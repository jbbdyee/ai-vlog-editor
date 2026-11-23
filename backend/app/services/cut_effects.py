"""TODO 40: effects on each cut of the finished video ("이 컷 확대", "여기 천천히 줌").

Effects live in ``outputs/projects/<id>/cut_effects.json`` next to the chat file (no database change), keyed by the
cut's scene id, so undo, moving cuts and "추천으로 다시 만들기" keep a scene's effect while that scene is used.
The edit-room chat reads effect sentences by rules (no AI), and the project render adds one video filter per cut.

40-1: zoom. ``zoom`` = a fixed 1.35x close-up around the upper middle (where faces usually are),
``push`` = a slow push-in from 1.0x to 1.15x over the cut.
40-2: words on the picture. ``react`` = a big yellow reaction word ("벌렁") that pops out for 1.2 s at the upper right,
``narr`` = a bracketed narration "(근데 갑자기)" low in the middle until the cut ends. Each keeps ``at``, the second
inside the cut where the video was paused ("여기"), and is burned in after the cuts are joined.
40-3: ``sounds`` = "여기 효과음 쿵" (쿵·뿅·휙·띵·띠용·찰칵, made by code in sound_effects), also with ``at``,
mixed in after the words, 8 dB under the speech.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Literal, Mapping, Sequence
from uuid import UUID

from backend.app.services import reel_text, sound_effects

Zoom = Literal["zoom", "push"]
ZOOMS: tuple[str, ...] = ("zoom", "push")
ZOOM_SCALE = 1.35
ZOOM_CENTER_Y = 0.4  # share of the frame height the close-up centres on (faces sit above the middle)
PUSH_END_SCALE = 1.15
ZOOM_LABELS = {"zoom": "확대", "push": "천천히 줌"}

TEXT_KINDS: tuple[str, ...] = ("react", "narr")
TEXT_LABELS = {"react": "리액션 글자", "narr": "괄호 내레이션"}
MAX_TEXTS = 4  # per cut
MAX_TEXT_CHARS = 20
REACT_SECONDS = 1.2
NARR_MIN_SECONDS = 1.0
TEXT_COLOR = "#FFE14A"
REACT_FONT = reel_text.BLACK_HAN
NARR_FONT = reel_text.Font("Pretendard ExtraBold", "Pretendard-ExtraBold.otf", width=0.88)
REACT_X, REACT_Y = 0.76, 0.26  # centre of the reaction word, share of the frame
# The narration's bottom edge, as a share of the height from the bottom. Spoken-line captions sit lower: the
# long-form captions (longform_captions, two lines) reach about 0.18 and the SRT burn-in (hard_subtitles) about 0.2.
NARR_BOTTOM = 0.24
MAX_SOUNDS = 4  # per cut


# --- file ------------------------------------------------------------------------------------------------------------

def _path(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "cut_effects.json"


def load_effects(output_root: Path, project_id: UUID) -> dict[str, dict]:
    """``{candidate_id: {"zoom": "zoom" | "push"}}``; a missing or odd file means no effects."""
    try:
        data = json.loads(_path(output_root, project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cuts = data.get("cuts") if isinstance(data, dict) else None
    if not isinstance(cuts, dict):
        return {}
    out = {}
    for key, value in cuts.items():
        if not isinstance(value, dict):
            continue
        entry: dict = {}
        if value.get("zoom") in ZOOMS:
            entry["zoom"] = value["zoom"]
        items = value.get("texts") if isinstance(value.get("texts"), list) else []
        texts = [item for item in (_clean_text_item(item) for item in items) if item][:MAX_TEXTS]
        if texts:
            entry["texts"] = texts
        items = value.get("sounds") if isinstance(value.get("sounds"), list) else []
        sounds = [item for item in (_clean_sound_item(item) for item in items) if item][:MAX_SOUNDS]
        if sounds:
            entry["sounds"] = sounds
        if entry:
            out[str(key)] = entry
    return out


def _clean_text_item(item: object) -> dict | None:
    if not isinstance(item, dict) or item.get("kind") not in TEXT_KINDS:
        return None
    text = clean_words(str(item.get("text") or ""))
    try:
        at = max(0.0, float(item.get("at") or 0.0))
    except (TypeError, ValueError):
        return None
    return {"kind": item["kind"], "text": text, "at": round(at, 3)} if text else None


def _clean_sound_item(item: object) -> dict | None:
    if not isinstance(item, dict) or item.get("name") not in sound_effects.NAMES:
        return None
    try:
        at = max(0.0, float(item.get("at") or 0.0))
    except (TypeError, ValueError):
        return None
    return {"name": item["name"], "at": round(at, 3)}


def clean_words(text: str) -> str:
    """No ASS control characters, one line, short."""
    return re.sub(r"\s+", " ", re.sub(r"[{}\\]", "", text)).strip()[:MAX_TEXT_CHARS]


def save_effects(output_root: Path, project_id: UUID, effects: Mapping[str, dict]) -> None:
    path = _path(output_root, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = {key: dict(value) for key, value in effects.items() if value}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"cuts": kept}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def set_zoom(effects: Mapping[str, dict], candidate_id: UUID, zoom: str | None) -> dict[str, dict]:
    out = {key: dict(value) for key, value in effects.items()}
    entry = out.setdefault(str(candidate_id), {})
    if zoom is None:
        entry.pop("zoom", None)
    else:
        entry["zoom"] = zoom
    if not entry:
        out.pop(str(candidate_id))
    return out


def texts_of(effects: Mapping[str, dict], candidate_id: UUID) -> list[dict]:
    return list((effects.get(str(candidate_id)) or {}).get("texts") or ())


def set_texts(effects: Mapping[str, dict], candidate_id: UUID, texts: Sequence[dict]) -> dict[str, dict]:
    out = {key: dict(value) for key, value in effects.items()}
    entry = out.setdefault(str(candidate_id), {})
    if texts:
        entry["texts"] = [dict(item) for item in texts][-MAX_TEXTS:]
    else:
        entry.pop("texts", None)
    if not entry:
        out.pop(str(candidate_id))
    return out


def sounds_of(effects: Mapping[str, dict], candidate_id: UUID) -> list[dict]:
    return list((effects.get(str(candidate_id)) or {}).get("sounds") or ())


def set_sounds(effects: Mapping[str, dict], candidate_id: UUID, sounds: Sequence[dict]) -> dict[str, dict]:
    out = {key: dict(value) for key, value in effects.items()}
    entry = out.setdefault(str(candidate_id), {})
    if sounds:
        entry["sounds"] = [dict(item) for item in sounds][-MAX_SOUNDS:]
    else:
        entry.pop("sounds", None)
    if not entry:
        out.pop(str(candidate_id))
    return out


def text_label(item: Mapping) -> str:
    return f"({item['text']})" if item.get("kind") == "narr" else str(item.get("text", ""))


def zoom_of(effects: Mapping[str, dict], candidate_id: UUID) -> str | None:
    return (effects.get(str(candidate_id)) or {}).get("zoom")


def for_cuts(output_root: Path, project_id: UUID, candidate_ids: Sequence[UUID]) -> list[dict | None]:
    effects = load_effects(output_root, project_id)
    return [effects.get(str(candidate_id)) for candidate_id in candidate_ids]


# --- chat sentence ---------------------------------------------------------------------------------------------------

_STAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}\]\s*")
_ZOOM_WORD = re.compile(r"확대|줌|클로즈\s*업|zoom", re.IGNORECASE)
_PUSH_WORD = re.compile(r"천천히|서서히|점점|밀고|푸시|push", re.IGNORECASE)
_OFF_WORD = re.compile(r"빼|삭제|지워|지우|없애|취소|그만|원래\s*대로|말고")


def zoom_request(message: str, here: int | None) -> tuple[int | None, str | None] | Literal[False]:
    """"3번 확대" -> (3, "zoom"), "여기 천천히 줌" -> (here, "push"), "확대 빼" -> (here, None).
    False when the sentence is not about zoom (it goes on to the plan edits)."""
    text = _STAMP.sub("", message).strip()
    if not _ZOOM_WORD.search(text):
        return False
    number = re.search(r"(\d+)\s*번", text)
    target = int(number.group(1)) if number else here
    if _OFF_WORD.search(text):
        return target, None
    return target, "push" if _PUSH_WORD.search(text) else "zoom"


_NARR = re.compile(r"[(（]\s*([^()（）]{1,40}?)\s*[)）]")
_QUOTED = re.compile(r"['‘’\"“”「『]\s*([^'‘’\"“”「」『』]{1,40}?)\s*['‘’\"“”」』]")
_TEXT_VERB = re.compile(r"띄|넣|붙|달아|써|쓰|추가|올려|박아")
_TEXT_WORD = re.compile(r"글자|글씨|리액션|내레이션|나레이션|텍스트")


@dataclass(frozen=True)
class TextRequest:
    number: int | None  # 1-based cut
    at: float  # seconds inside the cut
    kind: str | None  # "react" | "narr"; None when removing = every kind
    words: str | None  # None = remove


def text_request(message: str, here: int | None, offset: float | None) -> TextRequest | Literal[False]:
    """"여기 '벌렁' 띄워" -> react at the paused second, "3번 (근데 갑자기) 넣어" -> narr at the cut start,
    "여기 글자 빼" / "내레이션 지워" -> remove. False when the sentence is not about words on the picture."""
    text = _STAMP.sub("", message).strip()
    number = re.search(r"(\d+)\s*번", text)
    target = int(number.group(1)) if number else here
    at = offset if (offset is not None and target == here) else 0.0
    narr, quoted = _NARR.search(text), _QUOTED.search(text)
    if (narr or quoted) and _TEXT_VERB.search(text):
        kind, words = ("narr", narr.group(1)) if narr else ("react", quoted.group(1))
        words = clean_words(words)
        if words:
            return TextRequest(target, round(at, 3), kind, words)
    word = _TEXT_WORD.search(text)
    if word and _OFF_WORD.search(text):
        kind = "narr" if "레이션" in word.group(0) else "react" if word.group(0) == "리액션" else None
        return TextRequest(target, 0.0, kind, None)
    return False


_SOUND_WORD = re.compile(r"효과음|효과\s*소리|사운드|sfx|소리", re.IGNORECASE)
_SOUND_NAMES = sorted(sound_effects.NAMES, key=len, reverse=True)


@dataclass(frozen=True)
class SoundRequest:
    number: int | None  # 1-based cut
    at: float  # seconds inside the cut
    name: str | None  # None with add=True = which sound is unclear; None with add=False = remove every sound
    add: bool


def sound_request(message: str, here: int | None, offset: float | None) -> SoundRequest | Literal[False]:
    """"여기 효과음 쿵" -> add 쿵 at the paused second, "3번 효과음 띵" -> at the cut start, "효과음 빼" -> remove all,
    "효과음 쿵 빼" -> remove 쿵. False when the sentence is not about a sound effect."""
    text = _STAMP.sub("", message).strip()
    if not _SOUND_WORD.search(text):
        return False
    name = next((item for item in _SOUND_NAMES if item in text), None)
    if name is None and not re.search(r"효과음|효과\s*소리|sfx", text, re.IGNORECASE):
        return False  # "소리 줄여" is about the speech, not an effect
    number = re.search(r"(\d+)\s*번", text)
    target = int(number.group(1)) if number else here
    if _OFF_WORD.search(text):
        return SoundRequest(target, 0.0, name, False)
    at = offset if (offset is not None and target == here) else 0.0
    return SoundRequest(target, round(at, 3), name, True)


# --- render filter ---------------------------------------------------------------------------------------------------

def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def video_filter(effect: Mapping | None, width: int, height: int, fps: int, seconds: float) -> str:
    """Extra filters for one cut, run on the already scaled/padded ``width`` x ``height`` frame (keeps frame count)."""
    zoom = (effect or {}).get("zoom")
    if zoom == "zoom":
        crop_w, crop_h = _even(width / ZOOM_SCALE), _even(height / ZOOM_SCALE)
        x = (width - crop_w) // 2
        y = int(min(max(height * ZOOM_CENTER_Y - crop_h / 2, 0), height - crop_h))
        return f",crop={crop_w}:{crop_h}:{x}:{y},scale={width}:{height}:flags=lanczos,setsar=1"
    if zoom == "push":
        frames = max(1, int(round(seconds * fps)))
        # Worked at twice the size so the slow zoom does not wobble.
        return (f",scale={2 * width}:{2 * height}:flags=lanczos,"
                f"zoompan=z='1+{PUSH_END_SCALE - 1:.2f}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=1:s={width}x{height}:fps={fps},setsar=1")
    return ""


# --- words on the picture --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TextEvent:
    kind: str
    start: float  # seconds on the finished video
    end: float
    text: str


def has_texts(effects: Sequence[Mapping | None] | None) -> bool:
    return any((effect or {}).get("texts") for effect in effects or ())


def text_events(effects: Sequence[Mapping | None], cut_lengths: Sequence[float]) -> list[TextEvent]:
    """Place each cut's words on the finished video: cut start + the paused second, kept inside the cut."""
    events, begin = [], 0.0
    for effect, length in zip(effects, cut_lengths):
        for item in (effect or {}).get("texts") or ():
            at = float(item.get("at") or 0.0)
            if item["kind"] == "react":
                start = min(at, max(0.0, length - 0.4))
                end = min(start + REACT_SECONDS, length)
            else:
                start = min(at, max(0.0, length - NARR_MIN_SECONDS))
                end = length
            if end - start >= 0.2:
                events.append(TextEvent(item["kind"], round(begin + start, 3), round(begin + end, 3),
                                        text_label(item)))
        begin += length
    return events


