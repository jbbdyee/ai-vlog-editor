"""TODO 33-2: how often the subtitles of a video I like change, how long they are, and where they sit.

Frames are taken every 0.5s (1s for long videos) and read with Windows' built-in OCR (``windows_ocr.ps1``; local, free,
no AI). Screen recordings of reels carry app text (likes, comment box, the post's description), so text that stays put
for much of the video, the top/bottom app bands, small text (app screens shown inside the reel) and garbled reads are
dropped. Similar text in the same zone on following frames is one subtitle; a new subtitle is a change.
Decorated letters are often misread, so the character count is approximate.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
from typing import Sequence

SCRIPT = Path(__file__).with_name("windows_ocr.ps1")
LONG_VIDEO = 180.0  # longer than this: one frame a second instead of two
MIN_HEIGHT = 0.032  # text lower than this share of the frame is app/screen text, not a subtitle
SAME = 0.5  # text similarity that still counts as the same subtitle
STATIC = 0.6  # text at the same place in this share of frames is the app around a screen recording
LONG_TRACK = 0.6  # a "subtitle" on screen this share of the video is a watermark or app text
APP_BANDS = (0.1, 0.74)  # in a screen recording only this vertical band can hold subtitles
EDGE_BANDS = (0.03, 0.97)
ZONES = ("위", "가운데", "아래")
_HANGUL = re.compile(r"[가-힣]")


class CaptionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def step_for(duration: float) -> float:
    return 0.5 if duration <= LONG_VIDEO else 1.0


def zone(y: float) -> str:
    return ZONES[0] if y < 1 / 3 else (ZONES[1] if y < 2 / 3 else ZONES[2])


def hangul_only(text: str) -> str | None:
    """'(이 자막은 제가 넣은 거)' -> '이자막은제가넣은거'; mostly non-Korean (garbled) reads -> None."""
    body = re.sub(r"\s", "", text)
    letters = "".join(_HANGUL.findall(text))
    if len(letters) < 2 or len(letters) / max(1, len(body)) < 0.7:
        return None
    return letters


def frames_from_ocr(raw: Sequence[dict]) -> list[list[tuple[str, float, float]]]:
    """OCR json -> per frame [(text, top share, height share)]."""
    frames = []
    for item in raw:
        height = float(item.get("height") or 0) or 1.0
        lines = []
        for line in item.get("lines") or []:
            if isinstance(line, dict) and line.get("text"):
                lines.append((str(line["text"]), float(line.get("y") or 0) / height, float(line.get("h") or 0) / height))
        frames.append(lines)
    return frames


def app_text(frames: Sequence[Sequence[tuple[str, float, float]]]) -> set[tuple[str, float]]:
    """Text that sits at the same place in many frames (reels app around a screen recording)."""
    seen = Counter()
    for lines in frames:
        seen.update({(text, round(y, 2)) for text, y, _ in lines})
    return {key for key, count in seen.items() if count >= STATIC * len(frames)} if frames else set()


def tracks(frames: Sequence[Sequence[tuple[str, float, float]]], step: float) -> list[dict]:
    """Follow each subtitle over frames: [{start, end, zone, text}] (end = last frame it was seen)."""
    static = app_text(frames)
    low, high = APP_BANDS if static else EDGE_BANDS
    found: list[dict] = []
    open_: list[dict] = []
    for index, lines in enumerate(frames):
        at = round(index * step, 2)
        still: list[dict] = []
        for text, y, h in lines:
            if (text, round(y, 2)) in static or not low < y < high or h < MIN_HEIGHT:
                continue
            letters = hangul_only(text)
            if not letters:
                continue
            where = zone(y)
            match = next((track for track in open_ if track["zone"] == where
                          and SequenceMatcher(None, track["text"], letters).ratio() >= SAME), None)
            if match is None:
                match = {"start": at, "end": at, "zone": where, "text": letters}
                found.append(match)
            else:
                match["end"] = at
                if len(letters) > len(match["text"]):
                    match["text"] = letters
            if match not in still:
                still.append(match)
        # one missed frame (OCR blinks) does not end a subtitle
        still += [track for track in open_ if track not in still and at - track["end"] <= step]
        open_ = still
    total = len(frames) * step
    return [track for track in found if track["end"] - track["start"] < LONG_TRACK * total]


def caption_stats(found: Sequence[dict], duration: float, step: float) -> dict:
    if not found:
        return {"caption_count": 0, "change_count": 0, "median_gap": 0.0, "median_chars": 0.0,
                "on_screen_share": 0.0, "zone_share": {name: 0.0 for name in ZONES}}
    starts = sorted({track["start"] for track in found})
    gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
    shown = set()
    for track in found:
        shown.update(range(round(track["start"] / step), round(track["end"] / step) + 1))
    zones = Counter(track["zone"] for track in found)
    return {
        "caption_count": len(found),
        "change_count": len(starts),
        "median_gap": round(statistics.median(gaps), 2) if gaps else 0.0,
        "median_chars": round(statistics.median(len(track["text"]) for track in found), 1),
        "on_screen_share": round(min(1.0, len(shown) * step / duration), 3) if duration > 0 else 0.0,
        "zone_share": {name: round(zones[name] / len(found), 3) for name in ZONES},
    }


def _half(value: float) -> str:
    return f"{max(0.5, round(value * 2) / 2):g}"


def caption_candidates(numbers: dict) -> list[dict]:
    if numbers.get("caption_count", 0) < 3:
        return []
    out = []
    if numbers["median_gap"] > 0:
        out.append({"key": "caption_interval", "text": f"자막은 {_half(numbers['median_gap'])}초쯤마다 바꾸기",
                    "why": f"자막이 바뀌는 간격 가운데 값 {numbers['median_gap']:.1f}초"})
    out.append({"key": "caption_chars", "text": f"자막 한 번에 {max(1, round(numbers['median_chars']))}글자 안팎",
                "why": f"자막 글자 수 가운데 값 {numbers['median_chars']:g}자 (대략)"})
    where, share = max(numbers["zone_share"].items(), key=lambda item: item[1])
    if share >= 0.5:
        out.append({"key": "caption_position", "text": f"자막은 화면 {where}에",
                    "why": f"자막 {round(share * 100)}%가 {where}"})
    return out


def sample_frames(path: Path, where: Path, step: float, ffmpeg: str | None = None) -> None:
    command = [ffmpeg or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-v", "error",
               "-i", str(path), "-map", "0:v:0", "-an", "-vf", f"fps={1 / step:g},scale=720:-2", str(where / "f%05d.png")]
    try:
        done = subprocess.run(command, capture_output=True, timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise CaptionError("FRAMES_FAILED") from error
    if done.returncode != 0 or not any(where.glob("*.png")):
        raise CaptionError("FRAMES_FAILED")


def read_text(where: Path) -> list[dict]:
    shell = shutil.which("powershell") or shutil.which("powershell.exe")
    if shell is None or not SCRIPT.exists():
        raise CaptionError("OCR_UNAVAILABLE")
    out = where / "ocr.json"
    command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-Dir", str(where), "-Out", str(out)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=1800, check=False)
        raw = json.loads(out.read_text(encoding="utf-8-sig")) if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise CaptionError("OCR_FAILED") from error
    if not isinstance(raw, list):
        raise CaptionError("OCR_FAILED")
    return raw


def measure(path: Path, duration: float, *, ffmpeg: str | None = None) -> dict:
    step = step_for(duration)
    where = Path(tempfile.mkdtemp(prefix="cutory-captions-"))
    try:
        sample_frames(path, where, step, ffmpeg)
        found = tracks(frames_from_ocr(read_text(where)), step)
    finally:
        shutil.rmtree(where, ignore_errors=True)
    numbers = caption_stats(found, duration, step)
    return {"step": step, "stats": numbers, "captions": found[:300], "candidates": caption_candidates(numbers)}
