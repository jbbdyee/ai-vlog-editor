"""TODO 26: change the saved longform edit plan by talking to it, next to the video ("[03:12] 이 장면 짧게").

Same split as the reel chat (TODO 16): a sentence becomes a list of ``Edit`` objects, then Python checks and
applies them. Plain sentences ("3번 빼", "3번이랑 4번 바꿔", "여기서 끝내") are read by rules (free, instant);
anything else goes to the edit brain (Claude or the local AI, see ``edit_brain``), which only fills in the same
small form. Python owns every second: a cut never leaves its video and never gets shorter than 1 second.

Cut numbers are the numbers on the screen (1 = first cut of the plan). When the user paused the video, the
screen sends where (``at_seconds`` on the whole edit) and "여기 / 이 장면" means the cut playing there.

The plan itself stays in the existing edit-plan table (so rendering uses it as is). The chat, the last 10 plans
for undo and the brain usage live in ``outputs/projects/<id>/chat_edit.json`` (no database change).
File names are never sent to the brain; videos are "영상 1, 2, ..." in file-name order.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import SourceVideo
from backend.app.services import speaker_voice
from backend.app.services.day_brief import load_day_brief
from backend.app.services.edit_brain import Brain, cost_usd, parse_json
from backend.app.services.llm_edit_interpreter import LLMEditError
from backend.app.services.project_scene_candidates import list_active_project_candidates
from backend.app.services.project_scene_edit_plan import get_scene_edit_plan, save_scene_edit_plan

MIN_CUT_SECONDS = 1.0
DEFAULT_LONGER_SECONDS = 3.0
SHORTER_SHARE = 1 / 3  # "짧게" without a number takes a third off
MAX_HISTORY = 10
MAX_MESSAGES = 60
Action = Literal["remove", "shorter", "longer", "set_length", "trim_start", "trim_end", "move", "swap", "insert"]
ACTIONS: tuple[str, ...] = ("remove", "shorter", "longer", "set_length", "trim_start", "trim_end", "move", "swap",
                            "insert")


class ChatEditError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- inputs ----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SceneInfo:
    candidate_id: UUID
    source_video_id: UUID
    filename: str
    video_number: int
    found_start: float
    found_end: float
    caption: str | None


@dataclass(frozen=True)
class Line:
    start: float
    end: float
    text: str
    speaker: str | None  # "me" | "other" | None (voice step not run)


@dataclass(frozen=True)
class Cut:
    candidate_id: UUID
    start: float
    end: float

    @property
    def length(self) -> float:
        return round(self.end - self.start, 3)


@dataclass(frozen=True)
class ChatInputs:
    scenes: dict[UUID, SceneInfo]  # every active scene, in filmed order
    cuts: tuple[Cut, ...]  # the saved plan, valid scenes only
    durations: dict[UUID, float | None]
    lines: dict[UUID, tuple[Line, ...]]
    brief: str = ""
    dropped: int = 0  # plan rows whose scene is no longer active

    def unused(self) -> list[SceneInfo]:
        used = {cut.candidate_id for cut in self.cuts}
        return [scene for scene in self.scenes.values() if scene.candidate_id not in used]


def load_inputs(session: Session, output_root: Path, project_id: UUID) -> ChatInputs:
    candidates = list_active_project_candidates(session, project_id)  # raises SceneProjectNotFoundError
    sources = session.scalars(select(SourceVideo).where(SourceVideo.project_id == project_id)
                              .options(selectinload(SourceVideo.transcript))).all()
    ordered = sorted(sources, key=lambda row: (row.original_filename or "", str(row.id)))
    numbers = {row.id: index + 1 for index, row in enumerate(ordered)}
    names = {row.id: row.original_filename or str(row.id) for row in sources}
    durations = {row.id: float(row.duration_seconds) if row.duration_seconds is not None else None for row in sources}
    version = speaker_voice.load_my_voice(output_root, project_id).version
    lines: dict[UUID, tuple[Line, ...]] = {}
    for row in sources:
        segments = row.transcript.segments if row.transcript is not None and isinstance(row.transcript.segments, list) else []
        stored = speaker_voice.load_speaker_scores(output_root, project_id, row.id)
        scores = (stored.get("scores") if stored and version and stored.get("voice_version") == version
                  and stored.get("line_count") == len(segments) else None)
        out = []
        for index, segment in enumerate(segments):
            try:
                start, end, text = float(segment["start_seconds"]), float(segment["end_seconds"]), str(segment["text"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if text:
                out.append(Line(start, end, text, speaker_voice.speaker_label(scores[index]) if scores else None))
        lines[row.id] = tuple(out)
    scenes = {}
    for candidate in sorted(candidates, key=lambda c: (numbers.get(c.source_video_id, 0), float(c.start_seconds))):
        scenes[candidate.candidate_id] = SceneInfo(
            candidate.candidate_id, candidate.source_video_id, names.get(candidate.source_video_id, ""),
            numbers.get(candidate.source_video_id, 0), float(candidate.start_seconds), float(candidate.end_seconds),
            candidate.visual_caption)
    plan = get_scene_edit_plan(session, project_id)
    cuts = []
    for index, candidate_id in enumerate(plan.candidate_ids):
        scene = scenes.get(candidate_id)
        if scene is None:
            continue
        clip = plan.clip_ranges[index] if index < len(plan.clip_ranges) else None
        start, end = clip if clip else (scene.found_start, scene.found_end)
        cuts.append(Cut(candidate_id, float(start), float(end)))
    return ChatInputs(scenes, tuple(cuts), durations, lines, load_day_brief(output_root, project_id),
                      len(plan.candidate_ids) - len(cuts))


# --- timeline --------------------------------------------------------------------------------------------------------

def starts(cuts: Sequence[Cut]) -> list[float]:
    out, at = [], 0.0
    for cut in cuts:
        out.append(round(at, 3))
        at += cut.length
    return out


def cut_at(cuts: Sequence[Cut], seconds: float | None) -> tuple[int, float] | None:
    """0-based cut index playing at ``seconds`` on the whole edit, and how far into that cut."""
    if seconds is None or not cuts:
        return None
    for index, (begin, cut) in enumerate(zip(starts(cuts), cuts)):
        if seconds < begin + cut.length or index == len(cuts) - 1:
            return index, round(min(max(seconds - begin, 0.0), cut.length), 3)
    return None


def clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# --- 1. understanding the sentence -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Edit:
    action: Action
    cut: int | None = None  # 1-based number on the screen
    seconds: float | None = None
    to: int | None = None  # move / swap / insert: 1-based position (-1 = the end)
    scene: int | None = None  # insert: number in the "안 쓴 장면" list


_STAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}\]\s*")
_NUMBER = re.compile(r"(\d+)\s*번")
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*초")
_HERE = re.compile(r"여기|이\s*장면|이\s*컷|이거|이\s*부분|요기|지금")
_REMOVE = r"빼|삭제|지워|지우|없애|날려|버려|제외"
_SPLIT = re.compile(r"\s*(?:,|그리고|그다음|그\s*다음에?|(?<=[가-힣])고\s+(?=\d+\s*번))\s*")


def _clause_edit(text: str, here: int | None, count: int) -> Edit | None:
    numbers = [int(value) for value in _NUMBER.findall(text)]
    target = numbers[0] if numbers else (here if (_HERE.search(text) or here) else None)
    if re.search(r"마지막\s*(컷|장면)", text) and not numbers:
        target = count
    seconds_match = _SECONDS.search(text)
    seconds = float(seconds_match.group(1)) if seconds_match else None
    unused = re.search(r"안\s*쓴\s*(?:장면|컷)\s*(\d+)", text)
    if unused and re.search(r"넣|추가|살려|붙여", text):
        position = -1
        if re.search(r"맨\s*앞|처음", text):
            position = 1
        elif numbers and re.search(r"(\d+)\s*번\s*(앞|뒤|다음)", text):
            where = re.search(r"(\d+)\s*번\s*(앞|뒤|다음)", text)
            position = int(where.group(1)) + (0 if where.group(2) == "앞" else 1)
        elif here:
            position = here + 1
        return Edit("insert", scene=int(unused.group(1)), to=position)
    if len(numbers) >= 2 and re.search(r"바꿔|바꾸|교체|자리", text) and re.search(r"(이랑|하고|과|와|랑|,)", text):
        return Edit("swap", cut=numbers[0], to=numbers[1])
    if target is not None and re.search(r"(맨\s*앞|처음|첫\s*번째)\s*(으?로|에)", text):
        return Edit("move", cut=target, to=1)
    if target is not None and re.search(r"(맨\s*(뒤|끝)|마지막)\s*(으?로|에)", text):
        return Edit("move", cut=target, to=-1)
    if len(numbers) >= 2 and re.search(r"\d+\s*번\s*(앞|뒤|다음)\s*(으?로|에)", text):
        where = re.search(r"(\d+)\s*번\s*(앞|뒤|다음)\s*(으?로|에)", text)
        return Edit("move", cut=numbers[0], to=int(where.group(1)) + (0 if where.group(2) == "앞" else 1))
    if target is None:
        return None
    if re.search(r"여기\s*(서|에서)\s*(끝|끊|마무리|멈춰|잘라)", text):
        return Edit("trim_end", cut=target)  # at the paused point (filled in by understand)
    if re.search(r"여기\s*(서|에서)?\s*부터\s*(시작|보여|써|살려)?", text) and not re.search(_REMOVE, text):
        return Edit("trim_start", cut=target)
    if re.search(r"앞\s*부분|앞쪽|시작\s*부분", text) and re.search(r"잘라|빼|줄|없애|지워", text):
        return Edit("trim_start", cut=target, seconds=seconds)
    if re.search(r"뒷\s*부분|뒤쪽|끝\s*부분", text) and re.search(r"잘라|빼|줄|없애|지워", text):
        return Edit("trim_end", cut=target, seconds=seconds)
    if re.search(_REMOVE, text):
        return Edit("remove", cut=target)
    if seconds is not None and re.search(r"초\s*(로|만|정도로)", text):
        return Edit("set_length", cut=target, seconds=seconds)
    if re.search(r"짧게|줄여|줄이|짧아|빨리", text):
        return Edit("shorter", cut=target, seconds=seconds)
    if re.search(r"길게|늘려|늘리|길어|더\s*보여|더\s*넣", text):
        return Edit("longer", cut=target, seconds=seconds)
    return None


def rule_edits(message: str, here: int | None, count: int) -> list[Edit] | None:
    """Every clause must be understood; otherwise None (the brain reads the whole sentence)."""
    text = _STAMP.sub("", message).strip()
    clauses = [part for part in _SPLIT.split(text) if part.strip()]
    edits = []
    for clause in clauses or [text]:
        edit = _clause_edit(clause, here, count)
        if edit is None:
            return None
        edits.append(edit)
    return edits or None


class _AIEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str
    cut: int | None = None
    seconds: float | None = None
    to: int | None = None
    scene: int | None = None


class _AIReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    edits: list[_AIEdit] = Field(default_factory=list, max_length=40)
    reply: str = ""


def reply_schema() -> dict:
    nullable_int = {"type": ["integer", "null"]}
    return {
        "type": "object", "additionalProperties": False, "required": ["edits", "reply"],
        "properties": {
            "edits": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["action", "cut", "seconds", "to", "scene"],
                "properties": {"action": {"type": "string", "enum": list(ACTIONS)}, "cut": nullable_int,
                               "seconds": {"type": ["number", "null"]}, "to": nullable_int, "scene": nullable_int}}},
            "reply": {"type": "string"},
        },
    }


SYSTEM_PROMPT = (
    "너는 브이로그 편집 보조다. 사용자는 영상 주인('나')이고, 편집안을 보며 한국어로 고쳐 달라고 말한다. "
    "'지금 편집안'은 컷 번호 순서가 곧 재생 순서다. 말한 대로 고칠 목록 edits를 만든다.\n"
    "고치기 종류:\n"
    "- remove: cut번 컷을 뺀다.\n"
    "- shorter: cut번 컷을 짧게. seconds=줄일 초(말하지 않았으면 null).\n"
    "- longer: cut번 컷을 길게. seconds=늘릴 초(말하지 않았으면 null).\n"
    "- set_length: cut번 컷 길이를 seconds초로.\n"
    "- trim_start / trim_end: cut번 컷의 앞부분 / 뒷부분을 seconds초 잘라낸다(모르면 null).\n"
    "- move: cut번 컷을 to번 자리로 옮긴다(맨 끝은 -1).\n"
    "- swap: cut번과 to번 컷의 자리를 바꾼다.\n"
    "- insert: '안 쓴 장면' 목록의 scene번을 to번 자리에 넣는다(맨 끝은 -1).\n"
    "규칙: 번호는 목록에 있는 것만 쓴다. 번호는 모두 고치기 전 번호로 적는다. 사용자가 시킨 것만 고치고 다른 컷은 건드리지 않는다. "
    "내용으로 가리키면(예: 친구가 말하는 컷, 교실 장면) 대사·화면 설명·[나]/[다른 사람] 표시를 보고 맞는 컷을 모두 찾는다. "
    "'여기', '이 장면'은 사용자가 영상을 멈춘 컷이다. 못 알아들었거나 맞는 컷이 없으면 edits를 비우고 reply에 이유를 쓴다. "
    "reply에는 무엇을 왜 고쳤는지 한두 문장으로, 친구에게 말하듯 반말로 쓴다. JSON만 출력한다."
)


def _speech(lines: Sequence[Line], start: float, end: float, limit: int = 220) -> str:
    parts = []
    for line in lines:
        if line.start < end and start < line.end:
            mark = {"me": "[나] ", "other": "[다른 사람] "}.get(line.speaker or "", "")
            parts.append(mark + line.text)
    joined = " / ".join(parts)
    return joined[: limit - 1] + "…" if len(joined) > limit else joined or "(대사 없음)"


def plan_table(inputs: ChatInputs) -> str:
    rows = ["[지금 편집안]"]
    for number, (begin, cut) in enumerate(zip(starts(inputs.cuts), inputs.cuts), start=1):
        scene = inputs.scenes[cut.candidate_id]
        rows.append(f"{number}번 컷 | {clock(begin)}~{clock(begin + cut.length)} ({cut.length:.1f}초) | 영상 {scene.video_number} | "
                    f"대사: {_speech(inputs.lines.get(scene.source_video_id, ()), cut.start, cut.end)} | "
                    f"화면: {scene.caption or '(설명 없음)'}")
    rows.append("[안 쓴 장면]")
    for number, scene in enumerate(inputs.unused(), start=1):
        rows.append(f"장면 {number} | 영상 {scene.video_number} | {scene.found_end - scene.found_start:.1f}초 | "
                    f"대사: {_speech(inputs.lines.get(scene.source_video_id, ()), scene.found_start, scene.found_end, 160)} | "
                    f"화면: {scene.caption or '(설명 없음)'}")
    if len(rows) == 2 or rows[-1] == "[안 쓴 장면]":
        rows.append("(없음)")
    return "\n".join(rows)


@dataclass(frozen=True)
class Understood:
    edits: tuple[Edit, ...]
    engine: str  # "rule" | brain label
    reply: str = ""
    brain_key: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def understand(message: str, inputs: ChatInputs, at_seconds: float | None, brain: Brain | None,
               recent: Sequence[str] = ()) -> Understood:
    found = cut_at(inputs.cuts, at_seconds)
    here = found[0] + 1 if found else None
    edits = rule_edits(message, here, len(inputs.cuts))
    if edits is not None:
        return Understood(tuple(_fill_here(edit, found, here) for edit in edits), "rule")
    if brain is None:
        raise ChatEditError("BRAIN_UNAVAILABLE", "이 말은 규칙으로 못 알아들었어요. 편집 두뇌(AI)가 켜져 있지 않습니다.")
    system = SYSTEM_PROMPT + "\n\n" + (f"[오늘 있었던 일 (사용자가 적음)]\n{inputs.brief}\n\n" if inputs.brief else "") + plan_table(inputs)
    user = []
    if recent:
        user.append("[최근 대화]\n" + "\n".join(recent[-6:]))
    if found:
        user.append(f"[사용자가 영상을 멈춘 곳] {here}번 컷, 컷 시작에서 {found[1]:.1f}초 (전체 {clock(at_seconds or 0)})")
    user.append(f"[요청] {_STAMP.sub('', message).strip()}")
    try:
        answer = brain.ask(system, "\n".join(user), reply_schema())
        reply = _AIReply.model_validate(parse_json(answer.text))
    except ValidationError as error:
        raise ChatEditError("LLM_BAD_RESPONSE", "AI 답을 읽지 못했어요. 다시 말해 주세요.") from error
    except LLMEditError as error:
        raise ChatEditError(error.code, _brain_error(error.code)) from error
    edits = []
    for item in reply.edits:
        if item.action not in ACTIONS:
            continue
        edits.append(Edit(item.action, item.cut, item.seconds, item.to, item.scene))  # type: ignore[arg-type]
    return Understood(tuple(_guard(edits, message, len(inputs.cuts))), f"llm:{brain.key}/{brain.model}",
                      reply.reply.strip()[:400], brain.key, answer.input_tokens, answer.output_tokens)


def _brain_error(code: str) -> str:
    return {
        "LLM_TIMEOUT": "AI가 너무 오래 걸려서 멈췄어요. 다시 시도해 주세요.",
        "LLM_UNAVAILABLE": "AI에 연결하지 못했어요. 로컬 AI(Ollama)나 인터넷 연결을 확인해 주세요.",
        "CLAUDE_KEY_INVALID": "Claude API 키가 맞지 않아요. .env의 ANTHROPIC_API_KEY를 확인해 주세요.",
        "CLAUDE_RATE_LIMITED": "Claude 사용 한도에 걸렸어요. 잠시 뒤 다시 시도해 주세요.",
        "CLAUDE_REFUSED": "Claude가 이 요청을 처리하지 않았어요. 다르게 말해 주세요.",
    }.get(code, "AI가 답하지 못했어요. 다시 시도해 주세요.")


def _fill_here(edit: Edit, found: tuple[int, float] | None, here: int | None) -> Edit:
    """"여기서 끝내" / "여기부터 시작": the cut point is where the video was paused."""
    if edit.seconds is None and found and edit.cut == here:
        if edit.action == "trim_start":
            return replace(edit, seconds=found[1])
        if edit.action == "trim_end":
            return replace(edit, seconds=-found[1])  # negative = end at this point inside the cut
    return edit


def _guard(edits: list[Edit], message: str, count: int) -> list[Edit]:
    """The small local AI sometimes adds edits nobody asked for (TODO 16). Removing needs a removing word,
    and one message never removes more than half the cuts."""
    if not re.search(_REMOVE + r"|잘라|위주|만\s*남|필요\s*없|안\s*나오", message):
        edits = [edit for edit in edits if edit.action != "remove"]
    removes = [edit for edit in edits if edit.action == "remove"]
    if count and len(removes) > max(1, count // 2):
        edits = [edit for edit in edits if edit.action != "remove"] + removes[: max(1, count // 2)]
    return edits


# --- 2. applying -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Applied:
    cuts: tuple[Cut, ...]
    done: tuple[str, ...]
    skipped: tuple[str, ...]
    changed: frozenset[UUID] = field(default_factory=frozenset)


def _bounds(inputs: ChatInputs, cut: Cut) -> tuple[float, float]:
    duration = inputs.durations.get(inputs.scenes[cut.candidate_id].source_video_id)
    return 0.0, float(duration) if duration else max(cut.end, inputs.scenes[cut.candidate_id].found_end)


def _resize(inputs: ChatInputs, cut: Cut, new_length: float) -> Cut:
    """Grow or shrink around the cut's middle, staying inside the video."""
    low, high = _bounds(inputs, cut)
    new_length = max(MIN_CUT_SECONDS, min(new_length, high - low))
    middle = (cut.start + cut.end) / 2
    start = middle - new_length / 2
    start = min(max(start, low), high - new_length)
    return Cut(cut.candidate_id, round(start, 3), round(start + new_length, 3))


