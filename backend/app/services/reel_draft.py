"""TODO 10: short-form reel draft from already-cut videos (like the user's Blo workflow).

Steps (Python owns every timestamp; the AI only picks shots and writes words):
1. ``analyze_shots``: split each source into shots (FFmpeg scene-change detection), cut very long shots into
   pieces, describe each shot with the local VLM and attach the speech heard in it.
2. ``build_draft``: the LLM picks a mode (when "auto"), a hook title, the hook shot, which shots to use and a short
   line per shot. Python then orders the shots by the mode's rule and sets each clip length from the chosen pace,
   never cutting a spoken line short, and fits the total to the target length.
Any AI failure falls back to a rule-only draft so the user always gets something to look at.

TODO 11 (caption quality): the screen-reading AI also names the clothing/item on screen and what the shot is doing.
"auto" mode is a vote over those answers, counting ("1, 2, 3, 4") is dropped from the speech, a line that just copies
what was heard is rewritten once, and item modes get their name tags and "첫 번째" from Python, not from the AI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import hashlib
import os
from pathlib import Path
import re
from typing import Callable, Literal, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.services.llm_edit_interpreter import Completion, LLMEditError, configured_engine
from backend.app.services.reel_modes import (ACTIVITIES, ACTIVITY_MODE, AUTO_MODE, MIN_SHOT_SECONDS, MODE_BY_KEY, MODES,
                                             PACES)
from backend.app.services.shot_structure import ShotDetectionConfig, ShotStructureError, detect_shot_structure
from backend.app.services.vlm_scene_captioner import VLMCaptionError, ask_frames, vlm_model

ANALYSIS_VERSION = "reel-shots-v2"  # v2: reel-only screen question (item + activity)
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
    item: str = ""  # clothing/item on screen, "colour + kind" (TODO 11)
    activity: str = ""  # one of reel_modes.ACTIVITIES

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


class ShotLook(BaseModel):
    """What the screen-reading AI answers for one reel shot (TODO 11)."""
    model_config = ConfigDict(extra="forbid")
    caption: str = Field(default="", max_length=120)
    item: str = Field(default="", max_length=40)
    activity: Literal[ACTIVITIES] = "기타"  # type: ignore[valid-type]


LOOK_PROMPT = (
    "이 이미지들은 숏폼 영상 한 장면의 프레임 3장(시간 순서)이다. 화면에 실제로 보이는 것만 근거로 답하라. "
    "대사나 노래 가사는 쓰지 마라. "
    "caption: 장면을 설명하는 한국어 한 문장(40자 이내). 사람이 무엇을 입고 무엇을 하는지 구체적으로. "
    "item: 사람이 입어 보이거나 들어 보이는 옷·물건 이름을 '색 + 종류'로 짧게 쓴다 "
    "(예: 브라운 미니스커트, 플라워 롱원피스, 빈티지 롱스커트, 화이트 반팔티, 실버 텀블러). "
    "옷이면 가장 눈에 띄는 한 벌만. 한국어로만 쓴다. 특별히 보여주는 옷·물건이 없으면 빈 문자열. "
    "activity: 이 장면에서 하는 일 하나. 옷을 입고 거울 앞에서 포즈·셀카를 찍거나 옷을 들어 보이면 '옷 보여주기', "
    "물건을 들고 보여주면 '물건 보여주기', 연습실·무대에서 동작을 하거나 여러 명이 같은 동작·포즈를 하면 '춤', "
    "운동하면 '운동', 음식을 만들면 '요리', "
    "먹거나 마시면 '먹기·마시기', 걷거나 차를 타거나 경치를 보여주면 '이동·풍경', 카메라를 보고 말하거나 인사하면 "
    "'이야기·셀카', 아무것도 아니면 '기타'. JSON만 출력하라."
)

Detect = Callable[..., object]
Describe = Callable[[Path, float, float], "ShotLook | str"]


def reel_vlm_model() -> str:
    """Reels may use a bigger screen reader than scene search (TODO 11: qwen2.5vl:7b names clothes far better)."""
    return os.environ.get("CUTORY_REEL_VLM_MODEL") or vlm_model()


def analysis_fingerprint(sources: Sequence[SourceInput]) -> str:
    """Same videos + same detector/VLM = reuse the shots (changing mode or pace then skips the slow part)."""
    parts = [ANALYSIS_VERSION, reel_vlm_model()] + [f"{s.source_video_id}:{s.duration_seconds:.3f}:{s.path.name}" for s in sources]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _vlm_describe(path: Path, start: float, end: float) -> ShotLook:
    try:
        return ask_frames(path, start, end, LOOK_PROMPT, ShotLook, model=reel_vlm_model())[0]
    except VLMCaptionError:
        return ShotLook()


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
        look = describe(source.path, start, end)
        look = look if isinstance(look, ShotLook) else ShotLook(caption=str(look)[:120])
        shots.append(Shot(
            number, str(source.source_video_id), source.filename, start, end, look.caption.strip()[:80],
            " ".join(str(seg["text"]).strip() for seg in speech)[:120],
            max(start, min(float(seg["start_seconds"]) for seg in speech)) if speech else None,
            min(end, max(float(seg["end_seconds"]) for seg in speech)) if speech else None,
            _one_item(look.item), look.activity))
    if on_progress:
        on_progress(len(pieces), len(pieces))
    return shots


BASE_TOPS = ("반팔티", "티셔츠", "반팔", "티")  # worn under everything in a try-on, never the item being shown


def _one_item(text: str) -> str:
    """The small AI often lists the base tee too ("흰색 반팔티, 짙은 갈색 미니스커트"): skip plain tops, keep the first."""
    parts = [part.strip() for part in re.split(r"[,/]| 와 | 과 ", text) if part.strip()]
    shown = [part for part in parts if not part.split()[-1].endswith(BASE_TOPS)]
    return shown[0][:24] if shown else ""  # only the base tee on screen: nothing new is being shown


def _real_speech(segment: dict) -> bool:
    text = str(segment.get("text", "")).strip()
    return bool(text) and not any(phrase in text for phrase in HALLUCINATED_PHRASES)


_COUNT_WORDS = ("하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열|원|투|쓰리|포|파이브|식스|세븐|에잇|앤|"
                "one|two|three|four|five|six|seven|eight|and")
_COUNT_RE = re.compile(rf"(?<![가-힣A-Za-z])(?:{_COUNT_WORDS})(?![가-힣A-Za-z])", re.IGNORECASE)


def _without_counting(text: str) -> str:
    """Dance teachers count beats ("1, 2, 3, 4", "파이브 식스") - that is never a caption."""
    text = _COUNT_RE.sub(" ", re.sub(r"[0-9]+", " ", text))
    return re.sub(r"[^\w]+", " ", text).strip()


_COUNT_RUN_RE = re.compile(r"\d\D{0,3}\d\D{0,3}\d")  # "1, 2, 3" inside a longer line


def _is_counting(text: str) -> bool:
    return bool(text.strip()) and (len(_without_counting(text).replace(" ", "")) < 2 or bool(_COUNT_RUN_RE.search(text)))


def _norm(text: str) -> str:
    return re.sub(r"[^\w]", "", text).lower()


def _copies_speech(caption: str, speech: str) -> bool:
    """True when the on-screen line is mostly words lifted from what was heard (lyrics, mis-heard speech)."""
    line, heard = _norm(caption), _norm(speech)
    if len(line) < 3 or not heard:
        return False
    if line in heard:
        return True
    match = SequenceMatcher(None, line, heard).find_longest_match(0, len(line), 0, len(heard))
    # Mostly copied, or one heard phrase of 4+ letters pasted into a longer line ("잘하셨습니다! 실력이 느는 중")
    return match.size >= 4 or (match.size >= 3 and match.size / len(line) >= 0.5)


MAX_CAPTION_CHARS = 20
_FOREIGN_RE = re.compile(r"[Ͱ-ϿЀ-ӿ぀-ヿ一-鿿]")  # Greek, Cyrillic, kana, Hanzi


def _bad_caption(caption: str, speech: str) -> bool:
    return (_is_counting(caption) or _copies_speech(caption, speech) or len(caption.strip()) > MAX_CAPTION_CHARS
            or bool(_FOREIGN_RE.search(caption)))


def _speech_hint(shot: Shot) -> str:
    """What was heard minus the beat counting; nothing when only counting is left."""
    rest = _without_counting(shot.speech)
    return rest if len(rest.replace(" ", "")) >= 2 else ""


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
    "각 장면에는 번호, 길이, 화면 설명(AI가 본 화면), 보이는 옷·물건, 들린 말이 있다. "
    "mode: 지정된 모드가 있으면 그대로, 'auto'면 내용에 가장 맞는 모드 키를 고른다. "
    "title: 첫 화면에 크게 띄울 짧은 제목(20자 이내). 보는 사람이 끝까지 보고 싶게 쓴다. "
    "hook_shot: 맨 앞에 둘 가장 눈길을 끄는 장면 번호. "
    "scenes: 릴스에 넣을 장면을 고르고 장면마다 caption(화면에 띄울 한국어 한 줄, 18자 이내)을 쓴다. "
    "caption은 자막이 아니라 영상 주인이 화면에 얹는 짧은 한마디다. 친구에게 말하듯 솔직한 구어체로, "
    "광고 문구·설명문처럼 쓰지 말고 마침표 없이 12자 안팎으로 쓴다. 그 장면에서 실제로 보이는 동작·옷·상황을 말한다. "
    "나쁜 예(설명문): '두 명의 여성이 춤추며 호흡', '거울 앞에서 셀카를 찍는 여성' → "
    "좋은 예(구어체): '선생님 따라 하는 중', '거울샷 남겨주고'. "
    "들린 말은 상황을 이해하는 참고일 뿐이다. 들린 말을 그대로 옮겨 적지 마라. 숫자 세기와 노래 가사는 무시하라. "
    "화면에 없는 내용을 지어내지 마라. "
    "모드 순서가 items면 장면마다 label에 그 장면의 옷·물건 이름(보이는 옷·물건을 참고, 12자 이내)을 쓰고 "
    "같은 옷·물건이면 같은 이름을 쓴다. items가 아니면 label은 빈 문자열로 둔다. "
    "목표 길이를 채울 만큼 장면을 고르되 비슷한 장면이 연달아 나오면 하나만 고른다. 목록에 있는 번호만 쓴다. JSON만 출력하라."
)


def _schema(shot_count: int) -> dict:
    schema = _AIReel.model_json_schema()
    numbers = {"type": "integer", "enum": list(range(1, shot_count + 1))}
    schema["properties"]["mode"] = {"type": "string", "enum": [m.key for m in MODES]}
    schema["properties"]["hook_shot"] = numbers
    schema["$defs"]["_AIScene"]["properties"]["shot"] = numbers
    return schema


def _user_prompt(shots: Sequence[Shot], mode_key: str, pace_seconds: float, target_seconds: int,
                 hide_speech: frozenset[int] = frozenset()) -> str:
    # A known mode: only its own examples (the small AI copied another mode's examples into a dance reel).
    shown = [MODE_BY_KEY[mode_key]] if mode_key in MODE_BY_KEY else MODES
    modes = "\n".join(f"- {m.key}: {m.label} (순서 {m.order}, 제목 예: {m.title_example}, 문구 말투: {m.caption_style}"
                      + (f", 말투 참고 예시(그대로 쓰지 말 것): {' / '.join(m.caption_examples)})" if len(shown) == 1 else ")")
                      for m in shown)
    rows = "\n".join(
        f"[{s.index}] {s.length:.1f}초 | 화면: {s.caption or '설명 없음'}" + (f" | 옷·물건: {s.item}" if s.item else "")
        + (f" | 들린 말(참고만): {_speech_hint(s)}" if _speech_hint(s) and s.index not in hide_speech else "")
        for s in shots)
    wanted = max(1, round(target_seconds / pace_seconds))
    items = ""
    if mode_key in MODE_BY_KEY and MODE_BY_KEY[mode_key].order == "items":
        groups = _item_groups(shots)
        if groups:
            items = (f"\n보여주는 옷·물건 {len(groups)}가지(촬영 순서): "
                     + ", ".join(f"{name}(장면 {first}~{last})" for name, first, last in groups)
                     + "\n제목에 개수를 쓰면 이 개수를 쓴다.")
    # Few shots for the length: every shot ends up in the reel anyway, so every shot needs its own line.
    every = (f"\n장면이 {len(shots)}개뿐이라 목록의 모든 장면을 빠짐없이 scenes에 넣고 장면마다 caption을 쓴다."
             if len(shots) <= wanted * 1.5 else "")
    return (f"모드 목록:\n{modes}\n\n지정된 모드: {mode_key}\n목표 길이: {target_seconds}초, 장면 하나당 약 {pace_seconds}초 "
            f"→ 약 {wanted}개 장면{items}{every}\n\n장면 목록(촬영 순서):\n{rows}")


def _item_groups(shots: Sequence[Shot]) -> list[tuple[str, int, int]]:
    """Back-to-back shots of the same kind of item, in filmed order: (name, first shot, last shot)."""
    groups: list[list] = []
    for shot in shots:
        if not shot.item:
            if groups:
                groups[-1][2] = shot.index
            continue
        if groups and _same_item(shot.item, groups[-1][0]):
            groups[-1][2] = shot.index
        else:
            groups.append([shot.item, shot.index, shot.index])
    return [tuple(group) for group in groups]


def build_draft(shots: Sequence[Shot], *, mode_key: str, pace_key: str, target_seconds: int,
                engine: tuple[str, str, Completion] | None | object = ...) -> ReelDraft:
    if not shots:
        raise ValueError("no shots")
    if mode_key != AUTO_MODE and mode_key not in MODE_BY_KEY:
        raise ValueError("unknown mode")
    pace_label, pace_seconds = PACES[pace_key]
    engine = configured_engine() if engine is ... else engine
    by_index = {s.index: s for s in shots}
    notes: list[str] = []
    if mode_key == AUTO_MODE:
        voted, vote_note = _vote_mode(shots)
        if voted:
            mode_key = voted
            notes.append(vote_note)
    ai: _AIReel | None = None
    fallback: str | None = None
    engine_name = "rule"
    if engine is None:
        fallback = "LLM_NOT_CONFIGURED"
    else:
        provider, model, complete = engine
        engine_name = f"llm:{provider}/{model}"
        prompt = _user_prompt(shots, mode_key, pace_seconds, target_seconds)
        ai, fallback = _ask(complete, prompt, len(shots), by_index)
        copied = _copied_lines(ai, by_index) if ai is not None else []
        if copied:
            # The small AI copies whatever speech it sees, so the rewrite does not show it for those shots.
            retry = _user_prompt(shots, mode_key, pace_seconds, target_seconds, frozenset(copied))
            again, _ = _ask(complete, retry + _rewrite_request(ai, copied), len(shots), by_index)
            if again is not None and len(_copied_lines(again, by_index)) < len(copied):
                ai = again
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
        bad = set(_copied_lines(ai, by_index))
        for scene in ai.scenes:
            if scene.shot in by_index and scene.shot not in lines:
                caption = scene.caption.strip()[:40]
                if scene.shot in bad:  # still copied after one rewrite: no line beats a lifted lyric
                    caption = ""
                lines[scene.shot] = (caption, scene.label.strip()[:24] if mode.order == "items" else "")
        if hook not in lines:
            lines[hook] = ("", "")
    written = set(lines) if ai is not None else None
    ordered = [hook] + sorted(index for index in lines if index != hook)
    clips = {index: _clip(by_index[index], pace_seconds) for index in ordered}
    ordered, clips, fit_notes = _fit(ordered, clips, by_index, lines, hook, target_seconds, pace_seconds)
    notes += fit_notes
    if written is not None:  # shots added only to reach the length: a cut-off screen description reads badly
        for index in ordered:
            if index not in written:
                lines[index] = ("", lines[index][1])
    if mode.order == "items":
        _label_items(ordered, lines, by_index)
    scenes = tuple(ReelScene(
        index, by_index[index].source_video_id, by_index[index].source_filename, clips[index][0], clips[index][1],
        lines[index][0], lines[index][1], index == hook, by_index[index].caption) for index in ordered)
    total = round(sum(scene.end_seconds - scene.start_seconds for scene in scenes), 3)
    return ReelDraft("short", mode.key, mode.label, pace_key, pace_label, target_seconds, total, title, engine_name,
                     scenes, len(shots), tuple(notes), fallback)


def _ask(complete: Completion, prompt: str, shot_count: int, by_index: dict) -> tuple[_AIReel | None, str | None]:
    try:
        ai = _AIReel.model_validate_json(complete(SYSTEM_PROMPT, prompt, _schema(shot_count)))
    except LLMEditError as error:
        return None, error.code
    except (ValidationError, ValueError):
        return None, "LLM_SCHEMA_INVALID"
    if ai.hook_shot not in by_index or not any(scene.shot in by_index for scene in ai.scenes):
        return None, "LLM_SCENES_INVALID"
    return ai, None


def _copied_lines(ai: _AIReel, by_index: dict) -> list[int]:
    """Shots whose line is beat counting, copied from what was heard, too long or in a foreign script."""
    return [scene.shot for scene in ai.scenes if scene.shot in by_index
            and _bad_caption(scene.caption, by_index[scene.shot].speech)]


def _rewrite_request(ai: _AIReel, copied: Sequence[int]) -> str:
    # Only the shot numbers: showing the copied line again made the small AI write it again.
    numbers = ", ".join(str(index) for index in copied)
    return (f"\n\n다시 써라: 장면 {numbers}의 문구가 들린 말을 옮겼거나, 숫자 세기거나, 20자를 넘거나, "
            "한국어가 아닌 글자가 섞였다. 그 장면들은 화면 설명만 보고 모드의 문구 예시 같은 말투로 새로 써라. "
            "나머지 장면은 그대로 둬도 된다. 전체 JSON을 다시 출력하라.")


def _vote_mode(shots: Sequence[Shot]) -> tuple[str | None, str]:
    """"auto": the mode most shots are doing, when at least a third of the shots agree."""
    counts: dict[str, int] = {}
    for shot in shots:
        activity = shot.activity
        if activity in ("", "기타") and _COUNT_RUN_RE.search(shot.speech):
            activity = "춤"  # a teacher counting beats ("1 2 3 4 5") while the frames only show a pose
        mode = ACTIVITY_MODE.get(activity)
        if mode:
            counts[mode] = counts.get(mode, 0) + 1
    if not counts:
        return None, ""
    mode, count = max(counts.items(), key=lambda pair: pair[1])
    if count * 3 < len(shots):
        return None, ""
    activity = next(name for name, key in ACTIVITY_MODE.items() if key == mode)
    return mode, f"자동: 장면 {len(shots)}개 중 {count}개가 '{activity}' 장면이라 '{MODE_BY_KEY[mode].label}' 모드로 골랐습니다."


ORDINALS = ("첫 번째", "두 번째", "세 번째", "네 번째", "다섯 번째", "여섯 번째", "일곱 번째", "여덟 번째", "아홉 번째", "열 번째")


def _same_item(a: str, b: str) -> bool:
    """Back-to-back shots of the same kind of clothing are one item: the small AI names the colour differently
    from shot to shot ("짙은 갈색 미니스커트", "마른 가을색 미니스커트")."""
    ka, kb = a.split()[-1], b.split()[-1]
    return ka.endswith(kb) or kb.endswith(ka)


def _label_items(ordered: list[int], lines: dict, by_index: dict) -> None:
    """Haul/review: shots of the same item share one name tag; each new item opens with "첫 번째", "두 번째" ...

    Done here, not by the AI, so the numbering is always right. The hook shot only gets its name tag.
    """
    hook, rest = ordered[0], ordered[1:]
    name = lambda index: by_index[index].item or lines[index][1]  # noqa: E731  (what this shot shows first)
    if name(hook):
        lines[hook] = (lines[hook][0], name(hook))
    group: str | None = None
    count = 0
    for index in rest:
        own = name(index)
        if own and (group is None or not _same_item(own, group)):
            group, count = own, count + 1
            lines[index] = (ORDINALS[count - 1] if count <= len(ORDINALS) else f"{count}번째", group)
        elif group is not None:
            lines[index] = (lines[index][0], group)


def _short(text: str) -> str:
    """At most 18 characters, cut at a space so a word is never chopped in half."""
    text = text.strip()
    if len(text) <= 18:
        return text
    cut = text[:18]
    return cut[:cut.rfind(" ")] if " " in cut else cut


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
