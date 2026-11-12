"""TODO 10: short-form reel draft from already-cut videos (like the user's Blo workflow).

Steps (Python owns every timestamp; the AI only picks shots and writes words):
1. ``analyze_shots``: split each source into shots (FFmpeg scene-change detection), cut very long shots into
   pieces, describe each shot with the local VLM and attach the speech heard in it.
2. ``build_draft``: the LLM picks a mode (when "auto"), a hook title, the hook shot, which shots to use and a short
   line per shot. Python then orders the shots by the mode's rule and sets each clip length from the chosen pace,
   never cutting a spoken line short, and fits the total to the target length.
Any AI failure falls back to a rule-only draft so the user always gets something to look at.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.services.llm_edit_interpreter import Completion, LLMEditError, configured_engine
from backend.app.services.reel_modes import AUTO_MODE, MIN_SHOT_SECONDS, MODE_BY_KEY, MODES, PACES
from backend.app.services.shot_structure import ShotDetectionConfig, ShotStructureError, detect_shot_structure
from backend.app.services.vlm_scene_captioner import VLMCaptionError, caption_interval, vlm_model

ANALYSIS_VERSION = "reel-shots-v1"
MAX_SHOT_SECONDS = 8.0  # longer shots are cut into pieces so each piece gets its own description
MAX_SHOTS = 80
SHOT_CONFIG = ShotDetectionConfig(threshold_percent=10.0, minimum_shot_duration_seconds=0.8)
# Whisper sometimes "hears" these stock phrases over music (TODO 10 sample: nobody said them).
HALLUCINATED_PHRASES = ("구독과 좋아요", "구독 좋아요", "시청해 주셔서", "시청해주셔서", "다음 영상에서", "자막 제공", "MBC 뉴스")


@dataclass(frozen=True)
class SourceInput:
    source_video_id: UUID
    filename: str
    path: Path
    duration_seconds: float
    transcript_segments: Sequence[dict] = ()


@dataclass(frozen=True)
class Shot:
    index: int  # 1-based, in filmed order across all sources
    source_video_id: str
    source_filename: str
    start_seconds: float
    end_seconds: float
    caption: str = ""
    speech: str = ""
    speech_start: float | None = None
    speech_end: float | None = None

    @property
    def length(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class ReelScene:
    shot_index: int
    source_video_id: str
    source_filename: str
    start_seconds: float
    end_seconds: float
    caption: str
    label: str = ""
    is_hook: bool = False
    shot_caption: str = ""


@dataclass(frozen=True)
class ReelDraft:
    format: str
    mode: str
    mode_label: str
    pace: str
    pace_label: str
    target_seconds: int
    total_seconds: float
    title: str
    engine: str
    scenes: tuple[ReelScene, ...]
    shot_count: int
    notes: tuple[str, ...] = ()
    fallback_reason: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


Detect = Callable[..., object]
Describe = Callable[[Path, float, float], str]


def analysis_fingerprint(sources: Sequence[SourceInput]) -> str:
    """Same videos + same detector/VLM = reuse the shots (changing mode or pace then skips the slow part)."""
    parts = [ANALYSIS_VERSION, vlm_model()] + [f"{s.source_video_id}:{s.duration_seconds:.3f}:{s.path.name}" for s in sources]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _vlm_describe(path: Path, start: float, end: float) -> str:
    try:
        return caption_interval(path, start, end).caption.caption
    except VLMCaptionError:
        return ""


def analyze_shots(sources: Sequence[SourceInput], *, detect: Detect = detect_shot_structure,
                  describe: Describe = _vlm_describe, on_progress: Callable[[int, int], None] | None = None) -> list[Shot]:
    pieces: list[tuple[SourceInput, float, float]] = []
    for source in sources:
        try:
            structure = detect(source.path, source_video_id=source.source_video_id,
                               duration_seconds=source.duration_seconds, config=SHOT_CONFIG)
            intervals = [(i.start_seconds, i.end_seconds) for i in structure.intervals]
        except ShotStructureError:
            intervals = [(0.0, source.duration_seconds)]
        for start, end in intervals:
            count = max(1, int(-(-(end - start) // MAX_SHOT_SECONDS)))  # ceil
            step = (end - start) / count
            for k in range(count):
                pieces.append((source, round(start + k * step, 3), round(start + (k + 1) * step, 3)))
    pieces = pieces[:MAX_SHOTS]
    shots = []
    for number, (source, start, end) in enumerate(pieces, start=1):
        if on_progress:
            on_progress(number - 1, len(pieces))
        speech = [seg for seg in source.transcript_segments if _real_speech(seg)
                  and float(seg["end_seconds"]) > start and float(seg["start_seconds"]) < end]
        shots.append(Shot(
            number, str(source.source_video_id), source.filename, start, end, describe(source.path, start, end)[:80],
            " ".join(str(seg["text"]).strip() for seg in speech)[:120],
            max(start, min(float(seg["start_seconds"]) for seg in speech)) if speech else None,
            min(end, max(float(seg["end_seconds"]) for seg in speech)) if speech else None))
    if on_progress:
        on_progress(len(pieces), len(pieces))
    return shots


def _real_speech(segment: dict) -> bool:
    text = str(segment.get("text", "")).strip()
    return bool(text) and not any(phrase in text for phrase in HALLUCINATED_PHRASES)


class _AIScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot: int
    caption: str = Field(min_length=1, max_length=40)
    label: str = Field(default="", max_length=24)


class _AIReel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    title: str = Field(min_length=1, max_length=40)
    hook_shot: int
    scenes: list[_AIScene] = Field(min_length=1, max_length=MAX_SHOTS)


SYSTEM_PROMPT = (
    "너는 인스타그램 릴스·유튜브 쇼츠 편집자다. 사람이 이미 한 번 컷편집한 영상의 장면 목록을 받는다. "
    "각 장면에는 번호, 길이, 화면 설명(AI가 본 화면), 들린 말이 있다. "
    "mode: 지정된 모드가 있으면 그대로, 'auto'면 내용에 가장 맞는 모드 키를 고른다. "
    "title: 첫 화면에 크게 띄울 짧은 제목(20자 이내). 보는 사람이 끝까지 보고 싶게 쓴다. "
    "hook_shot: 맨 앞에 둘 가장 눈길을 끄는 장면 번호. "
    "scenes: 릴스에 넣을 장면을 고르고 장면마다 caption(화면에 띄울 한국어 한 줄, 18자 이내)을 쓴다. "
    "들린 말이 있으면 그 말과 어울리게, 없으면 화면 설명을 보고 쓴다. 화면에 없는 내용을 지어내지 마라. "
    "모드 순서가 items면 같은 물건을 보여주는 장면들에 같은 label(물건 이름, 12자 이내)을 붙이고 "
    "새 물건의 첫 장면 caption은 '첫 번째', '두 번째'처럼 시작한다. items가 아니면 label은 빈 문자열로 둔다. "
    "목표 길이를 채울 만큼 장면을 고르되 비슷한 장면이 연달아 나오면 하나만 고른다. 목록에 있는 번호만 쓴다. JSON만 출력하라."
)


def _schema(shot_count: int) -> dict:
    schema = _AIReel.model_json_schema()
    numbers = {"type": "integer", "enum": list(range(1, shot_count + 1))}
    schema["properties"]["mode"] = {"type": "string", "enum": [m.key for m in MODES]}
    schema["properties"]["hook_shot"] = numbers
    schema["$defs"]["_AIScene"]["properties"]["shot"] = numbers
    return schema


def _user_prompt(shots: Sequence[Shot], mode_key: str, pace_seconds: float, target_seconds: int) -> str:
    modes = "\n".join(f"- {m.key}: {m.label} (순서 {m.order}, 제목 예: {m.title_example}, 문구 말투: {m.caption_style})"
                      for m in MODES)
    rows = "\n".join(
        f"[{s.index}] {s.length:.1f}초 | 화면: {s.caption or '설명 없음'}" + (f" | 말: {s.speech}" if s.speech else "")
        for s in shots)
    wanted = max(1, round(target_seconds / pace_seconds))
    return (f"모드 목록:\n{modes}\n\n지정된 모드: {mode_key}\n목표 길이: {target_seconds}초, 장면 하나당 약 {pace_seconds}초 "
            f"→ 약 {wanted}개 장면\n\n장면 목록(촬영 순서):\n{rows}")


def build_draft(shots: Sequence[Shot], *, mode_key: str, pace_key: str, target_seconds: int,
                engine: tuple[str, str, Completion] | None | object = ...) -> ReelDraft:
    if not shots:
        raise ValueError("no shots")
    if mode_key != AUTO_MODE and mode_key not in MODE_BY_KEY:
        raise ValueError("unknown mode")
    pace_label, pace_seconds = PACES[pace_key]
    engine = configured_engine() if engine is ... else engine
    by_index = {s.index: s for s in shots}
    ai: _AIReel | None = None
    fallback: str | None = None
    engine_name = "rule"
    if engine is None:
        fallback = "LLM_NOT_CONFIGURED"
    else:
        provider, model, complete = engine
        engine_name = f"llm:{provider}/{model}"
        try:
            raw = complete(SYSTEM_PROMPT, _user_prompt(shots, mode_key, pace_seconds, target_seconds), _schema(len(shots)))
            ai = _AIReel.model_validate_json(raw)
        except LLMEditError as error:
            fallback = error.code
        except (ValidationError, ValueError):
            fallback = "LLM_SCHEMA_INVALID"
    notes: list[str] = []
    if ai is not None:
        picked = [scene for scene in ai.scenes if scene.shot in by_index]
        if ai.hook_shot not in by_index or not picked:
            ai, fallback = None, "LLM_SCENES_INVALID"
    if ai is None:
        engine_name = "rule"
        mode = MODE_BY_KEY.get(mode_key) or MODE_BY_KEY["daily_vlog"]
        title = mode.label
        hook = shots[0].index
        lines = {s.index: (_short(s.caption) or "", "") for s in shots}
    else:
        mode = MODE_BY_KEY[mode_key] if mode_key != AUTO_MODE else MODE_BY_KEY.get(ai.mode, MODE_BY_KEY["daily_vlog"])
        title = ai.title.strip()[:40]
        hook = ai.hook_shot
        lines = {}
        for scene in ai.scenes:
            if scene.shot in by_index and scene.shot not in lines:
                lines[scene.shot] = (scene.caption.strip()[:40], scene.label.strip()[:24] if mode.order == "items" else "")
        if hook not in lines:
            lines[hook] = (_short(by_index[hook].caption), "")
    ordered = [hook] + sorted(index for index in lines if index != hook)
    clips = {index: _clip(by_index[index], pace_seconds) for index in ordered}
    ordered, clips, fit_notes = _fit(ordered, clips, by_index, lines, hook, target_seconds, pace_seconds)
    notes += fit_notes
    scenes = tuple(ReelScene(
        index, by_index[index].source_video_id, by_index[index].source_filename, clips[index][0], clips[index][1],
        lines[index][0], lines[index][1], index == hook, by_index[index].caption) for index in ordered)
    total = round(sum(scene.end_seconds - scene.start_seconds for scene in scenes), 3)
    return ReelDraft("short", mode.key, mode.label, pace_key, pace_label, target_seconds, total, title, engine_name,
                     scenes, len(shots), tuple(notes), fallback)


def _short(text: str) -> str:
    return text.strip()[:18]


def _clip(shot: Shot, pace_seconds: float) -> tuple[float, float]:
    """About ``pace_seconds`` from the middle of the shot, widened to keep a spoken line whole.

    The widening stops at twice the pace: song lyrics over music are also transcribed as "speech" and would
    otherwise make every dance shot run as long as the shot itself.
    """
    length = min(shot.length, max(pace_seconds, MIN_SHOT_SECONDS))
    if shot.speech_start is not None and shot.speech_end is not None:
        start = max(shot.start_seconds, min(shot.speech_start, shot.end_seconds - length))
        end = min(shot.end_seconds, max(shot.speech_end, start + length), start + max(length, pace_seconds * 2))
        return round(start, 3), round(end, 3)
    start = shot.start_seconds + (shot.length - length) / 2
    return round(start, 3), round(start + length, 3)


def _fit(ordered, clips, by_index, lines, hook, target, pace_seconds):
    notes = []
    total = lambda: sum(e - s for s, e in clips.values())  # noqa: E731
    # Too long: drop non-hook scenes from the middle outwards (keeps how the story starts and ends).
    while total() > target * 1.1 and len(ordered) > 2:
        rest = ordered[1:]
        drop = rest[len(rest) // 2] if len(rest) % 2 else rest[len(rest) // 2 - 1]
        ordered = [i for i in ordered if i != drop]
        clips.pop(drop)
    # Too short: first add unused shots in filmed order, then let clips run longer (up to 1.6x pace).
    unused = [s.index for s in by_index.values() if s.index not in clips]
    while total() < target * 0.9 and unused:
        index = unused.pop(0)
        clips[index] = _clip(by_index[index], pace_seconds)
        lines.setdefault(index, (_short(by_index[index].caption), ""))
        ordered = [hook] + sorted(i for i in clips if i != hook)
    if total() < target * 0.9:
        for index in ordered:
            shot = by_index[index]
            start, end = clips[index]
            room = min(shot.length, pace_seconds * 1.6) - (end - start)
            if room > 0:
                grow = min(room, target - total())
                new_start = max(shot.start_seconds, start - grow / 2)
                clips[index] = (round(new_start, 3), round(min(shot.end_seconds, new_start + (end - start) + grow), 3))
            if total() >= target * 0.9:
                break
    if total() < target * 0.9:
        notes.append(f"영상이 짧아서 목표 {target}초보다 짧게 만들었습니다.")
    return ordered, clips, notes


def shots_to_json(shots: Sequence[Shot]) -> list[dict]:
    return [asdict(shot) for shot in shots]


def shots_from_json(rows: Sequence[dict]) -> list[Shot]:
    return [Shot(**row) for row in rows]


def draft_from_json(data: dict) -> ReelDraft:
    data = dict(data)
    data["scenes"] = tuple(ReelScene(**scene) for scene in data["scenes"])
    data["notes"] = tuple(data.get("notes", ()))
    return ReelDraft(**data)
