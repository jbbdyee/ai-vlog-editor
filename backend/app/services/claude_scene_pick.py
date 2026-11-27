"""TODO 43: Claude picks the scenes — looks at every scene's pictures and speech and decides what goes in the vlog.

Direction change (2026-11-26): Cutory does the fixed work (transcribing, cutting the day into scenes, pictures,
rendering); Claude makes the judgement. Before this, the small local AI grouped the scenes into chapters and the
taste scores (TODO 32-4) only decided what to leave out when there were too many.

Two steps, one paid run:
  1) per chunk of scenes (two pictures each): a 0~3 score, the part worth using (seconds inside the scene), a short
     note of what happens and why
  2) text only, every note at once: the day's chapters and the final scenes for the target length
43-2: build what would be sent and estimate the bill (no call).
43-3: the run; the answer is saved in outputs/projects/<id>/claude_scene_pick.json (the edit plan is not touched).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from uuid import UUID

from backend.app.services import edit_brain
from backend.app.services.taste_score import filmed_clock

MODEL_DEFAULT = "claude-sonnet-5-5"  # same as the finishing (TODO 41): judging a scene from pictures needs Sonnet
PICTURE_WIDTH = 480
PICTURES_PER_SCENE = 2
PICTURE_SPOTS = (1 / 3, 2 / 3)  # a shaky or turning shot shows in one of two moments
IMAGE_TOKENS = 173  # a 480x270 picture is about (480 x 270) / 750 tokens
CHUNK_SCENES = 50  # a request carries at most 100 pictures: 50 scenes x 2
CHARS_PER_TOKEN = 1.0  # Korean is about one token per character (TODO 32-4)
SPEECH_LIMIT = 400  # longer than the finishing: picking the part to use needs the timed lines
OUT_PER_SCENE = 70  # step 1: score, part, short note as JSON
THINK_PER_SCENE = 120  # extra output when Claude thinks first (upper end)
NOTE_CHARS_PER_SCENE = 70  # step 2 input: one line per scene from step 1
OUT_STEP2_PER_SCENE = 12  # step 2 output: scene numbers inside chapters
OUT_STEP2_BASE = 600  # titles, chapter descriptions, wrapper

SYSTEM_STEP1 = (
    "너는 이 사용자의 하루 브이로그에 어떤 장면을 쓸지 고르는 편집자다. 장면마다 사진 2장(장면의 1/3·2/3 지점)과 "
    "시각이 붙은 대사가 온다. 사진이 장면 설명보다 정확하니 사진을 믿어라. [나]는 사용자(영상 주인) 목소리, [남]은 다른 "
    "사람 목소리다(자동 구분이라 틀릴 수 있다). 사용자의 규칙과 직접 쓴 취향 글이 가장 중요한 기준이다."
)


@dataclass(frozen=True)
class SpeechLine:
    start: float
    end: float
    text: str
    speaker: str | None  # "me" | "other" | None


@dataclass(frozen=True)
class SceneRow:
    number: int  # 1-based, in filming order
    candidate_id: UUID
    source_video_id: UUID
    start: float  # seconds in the source video
    end: float
    clock: str  # time of day it was filmed, "" when unknown
    speech: str  # "[나 0.0] ... / [남 3.2] ..." (seconds from the scene start)
    caption: str

    @property
    def length(self) -> float:
        return round(self.end - self.start, 1)

    def line(self) -> str:
        return (f"{self.number}번 장면 {self.clock or '시각 모름'} 길이 {self.length}초 | 대사: {self.speech or '(없음)'}"
                f" | 화면 설명: {self.caption or '(없음)'}")


def timed_speech(lines: Sequence[SpeechLine], start: float, end: float, limit: int = SPEECH_LIMIT) -> str:
    marks = {"me": "나", "other": "남"}
    parts = [f"[{marks.get(line.speaker or '', '?')} {max(0.0, line.start - start):.1f}] {line.text}" for line in lines
             if line.end > start and line.start < end]
    text = " / ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def scene_rows(inputs) -> list[SceneRow]:
    """inputs: longform_chat.ChatInputs — every active scene, sorted by the time of day it was filmed."""
    found = []
    for scene in inputs.scenes.values():
        lines = [SpeechLine(line.start, line.end, line.text, line.speaker)
                 for line in inputs.lines.get(scene.source_video_id, ())]
        found.append((filmed_clock(scene.filename, scene.found_start), scene, lines))
    found.sort(key=lambda item: (item[0] or "99", item[1].video_number, item[1].found_start))
    return [SceneRow(number, scene.candidate_id, scene.source_video_id, scene.found_start, scene.found_end, clock,
                     timed_speech(lines, scene.found_start, scene.found_end), (scene.caption or "").strip()[:120])
            for number, (clock, scene, lines) in enumerate(found, start=1)]


def picture_times(row: SceneRow) -> tuple[float, ...]:
    return tuple(round(row.start + (row.end - row.start) * spot, 3) for spot in PICTURE_SPOTS)


def header_text(rules: Sequence[str], brief: str, day_brief: str, reference: Sequence[str], target_minutes: float) -> str:
    """Everything except the scenes: sent with every chunk and with step 2."""
    parts = [f"목표 길이: 약 {target_minutes:g}분",
             "내 규칙:\n" + ("\n".join(f"- {text}" for text in rules) if rules else "(없음)"),
             f"내 편집 취향(사용자가 직접 씀):\n{brief.strip() or '(없음)'}",
             f"오늘 있었던 일(사용자 메모):\n{day_brief.strip() or '(없음)'}",
             "좋아하는 영상에서 잰 숫자:\n" + ("\n".join(f"- {text}" for text in reference) if reference else "(없음)")]
    return "\n\n".join(parts)


@dataclass(frozen=True)
class Estimate:
    scenes: int
    pictures: int
    chunks: int
    input_tokens: int
    output_tokens: int  # without thinking
    output_tokens_high: int  # with thinking
    usd_low: float
    usd_high: float


def estimate(model: str, header: str, rows: Sequence[SceneRow], pictures: int | None = None) -> Estimate:
    count = len(rows)
    pictures = PICTURES_PER_SCENE * count if pictures is None else pictures
    chunks = max(1, -(-count // CHUNK_SCENES))
    step1 = (len(SYSTEM_STEP1) + len(header)) * chunks + sum(len(row.line()) for row in rows)
    step2 = len(SYSTEM_STEP1) + len(header) + NOTE_CHARS_PER_SCENE * count
    input_tokens = int((step1 + step2) / CHARS_PER_TOKEN) + pictures * IMAGE_TOKENS
    output_low = OUT_PER_SCENE * count + OUT_STEP2_PER_SCENE * count + OUT_STEP2_BASE
    output_high = output_low + THINK_PER_SCENE * count
    return Estimate(count, pictures, chunks, input_tokens, output_low, output_high,
                    round(edit_brain.cost_usd(model, input_tokens, output_low), 4),
                    round(edit_brain.cost_usd(model, input_tokens, output_high), 4))


def model_name() -> str:
    return os.environ.get("CUTORY_PICK_MODEL") or MODEL_DEFAULT


# ---- 43-3: one paid run — step 1 per chunk with pictures, step 2 the day's chapters (text only) ----------------------

WHAT_CHARS = 25
WHY_CHARS = 30
TITLE_CHARS = 40
MIN_USE = 1.0  # a used part shorter than this is widened to the whole scene

TASK_STEP1 = (
    "아래 장면마다 빠짐없이(번호 n) 답하라.\n"
    "- score: 이 사용자가 완성 영상에 쓸 가능성. 3=꼭 씀, 2=쓰면 좋음, 1=짧게 넣거나 빼도 됨, 0=빼야 함\n"
    "- use_from, use_to: 장면 안에서 실제로 쓸 구간(장면 시작부터 몇 초). 대사 앞의 숫자가 그 말이 시작하는 초다. "
    "말이 중간에 끊기지 않게 문장 끝까지 넣고, 아무 일 없는 앞뒤는 잘라라. 쓸 게 없으면 0과 장면 길이\n"
    "- what: 무슨 일이 일어나는지 한국어 {what}자 이내\n"
    "- why: 쓰거나 빼는 이유 한국어 {why}자 이내"
)
SYSTEM_STEP2 = (
    "너는 이 사용자의 하루 브이로그를 짜는 편집자다. 장면마다 앞 단계에서 사진과 대사를 보고 남긴 메모(점수, 쓸 구간 길이, "
    "무슨 일, 이유)가 온다. 사용자의 규칙과 취향 글, 오늘 있었던 일 메모가 가장 중요한 기준이다."
)
TASK_STEP2 = (
    "목표 길이에 맞게 쓸 장면을 골라 하루 흐름대로 챕터로 묶어라.\n"
    "- 고른 장면의 쓸 구간 길이를 더한 값이 목표 길이({target}초)의 90~105%가 되게 골라라(메모 전체의 합은 {total}초)\n"
    "- 점수가 높은 장면을 먼저 쓰되, 하루의 시작과 끝, 이야기가 이어지게 하는 장면도 챙겨라\n"
    "- 장면 번호(n) 순서가 촬영 순서다. 챕터와 챕터 안의 장면은 촬영 순서를 지켜라\n"
    "- 챕터는 3~8개. title은 짧은 챕터 이름, description은 한 줄 설명, reason은 이 장면들을 고른 이유\n"
    "- 영상 전체의 title(한국어 {title}자 이내)과 summary(한 줄)도 써라"
)


def step1_schema() -> dict:
    scene = {"type": "object", "additionalProperties": False, "required": ["n", "score", "use_from", "use_to", "what", "why"],
             "properties": {"n": {"type": "integer"}, "score": {"type": "integer", "enum": [0, 1, 2, 3]},
                            "use_from": {"type": "number"}, "use_to": {"type": "number"},
                            "what": {"type": "string"}, "why": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["scenes"],
            "properties": {"scenes": {"type": "array", "items": scene}}}


def step2_schema() -> dict:
    chapter = {"type": "object", "additionalProperties": False, "required": ["title", "description", "reason", "scenes"],
               "properties": {"title": {"type": "string"}, "description": {"type": "string"}, "reason": {"type": "string"},
                              "scenes": {"type": "array", "items": {"type": "integer"}}}}
    return {"type": "object", "additionalProperties": False, "required": ["title", "summary", "chapters"],
            "properties": {"title": {"type": "string"}, "summary": {"type": "string"},
                           "chapters": {"type": "array", "items": chapter}}}


def _image_block(path: Path) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(Path(path).read_bytes()).decode("ascii")}}


def step1_blocks(header: str, chunk: Sequence[SceneRow], pictures: dict[UUID, Sequence[Path]]) -> list[dict]:
    task = TASK_STEP1.format(what=WHAT_CHARS, why=WHY_CHARS)
    blocks: list[dict] = [{"type": "text", "text": f"{header}\n\n{task}\n\n장면 {chunk[0].number}~{chunk[-1].number}번:"}]
    for row in chunk:
        blocks.append({"type": "text", "text": row.line()})
        blocks.extend(_image_block(path) for path in pictures.get(row.candidate_id, ()))
    return blocks


@dataclass(frozen=True)
class Note:
    row: SceneRow
    score: int
    use_from: float  # seconds from the scene start
    use_to: float
    what: str
    why: str

    @property
    def use_length(self) -> float:
        return round(self.use_to - self.use_from, 1)

    def line(self) -> str:
        return (f"{self.row.number}. {self.row.clock or '시각 모름'} | {self.score}점 | 쓸 구간 {self.use_length}초"
                f" | {self.what or '-'} | {self.why or '-'}")


def _number(value: object, top: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return round(min(max(number, 0.0), top), 1)


def read_step1(text: str, chunk: Sequence[SceneRow]) -> dict[int, Note]:
    """Claude's step 1 JSON -> notes for scenes of this chunk; a missing scene gets 1 point and the whole scene."""
    by_number = {row.number: row for row in chunk}
    notes: dict[int, Note] = {}
    for item in json.loads(text).get("scenes") or []:
        row = by_number.get(item.get("n")) if isinstance(item, dict) else None
        if row is None or row.number in notes or item.get("score") not in (0, 1, 2, 3):
            continue
        top = max(0.0, row.end - row.start)
        start, end = _number(item.get("use_from"), top), _number(item.get("use_to"), top)
        if end - start < MIN_USE:
            start, end = 0.0, round(top, 1)
        notes[row.number] = Note(row, int(item["score"]), start, end, str(item.get("what") or "")[:WHAT_CHARS],
                                 str(item.get("why") or "")[:WHY_CHARS])
    for row in chunk:
        notes.setdefault(row.number, Note(row, 1, 0.0, round(row.end - row.start, 1), "", "답 없음"))
    return notes