def apply_edits(inputs: ChatInputs, edits: Sequence[Edit]) -> Applied:
    cuts = list(inputs.cuts)
    original = list(inputs.cuts)
    unused = inputs.unused()
    done: list[str] = []
    skipped: list[str] = []
    changed: set[UUID] = set()

    def name(candidate_id: UUID) -> str:
        scene = inputs.scenes[candidate_id]
        return Path(scene.filename).stem or f"영상 {scene.video_number}"

    def index_of(number: int | None) -> int | None:
        """Numbers always mean the plan before this message; find where that cut is now."""
        if number is None or not 1 <= number <= len(original):
            return None
        wanted = original[number - 1].candidate_id
        return next((i for i, cut in enumerate(cuts) if cut.candidate_id == wanted), None)

    def slot(to: int | None) -> int:
        if to is None or to == -1 or to > len(original):
            return len(cuts)
        anchor = index_of(max(1, to))
        return anchor if anchor is not None else len(cuts)

    for edit in edits:
        if edit.action == "insert":
            if edit.scene is None or not 1 <= edit.scene <= len(unused):
                skipped.append(f"안 쓴 장면 {edit.scene}번은 목록에 없어요")
                continue
            scene = unused[edit.scene - 1]
            if any(cut.candidate_id == scene.candidate_id for cut in cuts):
                skipped.append(f"{name(scene.candidate_id)} 장면은 이미 들어가 있어요")
                continue
            position = slot(edit.to)
            new = Cut(scene.candidate_id, scene.found_start, scene.found_end)
            cuts.insert(position, new)
            changed.add(new.candidate_id)
            done.append(f"안 쓴 장면 {edit.scene} ({name(new.candidate_id)} · {new.length:.1f}초)을 {position + 1}번 자리에 넣음")
            continue
        index = index_of(edit.cut)
        if index is None:
            skipped.append(f"{edit.cut}번 컷이 없어서 건너뜀" if edit.cut else "어느 컷인지 몰라서 건너뜀 (번호나 영상을 멈춘 곳으로 알려 줘)")
            continue
        cut = cuts[index]
        label = f"{edit.cut}번 컷"
        if edit.action == "remove":
            if len(cuts) <= 1:
                skipped.append("마지막 남은 컷은 뺄 수 없어요")
                continue
            cuts.pop(index)
            changed.discard(cut.candidate_id)
            done.append(f"{label} 뺌 ({name(cut.candidate_id)} · {cut.length:.1f}초)")
        elif edit.action in ("shorter", "longer", "set_length"):
            if edit.action == "set_length":
                target = edit.seconds or cut.length
            elif edit.action == "shorter":
                target = cut.length - (abs(edit.seconds) if edit.seconds else cut.length * SHORTER_SHARE)
            else:
                target = cut.length + (abs(edit.seconds) if edit.seconds else DEFAULT_LONGER_SECONDS)
            new = _resize(inputs, cut, target)
            if abs(new.length - cut.length) < 0.05:
                skipped.append(f"{label}은 더 {'늘릴' if target > cut.length else '줄일'} 수 없어요 ({cut.length:.1f}초)")
                continue
            cuts[index] = new
            changed.add(cut.candidate_id)
            done.append(f"{label} {cut.length:.1f}초 → {new.length:.1f}초")
        elif edit.action in ("trim_start", "trim_end"):
            low, high = _bounds(inputs, cut)
            amount = edit.seconds
            if edit.action == "trim_start":
                cut_off = abs(amount) if amount is not None else cut.length * SHORTER_SHARE
                start, end = min(cut.start + cut_off, cut.end - MIN_CUT_SECONDS), cut.end
            else:
                # negative seconds = "end at this point inside the cut" (the paused point)
                if amount is not None and amount < 0:
                    end = cut.start + abs(amount)
                else:
                    end = cut.end - (abs(amount) if amount is not None else cut.length * SHORTER_SHARE)
                start, end = cut.start, max(end, cut.start + MIN_CUT_SECONDS)
            start, end = max(low, round(start, 3)), min(high, round(end, 3))
            if end - start < MIN_CUT_SECONDS - 1e-6 or abs((end - start) - cut.length) < 0.05:
                skipped.append(f"{label}은 더 잘라낼 수 없어요 ({cut.length:.1f}초)")
                continue
            cuts[index] = Cut(cut.candidate_id, start, end)
            changed.add(cut.candidate_id)
            side = "앞부분" if edit.action == "trim_start" else "뒷부분"
            done.append(f"{label} {side} 잘라냄: {cut.length:.1f}초 → {end - start:.1f}초")
        elif edit.action == "swap":
            other = index_of(edit.to)
            if other is None or other == index:
                skipped.append(f"{edit.to}번 컷이 없어서 자리를 못 바꿨어요")
                continue
            cuts[index], cuts[other] = cuts[other], cuts[index]
            changed.update({cuts[index].candidate_id, cuts[other].candidate_id})
            done.append(f"{edit.cut}번 ↔ {edit.to}번 자리 바꿈")
        elif edit.action == "move":
            moving = cuts.pop(index)
            if edit.to is None or edit.to == -1 or edit.to >= len(original):
                position = len(cuts)
            elif edit.to <= 1:
                position = 0
            else:
                anchor = index_of(edit.to)
                position = len(cuts) if anchor is None else anchor + (1 if anchor >= index else 0)
            cuts.insert(position, moving)
            if position == index:
                skipped.append(f"{label}은 이미 그 자리예요")
                continue
            changed.add(moving.candidate_id)
            done.append(f"{label} → {position + 1}번 자리로 옮김")
    return Applied(tuple(cuts), tuple(done), tuple(skipped), frozenset(changed))


