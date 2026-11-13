"""TODO 12: turn a saved reel draft into a vertical (9:16) MP4 with the title, name tags and lines burned in.

Steps (all local FFmpeg, no AI):
1. cut every scene from its source and fit it into a 1080x1920 frame (wide shots get black bars above and below,
   nothing is cropped). Each piece is snapped to whole frames and gets audio of exactly the same length (silence when
   the source has none), so joining many pieces never drifts (the TODO 9 lesson).
2. join the pieces without re-encoding.
3. write an ASS subtitle file (title on the hook scene at the top, name tag + line per scene near the bottom) and burn
   it in with a Korean font. Emoji are dropped because the font has none (they would show as empty boxes).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from backend.app.services.media_probe import MediaProbeError, probe_media
from backend.app.services.reel_draft import ReelDraft

WIDTH, HEIGHT, FPS = 1080, 1920, 30
AUDIO_RATE = 48000
DEFAULT_FONT = Path(r"C:\Windows\Fonts\malgunbd.ttf")
FONT_NAME = "Malgun Gothic"
TITLE_MIN_SECONDS = 2.5  # a very short hook scene still leaves the title on screen long enough to read
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


def draft_fingerprint(draft: ReelDraft) -> str:
    """Changes whenever the draft changes, so the screen can tell an old video from the current draft."""
    return hashlib.sha256(json.dumps(draft.to_json(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def reel_font() -> Path:
    return Path(os.environ.get("CUTORY_REEL_FONT_PATH") or DEFAULT_FONT)


# Emoji, pictographs, dingbats, variation selectors and joiners; everything else (Korean, Latin, digits) stays.
_EMOJI = re.compile("[\U00010000-\U0010FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE00-\uFE0F\u200D\u20E3]")


def clean_text(text: str) -> str:
    text = _EMOJI.sub("", text or "")
    text = text.replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"\s+", " ", text).strip()


def _frames(seconds: float) -> int:
    return max(1, round(seconds * FPS))


def _ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def build_ass(draft: ReelDraft) -> str:
    """Times follow the frame-snapped scene lengths, the same ones used to cut the video."""
    # Colours are &HAABBGGRR. Title/Caption: white with a thick black outline; Label: light cyan.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{FONT_NAME},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,8,80,80,250,1
Style: Caption,{FONT_NAME},74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,90,90,330,1
Style: Label,{FONT_NAME},52,&H00F2E79F,&H00F2E79F,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,1,2,90,90,440,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    t = 0.0
    total = sum(_frames(s.end_seconds - s.start_seconds) for s in draft.scenes) / FPS
    for index, scene in enumerate(draft.scenes):
        length = _frames(scene.end_seconds - scene.start_seconds) / FPS
        start, end = _ass_time(t), _ass_time(t + length)
        caption, label = clean_text(scene.caption), clean_text(scene.label)
        if index == 0 and clean_text(draft.title):
            events.append(f"Dialogue: 1,{start},{_ass_time(min(total, max(length, TITLE_MIN_SECONDS)))},Title,,0,0,0,,"
                          f"{clean_text(draft.title)}")
        if label:
            events.append(f"Dialogue: 0,{start},{end},Label,,0,0,0,,{label}")
        if caption:
            events.append(f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{caption}")
        t += length
    return header + "\n".join(events) + "\n"


def _run(command: list[str], cwd: Path, code: str) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReelRenderError(code, str(error)) from error
    if result.returncode != 0:
        raise ReelRenderError(code, result.stderr.strip()[-800:])


def _cut_command(ffmpeg: str, source: Path, start: float, frames: int, has_audio: bool, output: str) -> list[str]:
    seconds = frames / FPS
    video = (f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
             f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={FPS},format=yuv420p[v]")
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
                font: Path | None = None, on_progress: Progress | None = None) -> ReelVideo:
    """Write ``output_dir/reel.mp4`` (replacing the old one only after the new one is checked)."""
    progress = on_progress or (lambda step, done, total: None)
    font = Path(font or reel_font())
    if not draft.scenes:
        raise ReelRenderError("REEL_NO_SCENES")
    if not font.is_file():
        raise ReelRenderError("REEL_FONT_MISSING", str(font))
    missing = [s.source_filename for s in draft.scenes if not Path(sources.get(str(s.source_video_id), "")).is_file()]
    if missing:
        raise ReelRenderError("REEL_SOURCE_MISSING", ", ".join(sorted(set(missing))))
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_by_source: dict[str, bool] = {}
    with TemporaryDirectory(prefix="reel-", dir=output_dir) as directory:
        stage = Path(directory)
        total = len(draft.scenes)
        names = []
        for number, scene in enumerate(draft.scenes, start=1):
            progress("장면 잘라 세로로 맞추기", number - 1, total)
            source = Path(sources[str(scene.source_video_id)])
            key = str(source)
            if key not in audio_by_source:
                try:
                    audio_by_source[key] = probe_media(source).has_audio_stream
                except MediaProbeError as error:
                    raise ReelRenderError("REEL_SOURCE_INVALID", source.name) from error
            name = f"scene-{number:03d}.mp4"
            _run(_cut_command(ffmpeg, source, scene.start_seconds, _frames(scene.end_seconds - scene.start_seconds),
                              audio_by_source[key], name), stage, "REEL_CUT_FAILED")
            names.append(name)
        progress("장면 이어 붙이기", total, total)
        (stage / "list.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
        _run([ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
              "-c", "copy", "joined.mp4"], stage, "REEL_JOIN_FAILED")
        progress("제목·문구 글자 입히기", total, total)
        (stage / "captions.ass").write_text(build_ass(draft), encoding="utf-8")
        shutil.copyfile(font, stage / f"font{font.suffix.lower()}")
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
                      draft_fingerprint(draft), len(draft.scenes))
    (output_dir / INFO_NAME).write_text(json.dumps({
        "duration_seconds": video.duration_seconds, "file_size_bytes": video.file_size_bytes,
        "draft_fingerprint": video.draft_fingerprint, "scene_count": video.scene_count}), encoding="utf-8")
    return video


def saved_video(output_dir: Path) -> ReelVideo | None:
    path, info = output_dir / VIDEO_NAME, output_dir / INFO_NAME
    if not path.is_file() or not info.is_file():
        return None
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
        return ReelVideo(path, float(data["duration_seconds"]), path.stat().st_size, str(data["draft_fingerprint"]),
                         int(data["scene_count"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