def step2_text(header: str, notes: Sequence[Note], target_seconds: float) -> str:
    total = round(sum(note.use_length for note in notes))
    task = TASK_STEP2.format(target=round(target_seconds), total=total, title=TITLE_CHARS)
    return f"{header}\n\n{task}\n\n장면 메모(번호. 시각 | 점수 | 쓸 구간 길이 | 무슨 일 | 이유):\n" + "\n".join(
        note.line() for note in notes)


def _picked(note: Note) -> dict:
    row = note.row
    return {"number": row.number, "candidate_id": str(row.candidate_id), "source_video_id": str(row.source_video_id),
            "clock": row.clock, "scene_start": row.start, "scene_end": row.end,
            "clip_start": round(row.start + note.use_from, 3), "clip_end": round(row.start + note.use_to, 3),
            "score": note.score, "what": note.what, "why": note.why}


def read_step2(text: str, notes: dict[int, Note]) -> dict:
    """Chapters with known scene numbers only, each scene once, in filming order inside a chapter."""
    data = json.loads(text)
    used: set[int] = set()
    chapters = []
    for chapter in data.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        numbers = sorted({n for n in chapter.get("scenes") or [] if isinstance(n, int) and n in notes and n not in used})
        if not numbers:
            continue
        used.update(numbers)
        chapters.append({"title": str(chapter.get("title") or "")[:TITLE_CHARS],
                         "description": str(chapter.get("description") or ""), "reason": str(chapter.get("reason") or ""),
                         "scenes": [_picked(notes[n]) for n in numbers]})
    chapters.sort(key=lambda chapter: chapter["scenes"][0]["number"])
    left_out = [_picked(notes[n]) for n in sorted(notes) if n not in used]
    return {"title": str(data.get("title") or "")[:TITLE_CHARS], "summary": str(data.get("summary") or ""),
            "chapters": chapters, "left_out": left_out}