# --- 3. the chat file (messages, undo history, brain usage) ----------------------------------------------------------

def _path(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "chat_edit.json"


def load_chat(output_root: Path, project_id: UUID) -> dict:
    try:
        data = json.loads(_path(output_root, project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("messages", [])
    data.setdefault("history", [])
    data.setdefault("usage", {})
    return data


def save_chat(output_root: Path, project_id: UUID, data: dict) -> None:
    path = _path(output_root, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["messages"] = data["messages"][-MAX_MESSAGES:]
    data["history"] = data["history"][-MAX_HISTORY:]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _snapshot(cuts: Sequence[Cut], label: str) -> dict:
    return {"ids": [str(cut.candidate_id) for cut in cuts], "ranges": [[cut.start, cut.end] for cut in cuts],
            "label": label}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_plan(session: Session, project_id: UUID, cuts: Sequence[Cut]) -> None:
    save_scene_edit_plan(session, project_id, tuple(cut.candidate_id for cut in cuts),
                         [(cut.start, cut.end) for cut in cuts])


@dataclass(frozen=True)
class SendResult:
    done: tuple[str, ...]
    skipped: tuple[str, ...]
    changed: frozenset[UUID]
    engine: str


def send_message(session: Session, output_root: Path, project_id: UUID, message: str, at_seconds: float | None,
                 brain: Brain | None) -> SendResult:
    message = (message or "").strip()
    if not message:
        raise ChatEditError("EMPTY_MESSAGE", "고칠 내용을 적어 주세요.")
    inputs = load_inputs(session, output_root, project_id)
    if not inputs.cuts:
        raise ChatEditError("NO_EDIT_PLAN", "아직 편집안이 없어요. 먼저 첫 편집안을 만들어 주세요.")
    chat = load_chat(output_root, project_id)
    recent = [f"{'나' if item.get('role') == 'user' else '편집 보조'}: {item.get('text', '')}" for item in chat["messages"][-6:]]
    chat["messages"].append({"role": "user", "text": message, "at_seconds": at_seconds, "at": _now()})
    try:
        understood = understand(message, inputs, at_seconds, brain, recent)
    except ChatEditError as error:
        chat["messages"].append({"role": "assistant", "text": error.message, "error": error.code, "at": _now()})
        save_chat(output_root, project_id, chat)
        raise
    if understood.brain_key:
        usage = chat["usage"].setdefault(understood.brain_key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})
        usage["calls"] += 1
        usage["input_tokens"] += understood.input_tokens
        usage["output_tokens"] += understood.output_tokens
        if brain is not None:
            usage["usd"] = round(usage["usd"] + cost_usd(brain.model, understood.input_tokens, understood.output_tokens), 6)
    applied = apply_edits(inputs, understood.edits)
    if applied.done:
        chat["history"].append(_snapshot(inputs.cuts, message[:80]))
        _save_plan(session, project_id, applied.cuts)
    reply = understood.reply or ("바로 고쳤어." if applied.done else "고칠 곳을 못 찾았어. 번호나 멈춘 곳으로 다시 알려 줘.")
    chat["messages"].append({"role": "assistant", "text": reply, "done": list(applied.done), "skipped": list(applied.skipped),
                             "engine": understood.engine, "changed": [str(value) for value in applied.changed], "at": _now()})
    save_chat(output_root, project_id, chat)
    return SendResult(applied.done, applied.skipped, applied.changed, understood.engine)


def undo(session: Session, output_root: Path, project_id: UUID) -> str:
    chat = load_chat(output_root, project_id)
    if not chat["history"]:
        raise ChatEditError("NOTHING_TO_UNDO", "되돌릴 고치기가 없어요.")
    inputs = load_inputs(session, output_root, project_id)
    previous = chat["history"].pop()
    cuts = []
    for raw_id, (start, end) in zip(previous["ids"], previous["ranges"]):
        candidate_id = UUID(raw_id)
        if candidate_id in inputs.scenes:
            cuts.append(Cut(candidate_id, float(start), float(end)))
    if not cuts:
        raise ChatEditError("UNDO_SCENES_GONE", "되돌릴 편집안의 장면이 더 이상 없어요.")
    _save_plan(session, project_id, cuts)
    label = previous.get("label", "")
    before = {cut.candidate_id: (index, cut.start, cut.end) for index, cut in enumerate(inputs.cuts)}
    changed = [str(cut.candidate_id) for index, cut in enumerate(cuts)
               if before.get(cut.candidate_id) != (index, cut.start, cut.end)]
    chat["messages"].append({"role": "assistant", "text": f"되돌렸어: {label}" if label else "되돌렸어.", "undo": True,
                             "changed": changed, "at": _now()})
    save_chat(output_root, project_id, chat)
    return label