def has_sounds(effects: Sequence[Mapping | None] | None) -> bool:
    return any((effect or {}).get("sounds") for effect in effects or ())


def sound_events(effects: Sequence[Mapping | None], cut_lengths: Sequence[float]) -> list[sound_effects.SoundEvent]:
    """Each cut's sounds on the finished video: cut start + the paused second (a sound may ring into the next cut)."""
    events, begin = [], 0.0
    for effect, length in zip(effects, cut_lengths):
        for item in (effect or {}).get("sounds") or ():
            at = min(float(item.get("at") or 0.0), max(0.0, length - 0.05))
            events.append(sound_effects.SoundEvent(item["name"], round(begin + at, 3)))
        begin += length
    return events


def _ass_color(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return f"&H00{value[4:6]}{value[2:4]}{value[0:2]}".upper()


# Pop out small, overshoot with a tilt, settle (the creator session's React move).
REACT_MOVE = (r"\fad(40,150)\frz-12\fscx40\fscy40\t(0,110,\fscx118\fscy118\frz8)"
              r"\t(110,200,\fscx100\fscy100\frz-4)\t(200,280,\frz0)")
NARR_MOVE = r"\fad(80,120)\fscx75\fscy75\t(0,120,\fscx106\fscy106)\t(120,200,\fscx100\fscy100)"


def narr_margin(height: int) -> int:
    return round(height * NARR_BOTTOM)


def build_text_ass(events: Sequence[TextEvent], width: int, height: int) -> str:
    react_font, narr_font = reel_text._usable(REACT_FONT), reel_text._usable(NARR_FONT)
    scale = height / 1080
    react_size, narr_size = round(150 * scale), round(52 * scale)
    color = _ass_color(TEXT_COLOR)
    side = round(width * 0.08)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: React,{react_font.family},{react_size},{color},{color},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{max(3, round(10 * scale))},0,5,0,0,0,1
Style: Narr,{narr_font.family},{narr_size},{color},{color},&H00000000,&HA0000000,0,0,0,0,100,100,0,0,1,{max(2, round(4.5 * scale))},{max(1, round(2 * scale))},2,{side},{side},{narr_margin(height)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    x, y = round(width * REACT_X), round(height * REACT_Y)
    lines = []
    for event in events:
        start, end = reel_text.ass_time(event.start), reel_text.ass_time(event.end)
        if event.kind == "react":
            lines.append(f"Dialogue: 2,{start},{end},React,,0,0,0,,{{\\an5\\pos({x},{y}){REACT_MOVE}}}{event.text}")
        else:
            lines.append(f"Dialogue: 1,{start},{end},Narr,,0,0,0,,{{{NARR_MOVE}}}{event.text}")
    return header + "\n".join(lines) + "\n"


class TextBurnError(RuntimeError):
    pass


def burn_texts(video: Path, events: Sequence[TextEvent], width: int, height: int, executable: str = "ffmpeg",
               run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    """Re-encode ``video`` in place with the words on it (audio copied, length unchanged)."""
    video = Path(video)
    with TemporaryDirectory(prefix="cut-texts-", dir=video.parent) as directory:
        stage = Path(directory)
        (stage / "texts.ass").write_text(build_text_ass(events, width, height), encoding="utf-8")
        for font in {reel_text._usable(REACT_FONT), reel_text._usable(NARR_FONT)}:
            path = reel_text._path(font)
            if path:
                shutil.copyfile(path, stage / path.name.lower())
        output = stage / "output.mp4"
        # Relative names in the filter: a Windows drive letter ("C:") breaks FFmpeg's filter syntax.
        command = [executable, "-v", "error", "-nostdin", "-y", "-i", str(video.resolve()),
                   "-vf", "ass=texts.ass:fontsdir=.", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                   "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output.resolve())]
        try:
            result = run(command, cwd=stage, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         check=False)
        except OSError as error:
            raise TextBurnError(str(error)) from error
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise TextBurnError((result.stderr or "")[-800:])
        output.replace(video)
