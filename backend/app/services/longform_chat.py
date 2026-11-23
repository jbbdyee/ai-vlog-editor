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
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import SourceVideo
from backend.app.services import claude_finishing, cut_effects, sound_effects, speaker_voice, taste_log
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


_OTHER_SCENE = re.compile(r"(다른|딴)\s*(장면|컷|거|걸|것|부분|데)")


def replace_request(message: str, here: int | None) -> int | None | Literal[False]:
    """TODO 27: "다른 장면으로" / "9번 다른 거" / "바꿔 줘" -> the cut to replace (None = which cut is unclear).
    False when the sentence is not asking for another scene."""
    text = _STAMP.sub("", message).strip()
    numbers = [int(value) for value in _NUMBER.findall(text)]
    asked = bool(_OTHER_SCENE.search(text)) or (
        len(numbers) < 2 and bool(re.search(r"(바꿔|바꾸|교체)", text))
        and not re.search(r"자리|순서|이랑|하고|랑|앞|뒤|길|짧|늘|줄|안\s*쓴", text))
    if not asked or re.search(r"안\s*쓴", text):
        return False
    if numbers:
        return numbers[0]
    return here


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
               recent: Sequence[str] = (), rules: Sequence[str] = ()) -> Understood:
    found = cut_at(inputs.cuts, at_seconds)
    here = found[0] + 1 if found else None
    edits = rule_edits(message, here, len(inputs.cuts))
    if edits is not None:
        return Understood(tuple(_fill_here(edit, found, here) for edit in edits), "rule")
    if brain is None:
        raise ChatEditError("BRAIN_UNAVAILABLE", "이 말은 규칙으로 못 알아들었어요. 편집 두뇌(AI)가 켜져 있지 않습니다.")
    rule_block = ("[내 편집 규칙 (사용자가 저장함. 시킨 고치기를 할 때 지킨다. 규칙만 보고 다른 컷을 스스로 고치지는 않는다)]\n"
                  + "\n".join(f"- {rule}" for rule in rules) + "\n\n") if rules else ""
    system = (SYSTEM_PROMPT + "\n\n" + rule_block
              + (f"[오늘 있었던 일 (사용자가 적음)]\n{inputs.brief}\n\n" if inputs.brief else "") + plan_table(inputs))
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


# --- 2b. "다른 장면으로": choices to swap one cut for (TODO 27) -----------------------------------------------------------

MAX_CHOICES = 6
MAX_UNUSED_CHOICES = 4


@dataclass(frozen=True)
class Choice:
    candidate_id: UUID  # an unused scene, or the replaced cut's own scene ("same": another part of its video)
    source_video_id: UUID
    start: float
    end: float
    kind: Literal["unused", "same"]
    label: str

    def as_dict(self) -> dict:
        return {"candidate_id": str(self.candidate_id), "source_video_id": str(self.source_video_id),
                "start_seconds": self.start, "end_seconds": self.end, "kind": self.kind, "label": self.label}


