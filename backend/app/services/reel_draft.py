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

from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
import hashlib
import os
from pathlib import Path
import re
from typing import Callable, Literal, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.services.llm_edit_interpreter import Completion, LLMEditError, configured_engine
from backend.app.services.reel_modes import (ACTIVITIES, ACTIVITY_MODE, AUTO_MODE, HOOK_FORMULAS, MIN_SHOT_SECONDS,
                                             MODE_BY_KEY, MODES, PACES)
from backend.app.services.reel_text import clean_text
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
class TitleOption:
    """TODO 20: one of the AI's title candidates (the draft keeps all of them for the [다른 제목] chips)."""
    lead: str
    title: str
    formula: str = ""


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
    title_lead: str = ""  # TODO 14: small line above the title, its own text box (Blo: "나만 아는 가수의" / "첫 댄스곡 도전기")
    title_options: tuple[TitleOption, ...] = ()  # TODO 20: every title candidate, the one in use first

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


MAX_CAPTION_CHARS = 20  # longer is never used
GOOD_CAPTION_CHARS = 14  # TODO 20: longer is asked to be rewritten once, but kept if the rewrite is long too
_FOREIGN_RE = re.compile(r"[Ͱ-ϿЀ-ӿ぀-ヿ一-鿿]")  # Greek, Cyrillic, kana, Hanzi


def _bad_caption(caption: str, speech: str) -> bool:
    return (_is_counting(caption) or _copies_speech(caption, speech) or len(caption.strip()) > MAX_CAPTION_CHARS
            or bool(_FOREIGN_RE.search(caption)))


def _needs_rewrite(caption: str, speech: str) -> bool:
    return _bad_caption(caption, speech) or len(caption.strip()) > GOOD_CAPTION_CHARS


def _speech_hint(shot: Shot) -> str:
    """What was heard minus the beat counting; nothing when only counting is left."""
    rest = _without_counting(shot.speech)
    return rest if len(rest.replace(" ", "")) >= 2 else ""


class _AIScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot: int
    caption: str = Field(min_length=1, max_length=40)
    label: str = Field(default="", max_length=24)


class _AITitle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formula: str = Field(default="", max_length=10)
    title_lead: str = Field(default="", max_length=30)
    title: str = Field(min_length=1, max_length=40)


class _AITitles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titles: list[_AITitle] = Field(min_length=1, max_length=5)


class _AIReel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    title_lead: str = Field(default="", max_length=30)
    title: str = Field(min_length=1, max_length=40)
    hook_shot: int
    scenes: list[_AIScene] = Field(min_length=1, max_length=MAX_SHOTS)