AskBlocks = Callable[[str, object, dict], tuple[str, int, int]]  # (system, text or blocks, schema) -> (json, in, out)


@dataclass(frozen=True)
class Picked:
    result: dict
    input_tokens: int
    output_tokens: int
    pictures: int


def pick(header: str, rows: Sequence[SceneRow], pictures: dict[UUID, Sequence[Path]], target_seconds: float,
         ask: AskBlocks) -> Picked:
    notes: dict[int, Note] = {}
    used_in = used_out = 0
    for first in range(0, len(rows), CHUNK_SCENES):
        chunk = rows[first:first + CHUNK_SCENES]
        text, input_tokens, output_tokens = ask(SYSTEM_STEP1, step1_blocks(header, chunk, pictures), step1_schema())
        used_in, used_out = used_in + input_tokens, used_out + output_tokens
        notes.update(read_step1(text, chunk))
    ordered = [notes[n] for n in sorted(notes)]
    text, input_tokens, output_tokens = ask(SYSTEM_STEP2, step2_text(header, ordered, target_seconds), step2_schema())
    return Picked(read_step2(text, notes), used_in + input_tokens, used_out + output_tokens,
                  sum(len(pictures.get(row.candidate_id, ())) for row in rows))


def result_path(output_root: Path, project_id: UUID) -> Path:
    """Claude's choice lives here (Git-ignored outputs/); the edit plan changes only when I press the button (43-4)."""
    return Path(output_root) / str(project_id) / "claude_scene_pick.json"