def _free_parts(low: float, high: float, used: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    parts, at = [], low
    for start, end in sorted(used):
        if start > at:
            parts.append((at, min(start, high)))
        at = max(at, end)
    if at < high:
        parts.append((at, high))
    return [(a, b) for a, b in parts if b - a > 0]


def replacement_choices(inputs: ChatInputs, index: int) -> list[Choice]:
    """Closest in filming first: unused scenes (nearest video, nearest moment), then parts of the same video that
    no cut uses, cut to the same length as the cut being replaced."""
    cut = inputs.cuts[index]
    scene = inputs.scenes[cut.candidate_id]
    middle = (cut.start + cut.end) / 2

    def stem(info: SceneInfo) -> str:
        numbers = re.findall(r"\d{3,}", Path(info.filename).stem)  # "DJI_20261112110921_0802_D" -> "0802"
        return numbers[-1] if numbers else (Path(info.filename).stem or f"영상 {info.video_number}")

    def closeness(info: SceneInfo, seconds: float) -> tuple[int, float]:
        return abs(info.video_number - scene.video_number), abs(seconds - middle)

    numbered = list(enumerate(inputs.unused(), start=1))
    numbered.sort(key=lambda pair: closeness(pair[1], (pair[1].found_start + pair[1].found_end) / 2))
    low, high = _bounds(inputs, cut)
    used = [(other.start, other.end) for other in inputs.cuts
            if inputs.scenes[other.candidate_id].source_video_id == scene.source_video_id]
    length = cut.length
    windows: list[tuple[float, float, float]] = []
    for part_start, part_end in _free_parts(low, high, used):
        size = part_end - part_start
        if size < max(MIN_CUT_SECONDS, min(length, max(2.0, length / 2))):
            continue
        width = min(length, size)
        # the middle of the free part, and (for a long one) the stretch one cut-length away from this cut
        starts_ = [part_start + (size - width) / 2]
        if size >= 4 * width:
            starts_.append(part_end - 2 * width if part_end <= cut.start else part_start + width)
        for begin in starts_:
            begin = round(min(max(begin, part_start), part_end - width), 3)
            windows.append((abs(begin + width / 2 - middle), begin, round(begin + width, 3)))
    windows.sort()
    same_room = min(len(windows), max(2, MAX_CHOICES - min(len(numbered), MAX_UNUSED_CHOICES)))
    out = [Choice(info.candidate_id, info.source_video_id, info.found_start, info.found_end, "unused",
                  f"안 쓴 장면 {number} · {stem(info)}")
           for number, info in numbered[: min(MAX_UNUSED_CHOICES, MAX_CHOICES - same_room)]]
    for _, begin, end in windows[:same_room]:
        out.append(Choice(cut.candidate_id, scene.source_video_id, begin, end, "same",
                          f"같은 영상 {begin:.0f}–{end:.0f}초"))
    return out[:MAX_CHOICES]


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


def _new_id() -> str:
    return uuid4().hex[:12]


# --- TODO 28: what the user chose, for rule candidates ---------------------------------------------------------------

def _tags(inputs: ChatInputs, candidate_id: UUID, start: float, end: float) -> tuple[str, ...]:
    scene = inputs.scenes.get(candidate_id)
    lines = inputs.lines.get(scene.source_video_id, ()) if scene else ()
    return tuple(taste_log.scene_tags(lines, start, end))


def _taste(inputs: ChatInputs, how: str, cut: Cut, from_seconds: float | None = None) -> taste_log.Choice:
    return taste_log.Choice(how, str(cut.candidate_id), _tags(inputs, cut.candidate_id, cut.start, cut.end), cut.length,
                            from_seconds)


def taste_from_change(inputs: ChatInputs, before: Sequence[Cut], after: Sequence[Cut]) -> list[taste_log.Choice]:
    """Removed / inserted / shortened / lengthened cuts between two plans (moves and swaps say nothing of taste)."""
    old = {cut.candidate_id: cut for cut in before}
    new = {cut.candidate_id: cut for cut in after}
    out = [_taste(inputs, "removed", cut) for key, cut in old.items() if key not in new]
    out += [_taste(inputs, "inserted", cut) for key, cut in new.items() if key not in old]
    for key, cut in new.items():
        if key in old and abs(cut.length - old[key].length) >= 0.3:
            out.append(_taste(inputs, "shortened" if cut.length < old[key].length else "longer", cut, old[key].length))
    return out


def recent_lines(messages: Sequence[dict], limit: int = 6) -> list[str]:
    """What the brain sees of the chat: undone requests and undo notices are left out (TODO 27), so a request the
    user took back is not done again."""
    kept = [item for item in messages if not item.get("undone") and not item.get("undo")]
    return [f"{'나' if item.get('role') == 'user' else '편집 보조'}: {item.get('text', '')}" for item in kept[-limit:]]


def _reply_text(applied: Applied, understood: Understood) -> str:
    """The reply never claims more than what was done (TODO 27): with no change it says so first."""
    if applied.done:
        return understood.reply or "바로 고쳤어."
    if understood.edits:
        return "바뀐 것 없음. 말한 대로 고칠 수 있는 컷이 없었어."
    if understood.reply:
        return f"바뀐 것 없음. {understood.reply}"
    return "바뀐 것 없음. 고칠 곳을 못 찾았어. 번호나 멈춘 곳으로 다시 알려 줘."


def send_message(session: Session, output_root: Path, project_id: UUID, message: str, at_seconds: float | None,
                 brain: Brain | None, rules: Sequence[str] = ()) -> SendResult:
    message = (message or "").strip()
    if not message:
        raise ChatEditError("EMPTY_MESSAGE", "고칠 내용을 적어 주세요.")
    inputs = load_inputs(session, output_root, project_id)
    if not inputs.cuts:
        raise ChatEditError("NO_EDIT_PLAN", "아직 편집안이 없어요. 먼저 첫 편집안을 만들어 주세요.")
    chat = load_chat(output_root, project_id)
    recent = recent_lines(chat["messages"])
    user_id = _new_id()
    chat["messages"].append({"id": user_id, "role": "user", "text": message, "at_seconds": at_seconds, "at": _now()})

    found = cut_at(inputs.cuts, at_seconds)
    sound = cut_effects.sound_request(message, found[0] + 1 if found else None, found[1] if found else None)
    if sound is not False:  # before words: "여기 효과음 '쿵' 넣어" is a sound, not a reaction word
        return _set_sound(output_root, project_id, chat, inputs, sound, user_id, message)
    words = cut_effects.text_request(message, found[0] + 1 if found else None, found[1] if found else None)
    if words is not False:  # before zoom: "여기 '확대' 띄워" is a word, not a zoom
        return _set_text(output_root, project_id, chat, inputs, words, user_id, message)
    zoom = cut_effects.zoom_request(message, found[0] + 1 if found else None)
    if zoom is not False:
        return _set_zoom(output_root, project_id, chat, inputs, zoom[0], zoom[1], user_id, message)
    wanted = replace_request(message, found[0] + 1 if found else None)
    if wanted is not False:
        return _offer_choices(output_root, project_id, chat, inputs, wanted, user_id)

    try:
        understood = understand(message, inputs, at_seconds, brain, recent, rules)
    except ChatEditError as error:
        chat["messages"].append({"id": _new_id(), "reply_to": user_id, "role": "assistant", "text": error.message,
                                 "error": error.code, "at": _now()})
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
    reply_id = _new_id()
    if applied.done:
        snapshot = _snapshot(inputs.cuts, message[:80])
        snapshot["marks"] = [user_id, reply_id]
        chat["history"].append(snapshot)
        _save_plan(session, project_id, applied.cuts)
        taste_log.record(output_root, project_id, reply_id, taste_from_change(inputs, inputs.cuts, applied.cuts))
    chat["messages"].append({"id": reply_id, "reply_to": user_id, "role": "assistant", "text": _reply_text(applied, understood),
                             "done": list(applied.done), "skipped": list(applied.skipped), "no_change": not applied.done,
                             "engine": understood.engine, "changed": [str(value) for value in applied.changed], "at": _now()})
    save_chat(output_root, project_id, chat)
    return SendResult(applied.done, applied.skipped, applied.changed, understood.engine)


def _change_effect(output_root: Path, project_id: UUID, chat: dict, inputs: ChatInputs, number: int | None,
                   user_id: str, message: str, change) -> SendResult:
    """TODO 40: an effect for the finished video is saved per cut; the plan stays and undo brings the old effects.
    ``change(effects, number, cut)`` gives (new effects, done line), or the reason text when nothing changes."""
    reply: dict = {"id": _new_id(), "reply_to": user_id, "role": "assistant", "engine": "rule", "at": _now()}
    done: tuple[str, ...] = ()
    changed: frozenset[UUID] = frozenset()
    if number is None or not 1 <= number <= len(inputs.cuts):
        reply.update(text="어느 컷인지 모르겠어. 영상을 멈추거나 컷을 누른 뒤 다시 말해 줘." if number is None
                     else f"{number}번 컷이 없어. 컷 띠의 번호로 다시 알려 줘.", no_change=True)
    else:
        cut = inputs.cuts[number - 1]
        effects = cut_effects.load_effects(output_root, project_id)
        outcome = change(effects, number, cut)
        if isinstance(outcome, str):
            reply.update(text=f"바뀐 것 없음. {outcome}", no_change=True)
        else:
            snapshot = _snapshot(inputs.cuts, message[:80])
            snapshot["marks"] = [user_id, reply["id"]]
            snapshot["effects"] = effects
            chat["history"].append(snapshot)
            cut_effects.save_effects(output_root, project_id, outcome[0])
            done = (outcome[1],)
            changed = frozenset({cut.candidate_id})
            reply.update(text=outcome[1] + ". 완성 영상(영상 만들기)에서 보여.", done=list(done), skipped=[],
                         no_change=False, changed=[str(cut.candidate_id)])
    chat["messages"].append(reply)
    save_chat(output_root, project_id, chat)
    return SendResult(done, (), changed, "rule")


def _set_zoom(output_root: Path, project_id: UUID, chat: dict, inputs: ChatInputs, number: int | None,
              zoom: str | None, user_id: str, message: str) -> SendResult:
    """TODO 40-1: "이 컷 확대" / "여기 천천히 줌" / "확대 빼"."""
    def change(effects: dict, number: int, cut: Cut):
        before = cut_effects.zoom_of(effects, cut.candidate_id)
        if before == zoom:
            return (f"{number}번 컷은 이미 "
                    f"{cut_effects.ZOOM_LABELS[zoom] + ' 들어가 있어' if zoom else '확대가 없어'}.")
        return (cut_effects.set_zoom(effects, cut.candidate_id, zoom),
                f"{number}번 컷에 {cut_effects.ZOOM_LABELS[zoom]} 넣었어" if zoom
                else f"{number}번 컷 {cut_effects.ZOOM_LABELS[before]} 뺐어")
    return _change_effect(output_root, project_id, chat, inputs, number, user_id, message, change)


def _set_text(output_root: Path, project_id: UUID, chat: dict, inputs: ChatInputs,
              request: cut_effects.TextRequest, user_id: str, message: str) -> SendResult:
    """TODO 40-2: "여기 '벌렁' 띄워" / "여기 (근데 갑자기) 넣어" at the paused second / "글자 빼"."""
    def change(effects: dict, number: int, cut: Cut):
        texts = cut_effects.texts_of(effects, cut.candidate_id)
        if request.words is None:
            kept = [item for item in texts if request.kind and item["kind"] != request.kind]
            if len(kept) == len(texts):
                return f"{number}번 컷에는 {cut_effects.TEXT_LABELS.get(request.kind or '', '글자')}가 없어."
            gone = ", ".join(cut_effects.text_label(item) for item in texts if item not in kept)
            return cut_effects.set_texts(effects, cut.candidate_id, kept), f"{number}번 컷 글자 {gone} 뺐어"
        at = round(min(request.at, cut.length), 1)
        item = {"kind": request.kind, "text": request.words, "at": at}
        if any(old["kind"] == item["kind"] and old["text"] == item["text"] for old in texts):
            return f"{number}번 컷에 이미 {cut_effects.text_label(item)}가 있어."
        kept = [old for old in texts if not (old["kind"] == item["kind"] and abs(old["at"] - at) < 0.05)]
        label = cut_effects.TEXT_LABELS[request.kind or "react"]
        return (cut_effects.set_texts(effects, cut.candidate_id, [*kept, item]),
                f"{number}번 컷 {at:.1f}초에 {label} {cut_effects.text_label(item)} 넣었어")
    return _change_effect(output_root, project_id, chat, inputs, request.number, user_id, message, change)


def _set_sound(output_root: Path, project_id: UUID, chat: dict, inputs: ChatInputs,
               request: cut_effects.SoundRequest, user_id: str, message: str) -> SendResult:
    """TODO 40-3: "여기 효과음 쿵" at the paused second / "효과음 빼"."""
    names = "·".join(sound_effects.NAMES)

    def change(effects: dict, number: int, cut: Cut):
        sounds = cut_effects.sounds_of(effects, cut.candidate_id)
        if not request.add:
            kept = [item for item in sounds if request.name and item["name"] != request.name]
            if len(kept) == len(sounds):
                return f"{number}번 컷에는 {'효과음 ' + request.name if request.name else '효과음'}이 없어."
            gone = ", ".join(item["name"] for item in sounds if item not in kept)
            return cut_effects.set_sounds(effects, cut.candidate_id, kept), f"{number}번 컷 효과음 {gone} 뺐어"
        if request.name is None:
            return f"어떤 소리를 넣을까? {names} 중에서 골라 줘. 예: 여기 효과음 쿵"
        at = round(min(request.at, cut.length), 1)
        if any(old["name"] == request.name and abs(old["at"] - at) < 0.05 for old in sounds):
            return f"{number}번 컷 {at:.1f}초에 이미 효과음 {request.name}이 있어."
        item = {"name": request.name, "at": at}
        return (cut_effects.set_sounds(effects, cut.candidate_id, [*sounds, item]),
                f"{number}번 컷 {at:.1f}초에 효과음 {request.name} 넣었어")
    return _change_effect(output_root, project_id, chat, inputs, request.number, user_id, message, change)


def _offer_choices(output_root: Path, project_id: UUID, chat: dict, inputs: ChatInputs, number: int | None,
                   user_id: str) -> SendResult:
    """TODO 27: "다른 장면으로" changes nothing yet; it answers with pictures to pick from."""
    reply: dict = {"id": _new_id(), "reply_to": user_id, "role": "assistant", "engine": "rule", "at": _now()}
    if number is None or not 1 <= number <= len(inputs.cuts):
        reply.update(text="어느 컷을 바꿀지 모르겠어. 영상을 멈추거나 컷을 누른 뒤 '다른 장면으로'라고 말해 줘."
                     if number is None else f"{number}번 컷이 없어. 컷 띠의 번호로 다시 알려 줘.", no_change=True)
        choices = []
    else:
        choices = replacement_choices(inputs, number - 1)
        cut = inputs.cuts[number - 1]
        reply.update(text=f"{number}번 컷({cut.length:.1f}초) 대신 넣을 장면이야. 눌러서 골라 줘." if choices
                     else f"{number}번 컷 대신 넣을 장면을 못 찾았어. 안 쓴 장면도, 같은 영상의 남은 부분도 없어.",
                     choices=[choice.as_dict() for choice in choices], for_cut=number,
                     for_candidate=str(cut.candidate_id), picked=None, no_change=not choices)
    chat["messages"].append(reply)
    save_chat(output_root, project_id, chat)
    return SendResult((), (), frozenset(), "rule")


def pick_choice(session: Session, output_root: Path, project_id: UUID, message_id: str, choice: int) -> SendResult:
    """TODO 27: put the picked picture in place of the cut (choice -1 = keep the cut as it is)."""
    chat = load_chat(output_root, project_id)
    offer = next((item for item in chat["messages"] if item.get("id") == message_id and item.get("choices")), None)
    if offer is None:
        raise ChatEditError("CHOICE_NOT_FOUND", "고를 장면 목록을 찾지 못했어요. 다시 '다른 장면으로'라고 말해 주세요.")
    if offer.get("picked") is not None:
        raise ChatEditError("CHOICE_ALREADY_PICKED", "이미 고른 목록이에요. 바꾸려면 되돌리기를 눌러 주세요.")
    if choice == -1:
        offer["picked"] = -1
        reply_id = _new_id()
        chat["messages"].append({"id": reply_id, "reply_to": message_id, "role": "assistant",
                                 "text": f"{offer.get('for_cut')}번 컷은 그대로 뒀어.", "no_change": True, "engine": "rule",
                                 "at": _now()})
        save_chat(output_root, project_id, chat)
        inputs = load_inputs(session, output_root, project_id)
        kept = next((cut for cut in inputs.cuts if str(cut.candidate_id) == offer.get("for_candidate")), None)
        taste_log.record(output_root, project_id, reply_id,
                         ([_taste(inputs, "kept", kept)] if kept else []) + _passed(inputs, offer["choices"], None))
        return SendResult((), (), frozenset(), "rule")
    if not 0 <= choice < len(offer["choices"]):
        raise ChatEditError("CHOICE_NOT_FOUND", "목록에 없는 장면이에요.")
    picked = offer["choices"][choice]
    inputs = load_inputs(session, output_root, project_id)
    target = UUID(offer["for_candidate"])
    index = next((i for i, cut in enumerate(inputs.cuts) if cut.candidate_id == target), None)
    new_id = UUID(picked["candidate_id"])
    in_plan = {cut.candidate_id for cut in inputs.cuts}
    if index is None or new_id not in inputs.scenes or (picked["kind"] == "unused" and new_id in in_plan):
        raise ChatEditError("CHOICE_STALE", "편집안이 그새 바뀌었어요. 다시 '다른 장면으로'라고 말해 주세요.")
    old = inputs.cuts[index]
    new = Cut(new_id, float(picked["start_seconds"]), float(picked["end_seconds"]))
    low, high = _bounds(inputs, new)
    if new.start < low - 1e-3 or new.end > high + 1e-3 or new.length < MIN_CUT_SECONDS - 1e-6:
        raise ChatEditError("CHOICE_STALE", "이 장면은 영상 범위를 벗어나서 넣을 수 없어요.")
    cuts = list(inputs.cuts)
    cuts[index] = new
    reply_id = _new_id()
    snapshot = _snapshot(inputs.cuts, f"{index + 1}번 컷을 {picked['label']}(으)로")
    snapshot["marks"] = [reply_id]
    snapshot["reopen"] = message_id
    chat["history"].append(snapshot)
    _save_plan(session, project_id, cuts)
    offer["picked"] = choice
    done = (f"{index + 1}번 컷 {old.length:.1f}초 → {picked['label']} ({new.length:.1f}초)로 바꿈",)
    chat["messages"].append({"id": reply_id, "reply_to": message_id, "role": "assistant", "text": "골라 준 장면으로 바꿨어.",
                             "done": list(done), "engine": "rule", "changed": [str(new_id)], "at": _now()})
    save_chat(output_root, project_id, chat)
    taste_log.record(output_root, project_id, reply_id,
                     [_taste(inputs, "picked", new), _taste(inputs, "replaced", old)] + _passed(inputs, offer["choices"], choice))
    return SendResult(done, (), frozenset({new_id}), "rule")


def _passed(inputs: ChatInputs, choices: Sequence[dict], picked: int | None) -> list[taste_log.Choice]:
    """The pictures that were shown but not picked."""
    out = []
    for index, item in enumerate(choices):
        if index == picked:
            continue
        try:
            cut = Cut(UUID(item["candidate_id"]), float(item["start_seconds"]), float(item["end_seconds"]))
        except (KeyError, TypeError, ValueError):
            continue
        out.append(_taste(inputs, "passed", cut))
    return out


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
    if isinstance(previous.get("effects"), dict):  # TODO 40: an effect change is undone like a plan change
        cut_effects.save_effects(output_root, project_id, previous["effects"])
    marks = set(previous.get("marks") or ())
    taste_log.mark_undone(output_root, marks)  # TODO 28: a taken-back change is not part of my taste
    for item in chat["messages"]:
        if item.get("id") in marks:
            item["undone"] = True  # TODO 27: not sent to the brain again, shown as taken back
        if previous.get("reopen") and item.get("id") == previous["reopen"]:
            item["picked"] = None  # the pictures can be picked again
    label = previous.get("label", "")
    before = {cut.candidate_id: (index, cut.start, cut.end) for index, cut in enumerate(inputs.cuts)}
    changed = [str(cut.candidate_id) for index, cut in enumerate(cuts)
               if before.get(cut.candidate_id) != (index, cut.start, cut.end)]
    chat["messages"].append({"id": _new_id(), "role": "assistant", "text": f"되돌렸어: {label}" if label else "되돌렸어.",
                             "undo": True, "changed": changed, "at": _now()})
    save_chat(output_root, project_id, chat)
    return label


def apply_finishing(session: Session, output_root: Path, project_id: UUID, wanted: Sequence[UUID] | None = None) -> int:
    """TODO 41-3: put Claude's saved suggestions into the cut effects (all, or only ``wanted`` cuts). Cuts that already
    have an effect stay as they are; one undo brings the effects from before."""
    saved = claude_finishing.load_result(output_root, project_id) or {}
    suggestions = [item for item in saved.get("suggestions") or [] if isinstance(item, dict)]
    inputs = load_inputs(session, output_root, project_id)
    lengths = {str(cut.candidate_id): cut.length for cut in inputs.cuts}
    numbers = {str(cut.candidate_id): index + 1 for index, cut in enumerate(inputs.cuts)}
    effects = cut_effects.load_effects(output_root, project_id)
    new, put = claude_finishing.merge(effects, suggestions, lengths,
                                      None if wanted is None else {str(item) for item in wanted})
    if not put:
        raise ChatEditError("NOTHING_TO_APPLY", "넣을 제안이 없어요. 이미 효과가 있는 컷은 그대로 둬요.")
    chat = load_chat(output_root, project_id)
    reply_id = _new_id()
    shown = ", ".join(f"{numbers[key]}번" for key in sorted(put, key=numbers.get))
    snapshot = _snapshot(inputs.cuts, f"Claude 제안 {len(put)}컷 넣기")
    snapshot["marks"] = [reply_id]
    snapshot["effects"] = effects
    chat["history"].append(snapshot)
    cut_effects.save_effects(output_root, project_id, new)
    chat["messages"].append({"id": reply_id, "role": "assistant", "engine": "claude-finishing", "at": _now(),
                             "text": f"Claude 제안을 {len(put)}컷에 넣었어({shown}). 완성 영상(영상 만들기)에서 보여. "
                                     "마음에 안 들면 되돌리기를 눌러 줘.",
                             "done": [f"{numbers[key]}번 컷 Claude 제안 넣음" for key in put], "skipped": [],
                             "no_change": False, "changed": put})
    save_chat(output_root, project_id, chat)
    return len(put)


def remake(session: Session, output_root: Path, project_id: UUID,
           clips: Sequence[tuple[UUID, float, float]]) -> int:
    """TODO 32: put a fresh recommendation in place of the plan; the plan before it stays one undo away."""
    inputs = load_inputs(session, output_root, project_id)
    cuts = [Cut(candidate_id, float(start), float(end)) for candidate_id, start, end in clips
            if candidate_id in inputs.scenes and end > start]
    if not cuts:
        raise ChatEditError("REMAKE_EMPTY", "새 추천에 넣을 장면이 없어요.")
    chat = load_chat(output_root, project_id)
    reply_id = _new_id()
    if inputs.cuts:
        snapshot = _snapshot(inputs.cuts, "추천으로 다시 만들기")
        snapshot["marks"] = [reply_id]
        chat["history"].append(snapshot)
    _save_plan(session, project_id, cuts)
    total = sum(cut.length for cut in cuts)
    chat["messages"].append({"id": reply_id, "role": "assistant", "engine": "rule", "at": _now(),
                             "text": f"추천으로 다시 만들었어: 컷 {len(cuts)}개, {clock(total)}. "
                                     "하루 시간 순서대로 줄 세웠어. 전 편집안이 낫다면 되돌리기를 눌러 줘.",
                             "changed": [str(cut.candidate_id) for cut in cuts]})
    save_chat(output_root, project_id, chat)
    return len(cuts)
