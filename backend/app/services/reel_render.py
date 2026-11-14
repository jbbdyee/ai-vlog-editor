"""TODO 12: turn a saved reel draft into a vertical (9:16) MP4 with the title, name tags and lines burned in.

Steps (all local FFmpeg, no AI):
1. cut every scene from its source and fit it into a 1080x1920 frame. A portrait shot fills it; a wide shot keeps its
   whole picture and sits a little high (top edge at y=520, TODO 17) so the title fits in the black band above and
   the name tag and line in the band below. A wide shot saved inside a portrait file with black bars is found with
   cropdetect and treated the same (only the bars are cut off). Each piece is snapped to whole frames and gets audio
   of exactly the same length (silence when the source has none), so joining many pieces never drifts (TODO 9).
2. join the pieces without re-encoding.
3. write an ASS subtitle file in the chosen text template (``reel_text``: typeface, colour, place, size) and burn it
   in. Emoji are dropped because the fonts have none (they would show as empty boxes).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from backend.app.services.media_probe import MediaInfo, MediaProbeError, probe_media
from backend.app.services.reel_draft import ReelDraft
from backend.app.services.reel_text import (DEFAULT_FONT, FPS, HEIGHT, WIDTH, TextStyle, WideFrame, build_ass,  # noqa: F401
                                            clean_text, font_files, frames, normalize, reel_font, wide_frame)

AUDIO_RATE = 48000
VIDEO_NAME = "reel.mp4"
INFO_NAME = "reel.json"

Progress = Callable[[str, int, int], None]


class ReelRenderError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class ReelVideo:
    path: Path
    duration_seconds: float
    file_size_bytes: int
    draft_fingerprint: str
    scene_count: int
    text_style: TextStyle = TextStyle()


def draft_fingerprint(draft: ReelDraft) -> str:
    """Changes whenever the draft changes, so the screen can tell an old video from the current draft."""
    return hashlib.sha256(json.dumps(draft.to_json(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _frames(seconds: float) -> int:
    return frames(seconds)


def _run(command: list[str], cwd: Path, code: str) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReelRenderError(code, str(error)) from error
    if result.returncode != 0:
        raise ReelRenderError(code, result.stderr.strip()[-800:])


@dataclass(frozen=True)
class _Shape:
    """How one source goes into the reel frame: an optional crop to its real picture, then its place."""
    crop: str = ""  # FFmpeg crop=w:h:x:y, when black bars are baked into a portrait file
    wide: WideFrame | None = None


_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def _baked_bars(ffmpeg: str, source: Path, width: int, height: int) -> tuple[int, int] | None:
    """(height, top) of a wide picture saved inside a portrait file with black bars above and below.

    Such files come from apps that export a wide shot as 9:16. FFmpeg's cropdetect looks at the key frames of the first
    two minutes and keeps the area that was ever not black. Only bars across the full width that take a fifth of the
    height or more count, so a dark portrait clip is not mistaken for one.
    """
    try:
        result = subprocess.run([ffmpeg, "-v", "info", "-nostdin", "-skip_frame", "nokey", "-t", "120",
                                 "-i", str(source), "-vf", "cropdetect=limit=0.1:round=2:reset=0:skip=0", "-an",
                                 "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = _CROP.findall(result.stderr or "")
    if not found:
        return None
    w, h, _, y = (int(v) for v in found[-1])
    if w >= width * 0.95 and h <= height * 0.8 and width > h:
        return h, y
    return None


def _shape(ffmpeg: str, source: Path, info: MediaInfo) -> _Shape:
    width, height = info.display_width, info.display_height
    if info.is_wide:
        return _Shape(wide=wide_frame(width, height))
    if width and height:
        bars = _baked_bars(ffmpeg, source, width, height)
        if bars:
            picture, top = bars
            return _Shape(f"crop={width}:{picture}:0:{top},", wide_frame(width, picture))
    return _Shape()


def _cut_command(ffmpeg: str, source: Path, start: float, frames: int, has_audio: bool, output: str,
                 shape: _Shape = _Shape()) -> list[str]:
    seconds = frames / FPS
    # FFmpeg turns a phone clip upright by itself while reading it, so the sizes here are the on-screen ones.
    wide = shape.wide
    fit = (f"{shape.crop}scale={WIDTH}:{wide.height},pad={WIDTH}:{HEIGHT}:0:{wide.top}:black" if wide else
           f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black")
    video = f"[0:v]{fit},setsar=1,fps={FPS},format=yuv420p[v]"
    command = [ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(source)]
    if has_audio:
        audio = (f"[0:a:0]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"apad,atrim=end_sample={round(seconds * AUDIO_RATE)}[a]")
    else:
        command += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
        audio = f"[1:a]atrim=end_sample={round(seconds * AUDIO_RATE)}[a]"
    return command + ["-filter_complex", f"{video};{audio}", "-map", "[v]", "-map", "[a]",
                      "-frames:v", str(frames), "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                      "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", str(AUDIO_RATE),
                      "-map_metadata", "-1", output]


def render_reel(draft: ReelDraft, sources: Mapping[str, Path], output_dir: Path, *, ffmpeg: str = "ffmpeg",
                font: Path | None = None, on_progress: Progress | None = None,
                text_style: TextStyle | dict | None = None) -> ReelVideo:
    """Write ``output_dir/reel.mp4`` (replacing the old one only after the new one is checked)."""
    progress = on_progress or (lambda step, done, total: None)
    font = Path(font or reel_font())
    text_style = normalize(text_style)
    if not draft.scenes:
        raise ReelRenderError("REEL_NO_SCENES")
    if not font.is_file():
        raise ReelRenderError("REEL_FONT_MISSING", str(font))
    missing = [s.source_filename for s in draft.scenes if not Path(sources.get(str(s.source_video_id), "")).is_file()]
    if missing:
        raise ReelRenderError("REEL_SOURCE_MISSING", ", ".join(sorted(set(missing))))
    output_dir.mkdir(parents=True, exist_ok=True)
    info_by_source: dict[str, MediaInfo] = {}
    shape_by_source: dict[str, _Shape] = {}
    wide: list[WideFrame | None] = []
    with TemporaryDirectory(prefix="reel-", dir=output_dir) as directory:
        stage = Path(directory)
        total = len(draft.scenes)
        names = []
        for number, scene in enumerate(draft.scenes, start=1):
            progress("장면 잘라 세로로 맞추기", number - 1, total)
            source = Path(sources[str(scene.source_video_id)])
            key = str(source)
            if key not in info_by_source:
                try:
                    info_by_source[key] = probe_media(source)
                except MediaProbeError as error:
                    raise ReelRenderError("REEL_SOURCE_INVALID", source.name) from error
                shape_by_source[key] = _shape(ffmpeg, source, info_by_source[key])
            info, shape = info_by_source[key], shape_by_source[key]
            wide.append(shape.wide)  # each scene on its own (TODO 17)
            name = f"scene-{number:03d}.mp4"
            _run(_cut_command(ffmpeg, source, scene.start_seconds, _frames(scene.end_seconds - scene.start_seconds),
                              info.has_audio_stream, name, shape), stage, "REEL_CUT_FAILED")
            names.append(name)
        progress("장면 이어 붙이기", total, total)
        (stage / "list.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
        _run([ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
              "-c", "copy", "joined.mp4"], stage, "REEL_JOIN_FAILED")
        progress("제목·문구 글자 입히기", total, total)
        (stage / "captions.ass").write_text(build_ass(draft, text_style, wide), encoding="utf-8")
        for file in {font, *font_files(text_style)}:  # the template's typefaces, next to the subtitle file
            shutil.copyfile(file, stage / file.name.lower())
        # Relative names only: Windows drive letters ("C:") break FFmpeg's filter syntax.
        _run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", "joined.mp4", "-vf", "ass=captions.ass:fontsdir=.",
              "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy",
              "-movflags", "+faststart", "final.mp4"], stage, "REEL_TEXT_FAILED")
        final = stage / "final.mp4"
        try:
            info = probe_media(final)
        except MediaProbeError as error:
            raise ReelRenderError("REEL_OUTPUT_INVALID") from error
        expected = sum(_frames(s.end_seconds - s.start_seconds) for s in draft.scenes) / FPS
        if not info.has_video_stream or abs(info.duration_seconds - expected) > 0.25:
            raise ReelRenderError("REEL_OUTPUT_INVALID", f"{info.duration_seconds} vs {expected}")
        destination = output_dir / VIDEO_NAME
        final.replace(destination)
    video = ReelVideo(destination, round(info.duration_seconds, 2), destination.stat().st_size,
                      draft_fingerprint(draft), len(draft.scenes), text_style)
    (output_dir / INFO_NAME).write_text(json.dumps({
        "duration_seconds": video.duration_seconds, "file_size_bytes": video.file_size_bytes,
        "draft_fingerprint": video.draft_fingerprint, "scene_count": video.scene_count,
        "text_style": text_style.to_json()}), encoding="utf-8")
    return video


def saved_video(output_dir: Path) -> ReelVideo | None:
    path, info = output_dir / VIDEO_NAME, output_dir / INFO_NAME
    if not path.is_file() or not info.is_file():
        return None
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
        return ReelVideo(path, float(data["duration_seconds"]), path.stat().st_size, str(data["draft_fingerprint"]),
                         int(data["scene_count"]), normalize(data.get("text_style")))
    except (OSError, ValueError, KeyError, TypeError):
        return None