SYSTEM_PROMPT = (
    "너는 인스타그램 릴스·유튜브 쇼츠 편집자다. 사람이 이미 한 번 컷편집한 영상의 장면 목록을 받는다. "
    "각 장면에는 번호, 길이, 화면 설명(AI가 본 화면), 보이는 옷·물건, 들린 말이 있다. "
    "mode: 지정된 모드가 있으면 그대로, 'auto'면 내용에 가장 맞는 모드 키를 고른다. "
    "첫 화면 제목은 글자 상자 두 개다. title_lead: 위에 작게 띄울 앞말(10자 안팎), title: 그 아래 크게 띄울 핵심(10자 안팎). "
    "둘을 이어 읽으면 한 문장이 되고, 보는 사람이 끝까지 보고 싶게 쓴다. 두 칸에 같은 말을 쓰지 말고 '/'를 쓰지 마라. "
    "화면 설명에 나온 장소·옷·동작을 넣어 이 영상만의 제목으로 쓴다. "
    "hook_shot: 맨 앞에 둘 가장 눈길을 끄는 장면 번호. "
    "scenes: 릴스에 넣을 장면을 고르고 장면마다 caption(화면에 띄울 한국어 한 줄, 14자 이내)을 쓴다. "
    "caption은 자막이 아니라 영상 주인이 화면에 얹는 짧은 한마디다. 친구에게 말하듯 솔직한 구어체로, "
    "광고 문구·설명문처럼 쓰지 말고 마침표·이모지 없이 12자 안팎으로 쓴다. 장면마다 다른 말을 쓴다. 그 장면에서 실제로 보이는 동작·옷·상황을 말한다. "
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
    # The small AI leaves an optional field empty: the lead-in is required in what it is asked for (Python still
    # accepts an answer without one and then splits the title as before).
    schema["properties"]["title_lead"] = {"type": "string", "minLength": 1, "maxLength": 20}
    schema["required"] = sorted(set(schema.get("required", [])) | {"title_lead"})
    schema["properties"]["hook_shot"] = numbers
    schema["$defs"]["_AIScene"]["properties"]["shot"] = numbers
    return schema


def _user_prompt(shots: Sequence[Shot], mode_key: str, pace_seconds: float, target_seconds: int,
                 hide_speech: frozenset[int] = frozenset()) -> str:
    # A known mode: only its own examples (the small AI copied another mode's examples into a dance reel).
    shown = [MODE_BY_KEY[mode_key]] if mode_key in MODE_BY_KEY else MODES
    def title_example(mode) -> str:
        lead, _, title = mode.title_example.partition(" / ")
        return f"title_lead '{lead}' + title '{title}'"
    modes = "\n".join(f"- {m.key}: {m.label} (순서 {m.order}, 제목 틀(○○는 화면 설명의 낱말로, N은 옷·물건 개수로 채울 것): "
                      f"{title_example(m)}, "
                      f"문구 말투: {m.caption_style}"
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


# TODO 14: in a try-on the pieces being shown are the bottoms and dresses; jackets, blouses and knits are worn over
# them or held up next to them (Blo counted 3 items where the screen reader named 5, with a fur jacket and a blouse).
LAYER_KINDS = ("재킷", "자켓", "코트", "블라우스", "셔츠", "니트", "스웨터", "가디건", "카디건", "점퍼", "패딩", "후드", "후디",
               "맨투맨", "조끼", "베스트", "블레이저", "모자", "캡")


def _is_layer(item: str) -> bool:
    return bool(item) and item.split()[-1].endswith(LAYER_KINDS)


def _shown_items(shots: Sequence[Shot]) -> dict[int, str]:
    """Item per shot, leaving out layers when the video also shows other pieces (a jacket haul keeps its jackets)."""
    named = {shot.index: shot.item for shot in shots if shot.item}
    if any(not _is_layer(item) for item in named.values()):
        named = {index: item for index, item in named.items() if not _is_layer(item)}
    return named


def _item_groups(shots: Sequence[Shot]) -> list[tuple[str, int, int]]:
    """Back-to-back shots of the same kind of item, in filmed order: (name, first shot, last shot)."""
    shown = _shown_items(shots)
    shots = [replace(shot, item=shown.get(shot.index, "")) for shot in shots]
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
    complete: Completion | None = None
    if engine is None:
        fallback = "LLM_NOT_CONFIGURED"
    else:
        provider, model, complete = engine
        engine_name = f"llm:{provider}/{model}"
        prompt = _user_prompt(shots, mode_key, pace_seconds, target_seconds)
        ai, fallback = _ask(complete, prompt, len(shots), by_index)
        copied = _copied_lines(ai, by_index, rewrite=True) if ai is not None else []
        if copied:
            # The small AI copies whatever speech it sees, so the rewrite does not show it for those shots.
            retry = _user_prompt(shots, mode_key, pace_seconds, target_seconds, frozenset(copied))
            again, _ = _ask(complete, retry + _rewrite_request(ai, copied), len(shots), by_index)
            if again is not None:
                ai = _merge_lines(ai, again, copied, by_index)
    if ai is None:
        engine_name = "rule"
        complete = None
        mode = MODE_BY_KEY.get(mode_key) or MODE_BY_KEY["daily_vlog"]
        lead, title = "", mode.label
        hook = shots[0].index
        lines = {s.index: (_short(s.caption) or "", "") for s in shots}
    else:
        mode = MODE_BY_KEY[mode_key] if mode_key != AUTO_MODE else MODE_BY_KEY.get(ai.mode, MODE_BY_KEY["daily_vlog"])
        lead, title = _title_parts(ai.title_lead, ai.title)
        hook = ai.hook_shot
        lines = {}
        bad = set(_copied_lines(ai, by_index))
        for scene in ai.scenes:
            if scene.shot in by_index and scene.shot not in lines:
                caption = _line(scene.caption.replace("/", " "))  # emoji: the video fonts have none (TODO 12)
                if scene.shot in bad:  # still copied after one rewrite: no line beats a lifted lyric
                    caption = ""
                lines[scene.shot] = (caption, clean_text(scene.label)[:24] if mode.order == "items" else "")
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
    count = _label_items(ordered, lines, by_index) if mode.order == "items" else 0
    options: list[TitleOption] = []
    if complete is not None:
        _fill_lines(complete, ordered, lines, by_index, mode, hook, bool(title))
        _shorten_lines(complete, ordered, lines, by_index, mode)
        # TODO 20: three more titles from a title-only call; the draft's own title is one of the candidates.
        extra = _ask_titles(complete, [by_index[index] for index in ordered], mode, count)
        options = _pick_title(extra + [TitleOption(lead, title, "모드")], shots, mode.caption_examples, count)
        if count:  # the title promises as many items as there are name tags
            options = [replace(option, lead=_match_count(option.lead, count), title=_match_count(option.title, count))
                       for option in options]
            if (_match_count(lead, count), _match_count(title, count)) != (lead, title):
                notes.append(f"제목의 개수를 이름표 개수({count}가지)에 맞췄습니다.")
        lead, title = options[0].lead, options[0].title
    if mode.order == "items":
        _fill_with_item_kind(ordered, lines, hook, bool(title))
    scenes = tuple(ReelScene(
        index, by_index[index].source_video_id, by_index[index].source_filename, clips[index][0], clips[index][1],
        lines[index][0], lines[index][1], index == hook, by_index[index].caption) for index in ordered)
    total = round(sum(scene.end_seconds - scene.start_seconds for scene in scenes), 3)
    return ReelDraft("short", mode.key, mode.label, pace_key, pace_label, target_seconds, total, title, engine_name,
                     scenes, len(shots), tuple(notes), fallback, title_lead=lead,
                     title_options=tuple(options) if len(options) > 1 else ())


def _candidates(raw: Sequence[TitleOption]) -> list[TitleOption]:
    """Title candidates in the given order, cleaned, empty and repeated ones left out."""
    seen: set[str] = set()
    options = []
    for option in raw:
        lead, title = _title_parts(option.lead, option.title)
        key = _norm(lead + title)
        if title and key not in seen:
            seen.add(key)
            options.append(TitleOption(lead, title, option.formula if option.formula in HOOK_FORMULAS else ""))
    return options


_BLAND_TITLE = re.compile(r"^(오늘의\s*)?(일상|브이로그|하루|기록|연습|시작|춤 연습 시작)$")


def _title_score(option: TitleOption, words: set[str], speech: str = "", examples: Sequence[str] = (),
                 count: int = 0) -> int:
    """TODO 20: words from the screen count most (a title only this video could have), then length, then not bland.

    Lifted speech ("처음 뵙겠습니다", a mis-heard "진흙 호흡") and fragments ("왜 / 한 이유") lose.
    """
    text = f"{option.lead} {option.title}"
    score = 2 if any(word in text for word in words) else 0
    score += 1 if len(option.lead) <= 12 and len(option.title) <= 14 else (-2 if len(option.title) > 18 else 0)
    lead, title = _norm(option.lead), _norm(option.title)
    score -= 2 if _BLAND_TITLE.match(option.title.strip()) or (lead and (lead in title or title in lead)) else 0
    score -= 3 if any(_copies_speech(part, speech) for part in (option.lead, option.title) if part) else 0
    # a caption example lifted into the title ("처음 뵙겠습니다" in a dance reel)
    score -= 3 if any(len(_norm(example)) >= 4 and _norm(example) in _norm(text) for example in examples) else 0
    # words only heard, never seen: mis-heard speech ("호흡, 진흙, 호흡!" became "진흙 호흡의 이유")
    heard = {word for word in re.findall(r"[가-힣]{2,}", speech) if not any(word[:2] in seen for seen in words)}
    score -= 1 if any(word in text for word in heard) else 0
    score -= 2 if len(_norm(option.title)) < 4 else 0
    score -= 1 if option.lead and len(_norm(option.lead)) < 2 else 0
    # Short punch lines read at a glance; screen-description words ("장발의 여성의 비밀") and the base tee worn under a
    # try-on ("흰색 티셔츠는") are not what the video is about; an item reel's title promises its count.
    score += 1 if len(option.title) <= 10 else 0
    score -= 2 if re.search(r"여성|남성|사람", text) else 0
    score -= 2 if any(re.sub(r"[은는이가을를도]$", "", word).endswith(BASE_TOPS) for word in text.split()) else 0
    score += 3 if count and _TITLE_COUNT_RE.search(text) else 0
    return score


_STOP_WORDS = {"있는", "하는", "있다", "여성", "남성", "사람", "모습", "장면", "화면", "앞에서", "함께", "그리고", "명의"}


def _screen_words(shots: Sequence[Shot]) -> set[str]:
    words = set()
    for shot in shots:
        for word in re.findall(r"[가-힣A-Za-z]{2,}", f"{shot.caption} {shot.item}"):
            stem = word[:-1] if len(word) > 2 and word[-1] in "을를이가은는에의도와과로" else word
            if stem not in _STOP_WORDS and len(stem) >= 2:
                words.add(stem)
    return words


def _pick_title(raw: Sequence[TitleOption], shots: Sequence[Shot], examples: Sequence[str] = (),
                count: int = 0) -> list[TitleOption]:
    """The best candidate first, the rest in the given order (ties keep the given order)."""
    options = _candidates(raw)
    words = _screen_words(shots)
    speech = " ".join(_speech_hint(shot) for shot in shots)
    best = max(range(len(options)), key=lambda i: (_title_score(options[i], words, speech, examples, count), -i))
    return [options[best]] + [option for i, option in enumerate(options) if i != best]


def _title_parts(lead: str, title: str) -> tuple[str, str]:
    """Two title boxes; when the AI put the whole sentence in ``title`` too, the repeated lead-in is dropped.

    The small AI sometimes writes both boxes into ``title`` as "앞말 / 제목" (and puts the punch line in the lead
    box): the slash wins.
    """
    if "/" in title:
        head, _, tail = title.partition("/")
        if head.strip() and tail.strip():
            lead, title = head, tail
    lead, title = (clean_text(part.replace("/", " ").replace("○", ""))[:limit] for part, limit in ((lead, 20), (title, 40)))
    if lead and title.startswith(lead):
        rest = title[len(lead):].strip()
        title, lead = (rest, lead) if rest else (title, "")
    return lead, title


_NUM_WORDS = ("한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열")
_TITLE_COUNT_RE = re.compile(r"(?<![가-힣\d])(\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)(\s?)(가지|개|벌|착|템)")


def _match_count(text: str, count: int) -> str:
    """"추천템 5가지" with 3 name tags -> "추천템 3가지" ("세 가지" stays in words)."""
    def fix(match: re.Match) -> str:
        words = not match.group(1).isdigit() and count <= len(_NUM_WORDS)
        return f"{_NUM_WORDS[count - 1] if words else count}{match.group(2)}{match.group(3)}"
    return _TITLE_COUNT_RE.sub(fix, text, count=1)


def _lines_to_fill(ordered: Sequence[int], lines: dict, hook: int, has_title: bool) -> list[int]:
    """Scenes with no line, or the same line as the scene before. The title covers the first scene."""
    missing, previous = [], ""
    for index in ordered:
        caption = lines[index][0]
        if not (index == hook and has_title) and (not caption or _norm(caption) == _norm(previous)):
            missing.append(index)
        previous = caption
    return missing


class _AILine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot: int
    caption: str = Field(min_length=1, max_length=40)


class _AIFill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[_AILine] = Field(min_length=1)


FILL_SYSTEM_PROMPT = (
    "너는 인스타그램 릴스 편집자다. 릴스 장면 순서와 장면마다 화면에 띄운 한 줄 문구를 받는다. "
    "'채울 것'이라고 표시된 장면에만 문구를 새로 쓴다. 친구에게 말하듯 솔직한 구어체로, 마침표·이모지 없이 12자 안팎. "
    "그 장면 화면에 보이는 동작·옷·상황만 말하고, 앞뒤 장면 문구와 다른 말을 쓴다. 숫자 세기는 쓰지 마라. JSON만 출력하라."
)


def _fill_lines(complete: Completion, ordered, lines: dict, by_index: dict, mode, hook: int, has_title: bool) -> None:
    """TODO 14: one more short AI call for scenes left without a line (dropped copies, shots added for length)."""
    missing = _lines_to_fill(ordered, lines, hook, has_title)
    if not missing:
        return
    rows = "\n".join(
        f"[{index}] 화면: {by_index[index].caption or '설명 없음'}"
        + (f" | 옷·물건: {lines[index][1]}" if lines[index][1] else "")
        + (" | 문구: (채울 것)" if index in missing else f" | 문구: {lines[index][0] or '(제목 화면)'}")
        for index in ordered)
    prompt = (f"모드: {mode.label}, 문구 말투: {mode.caption_style}, 말투 참고 예시(그대로 쓰지 말 것): "
              f"{' / '.join(mode.caption_examples)}\n\n릴스 순서:\n{rows}\n\n채울 장면: {', '.join(map(str, missing))}")
    schema = _AIFill.model_json_schema()
    schema["$defs"]["_AILine"]["properties"]["shot"] = {"type": "integer", "enum": list(missing)}
    try:
        answer = _AIFill.model_validate_json(complete(FILL_SYSTEM_PROMPT, prompt, schema))
    except (LLMEditError, ValidationError, ValueError):
        return
    written = {line.shot: _line(line.caption.replace("/", " ")) for line in answer.lines if line.shot in missing}
    for position, index in enumerate(ordered):
        caption = written.get(index, "")
        neighbours = {_norm(lines[ordered[p]][0]) for p in (position - 1, position + 1) if 0 <= p < len(ordered)}
        if caption and not _bad_caption(caption, by_index[index].speech) and _norm(caption) not in neighbours:
            lines[index] = (caption, lines[index][1])


TITLE_SYSTEM_PROMPT = (
    "너는 인스타그램 릴스 제목 작가다. 영상 요약을 보고 첫 화면 제목 후보 3개를 쓴다. "
    "제목은 글자 상자 두 개다. title_lead: 위에 작게 띄울 앞말(10자 이내), title: 아래 크게 띄울 핵심(12자 이내). "
    "둘을 이어 읽으면 한 문장이 되고, 두 칸에 같은 낱말을 되풀이하지 마라. "
    "피드를 넘기던 사람이 손을 멈추게 쓴다. 후보 3개는 서로 다른 공식(formula)으로 쓰고 ○○는 영상 요약의 낱말로 채운다. "
    "밋밋한 요약('춤 연습 시작', '오늘의 일상')은 쓰지 마라. 이모지·마침표·'/' 없이. JSON만 출력하라."
)
TITLE_FORMULAS = tuple(name for name in HOOK_FORMULAS if name != "모드")


def _ask_titles(complete: Completion, shots: Sequence[Shot], mode, count: int) -> list[TitleOption]:
    """TODO 20: a title-only AI call (one job works better for the small AI than titles inside the full draft)."""
    seen: list[str] = []
    for shot in shots:
        if shot.caption and shot.caption not in seen:
            seen.append(shot.caption)
    items = sorted({shot.item for shot in shots if shot.item}) if mode.order == "items" else []
    prompt = (f"영상 종류: {mode.label}\n"
              + (f"보여주는 옷·물건 {count}가지\n" if count else (f"보이는 옷·물건: {', '.join(items)}\n" if items else ""))
              + "화면 요약:\n" + "\n".join(f"- {caption}" for caption in seen[:8])
              + "\n\n제목 공식:\n" + "\n".join(f"- {name}: {HOOK_FORMULAS[name]}" for name in TITLE_FORMULAS))
    schema = _AITitles.model_json_schema()
    title = schema["$defs"]["_AITitle"]
    title["properties"]["formula"] = {"type": "string", "enum": list(TITLE_FORMULAS)}
    title["properties"]["title_lead"] = {"type": "string", "minLength": 1, "maxLength": 20}
    title["required"] = ["formula", "title_lead", "title"]
    schema["properties"]["titles"]["minItems"] = 3
    schema["properties"]["titles"]["maxItems"] = 3
    try:
        answer = _AITitles.model_validate_json(complete(TITLE_SYSTEM_PROMPT, prompt, schema))
    except Exception:  # noqa: BLE001 - extra titles are a bonus; the draft keeps its own title
        return []
    return [TitleOption(t.title_lead, t.title, t.formula) for t in answer.titles]


SHORTEN_SYSTEM_PROMPT = (
    "너는 인스타그램 릴스 편집자다. 화면에 띄울 한 줄 문구가 너무 길다. 뜻과 말투는 살리고 12자 안팎으로 줄여라. "
    "꾸미는 말을 빼고 핵심 낱말만 남긴다. 마침표·이모지·쉼표 없이. JSON만 출력하라."
)


def _shorten_lines(complete: Completion, ordered, lines: dict, by_index: dict, mode) -> None:
    """TODO 20: one small AI call for lines still over 14 characters after the rewrite (a one-job prompt works
    better for the small AI than another full draft). A shortened line is used only when it fits and is usable."""
    long = [index for index in ordered if len(lines[index][0]) > GOOD_CAPTION_CHARS]
    if not long:
        return
    rows = "\n".join(f"[{index}] {lines[index][0]}" for index in long)
    prompt = f"모드: {mode.label}\n줄일 문구:\n{rows}"
    schema = _AIFill.model_json_schema()
    schema["$defs"]["_AILine"]["properties"]["shot"] = {"type": "integer", "enum": list(long)}
    try:
        answer = _AIFill.model_validate_json(complete(SHORTEN_SYSTEM_PROMPT, prompt, schema))
    except (LLMEditError, ValidationError, ValueError):
        return
    for line in answer.lines:
        short = _line(line.caption.replace("/", " "))
        if line.shot in long and short and len(short) <= GOOD_CAPTION_CHARS \
                and not _bad_caption(short, by_index[line.shot].speech):
            lines[line.shot] = (short, lines[line.shot][1])


def _fill_with_item_kind(ordered, lines: dict, hook: int, has_title: bool) -> None:
    """Last resort for hauls, as Blo does: the kind of item ("미니스커트") under its name tag."""
    for index in _lines_to_fill(ordered, lines, hook, has_title):
        label = lines[index][1]
        kind = label.split()[-1] if label else ""
        place = ordered.index(index)
        previous = lines[ordered[place - 1]][0] if place > 0 else ""
        if kind and _norm(kind) != _norm(previous):
            lines[index] = (kind, label)


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


def _copied_lines(ai: _AIReel, by_index: dict, rewrite: bool = False) -> list[int]:
    """Shots whose line is beat counting, copied from what was heard, too long or in a foreign script.

    ``rewrite``: also lines over 14 characters (asked once to be shorter, but still used when the rewrite is long).
    """
    bad = _needs_rewrite if rewrite else _bad_caption
    return [scene.shot for scene in ai.scenes if scene.shot in by_index
            and bad(scene.caption, by_index[scene.shot].speech)]


def _merge_lines(ai: _AIReel, again: _AIReel, asked: Sequence[int], by_index: dict) -> _AIReel:
    """TODO 20: take a rewritten line shot by shot when it is better (usable, and shorter or replacing an unusable one).

    The first answer keeps its titles and its choice of shots: only the lines were asked for again, and on the user's
    samples the rewrite's titles got worse ("왜 / 한 이유") while some of its lines got longer.
    """
    rewritten = {scene.shot: scene.caption for scene in again.scenes}
    scenes = []
    for scene in ai.scenes:
        new = rewritten.get(scene.shot)
        if scene.shot in asked and new and scene.shot in by_index:
            speech = by_index[scene.shot].speech
            if not _bad_caption(new, speech) and (_bad_caption(scene.caption, speech) or len(new) < len(scene.caption)):
                scene = scene.model_copy(update={"caption": new})
        scenes.append(scene)
    return ai.model_copy(update={"scenes": scenes})


def _rewrite_request(ai: _AIReel, copied: Sequence[int]) -> str:
    # Only the shot numbers: showing the copied line again made the small AI write it again.
    numbers = ", ".join(str(index) for index in copied)
    return (f"\n\n다시 써라: 장면 {numbers}의 문구가 너무 길거나(14자 넘음), 들린 말을 옮겼거나, 숫자 세기거나, "
            "한국어가 아닌 글자가 섞였다. 그 장면들은 화면 설명만 보고 모드의 문구 예시 같은 말투로 12자 안팎으로 새로 써라. "
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


def _label_items(ordered: list[int], lines: dict, by_index: dict) -> int:
    """Haul/review: shots of the same item share one name tag; each new item opens with "첫 번째", "두 번째" ...

    Done here, not by the AI, so the numbering is always right. Returns how many items got a number.
    TODO 14: names come from the screen reader (layers left out); the AI's labels only when it named nothing.
    The hook shot (under the title) gets a name tag only when it shows one of the numbered items, so the screen
    never shows more item names than the title counts.
    """
    hook, rest = ordered[0], ordered[1:]
    shown = _shown_items([by_index[index] for index in ordered])
    if not shown:
        shown = {index: lines[index][1] for index in ordered if lines[index][1]}
    group: str | None = None
    groups: list[str] = []
    for index in rest:
        own = shown.get(index, "")
        earlier = next((name for name in groups if own and _same_item(own, name)), None)
        if earlier is not None:  # back to an item already numbered: same tag, no new number
            group = earlier
            lines[index] = (lines[index][0], group)
        elif own:
            group = own
            groups.append(group)
            count = len(groups)
            lines[index] = (ORDINALS[count - 1] if count <= len(ORDINALS) else f"{count}번째", group)
        else:
            lines[index] = (lines[index][0], group or "")
    own = shown.get(hook, "")
    tag = next((name for name in groups if own and _same_item(own, name)), "")
    lines[hook] = (lines[hook][0], tag)
    return len(groups)


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


PREVIOUS_KEY = "previous_draft"  # TODO 16: the draft before the last chat edit (older saves only)
HISTORY_KEY = "edit_history"  # TODO 18: the drafts before the last chat edits, newest first, for "되돌리기" many times


def draft_from_json(data: dict) -> ReelDraft:
    data = dict(data)
    data.pop(PREVIOUS_KEY, None)
    data.pop(HISTORY_KEY, None)
    data["scenes"] = tuple(ReelScene(**scene) for scene in data["scenes"])
    data["notes"] = tuple(data.get("notes", ()))
    data["title_options"] = tuple(TitleOption(**option) for option in data.get("title_options", ()))
    return ReelDraft(**data)


def _line(text: str) -> str:
    """On-screen line: no emoji (the video fonts have none) and no full stop at the end (the prompt asks for none)."""
    return clean_text(text)[:40].rstrip(".。").strip()