def save_result(output_root: Path, project_id: UUID, done: Picked, *, model: str, target_minutes: float) -> dict:
    used = sum(scene["clip_end"] - scene["clip_start"] for chapter in done.result["chapters"] for scene in chapter["scenes"])
    data = {"made_at": datetime.now(timezone.utc).isoformat(), "model": model, "target_minutes": target_minutes,
            "input_tokens": done.input_tokens, "output_tokens": done.output_tokens,
            "usd": round(edit_brain.cost_usd(model, done.input_tokens, done.output_tokens), 4),
            "pictures": done.pictures, "total_seconds": round(used, 1), **done.result}
    path = result_path(output_root, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)
    return data


def load_result(output_root: Path, project_id: UUID) -> dict | None:
    try:
        data = json.loads(result_path(output_root, project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---- TODO 43 다음(A): widen Claude's parts to the '한 컷 M초 안팎' rule, no AI call ----------------------------------

MERGE_GAP = 1.0  # picked scenes this close in the same video (nothing between) become one cut
MINE_FIRST = 4  # a cut where I talk is left out last (above Claude's best score 3)


def _scene_key(scene: dict) -> tuple[str, float]:
    return str(scene["source_video_id"]), float(scene["scene_start"])


def widen(result: dict, timing: dict, target_seconds: float, typical_cut: float | None = None,
          mine: set | frozenset = frozenset(), max_cut: float | None = None) -> dict | None:
    """Claude's picks -> cuts of about the usual length: back-to-back picked scenes merge, the lowest scores go when
    there are too many, the rest widen around Claude's part (never into a scene Claude scored 0). Saves nothing."""
    from backend.app.services.story_length import Moment, fit_to_length
    from backend.app.services.story_select import SceneVoice, leave_out

    chapters = result.get("chapters") or []
    every = [s for chapter in chapters for s in chapter.get("scenes") or []] + list(result.get("left_out") or [])
    if not any(chapter.get("scenes") for chapter in chapters):
        return None
    in_video: dict[str, list[dict]] = {}
    for scene in every:
        in_video.setdefault(str(scene["source_video_id"]), []).append(scene)
    for scenes in in_video.values():
        scenes.sort(key=lambda s: float(s["scene_start"]))
    place = {_scene_key(s): i for scenes in in_video.values() for i, s in enumerate(scenes)}

    groups: list[dict] = []  # one cut each, in day order
    for index, chapter in enumerate(chapters):
        last = None
        for scene in chapter.get("scenes") or []:
            video = str(scene["source_video_id"])
            if (last is not None and video == str(last["source_video_id"])
                    and place[_scene_key(scene)] == place[_scene_key(last)] + 1
                    and float(scene["scene_start"]) - float(last["scene_end"]) <= MERGE_GAP):
                group = groups[-1]
                group["scenes"].append(scene)
                group["end"] = max(group["end"], float(scene["clip_end"]))
            else:
                groups.append({"chapter": index, "scenes": [scene], "start": float(scene["clip_start"]),
                               "end": float(scene["clip_end"])})
            last = scene
    merged = sum(len(g["scenes"]) - 1 for g in groups)
    for group in groups:
        group["id"] = UUID(str(group["scenes"][0]["candidate_id"]))
        group["video"] = UUID(str(group["scenes"][0]["source_video_id"]))
        group["mine"] = any(UUID(str(s["candidate_id"])) in mine for s in group["scenes"])
        group["score"] = max(int(s.get("score") or 0) for s in group["scenes"])

    out = set(leave_out([SceneVoice(g["id"], g["video"], g["end"] - g["start"],
                                    taste=MINE_FIRST if g["mine"] else g["score"]) for g in groups],
                        target_seconds, False, typical_cut))
    kept = [g for g in groups if g["id"] not in out]

    walls = []
    for group in kept:
        scenes = in_video[str(group["video"])]
        first, final = place[_scene_key(group["scenes"][0])], place[_scene_key(group["scenes"][-1])]
        low = max([float(s["scene_end"]) for s in scenes[:first] if int(s.get("score") or 0) == 0], default=0.0)
        high = min([float(s["scene_start"]) for s in scenes[final + 1:] if int(s.get("score") or 0) == 0],
                   default=float("inf"))
        walls.append((low, high))
    fit = fit_to_length([Moment(g["video"], g["start"], g["end"]) for g in kept], timing, target_seconds, walls)
    clips = []
    for group, (start, end) in zip(kept, fit.clips):
        if max_cut and not group["mine"] and end - start > max_cut + 1e-3:
            middle = (start + end) / 2
            start, end = round(middle - max_cut / 2, 3), round(middle + max_cut / 2, 3)
        clips.append({"candidate_id": str(group["id"]), "source_video_id": str(group["video"]),
                      "numbers": [s["number"] for s in group["scenes"]], "chapter": group["chapter"],
                      "start": start, "end": end, "picked_start": group["start"], "picked_end": group["end"]})
    lengths = sorted(c["end"] - c["start"] for c in clips)
    middle = len(lengths) // 2
    median = lengths[middle] if len(lengths) % 2 else (lengths[middle - 1] + lengths[middle]) / 2
    return {"clips": clips, "cuts": len(clips), "median_seconds": round(median, 1),
            "total_seconds": round(sum(lengths), 1), "merged": merged, "left_out": len(groups) - len(kept),
            "typical_cut": typical_cut}
