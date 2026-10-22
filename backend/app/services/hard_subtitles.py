"""Isolated Docker/libass burn-in for an already rendered MP4 and SRT."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from backend.app.services.media_probe import MediaProbeError, probe_media


IMAGE = "lscr.io/linuxserver/ffmpeg@sha256:1f9755c920d41b30c4630eb6d54ac4d9badc4f5b0ca3e7f495a98d00e8020c3a"
FONT_SHA256 = "6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a"


class HardSubtitleError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def burn_hard_subtitles(mp4: Path, srt: Path, font: Path, *, docker: str = "docker") -> Path:
    """Create final-subtitled.mp4 atomically, preserving the source files on failure.

    Docker receives only copied inputs in a disposable staging directory. The
    caller must opt in by supplying a verified local font path.
    """
    import hashlib

    mp4, srt, font = Path(mp4), Path(srt), Path(font)
    destination = mp4.with_name("final-subtitled.mp4")
    if not mp4.is_file() or not srt.is_file():
        raise HardSubtitleError("SUBTITLE_INPUT_MISSING")
    try:
        srt_text = srt.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise HardSubtitleError("SUBTITLE_INPUT_INVALID") from error
    if not srt_text.strip():
        raise HardSubtitleError("SUBTITLE_INPUT_MISSING")
    try:
        font_hash = hashlib.sha256(font.read_bytes()).hexdigest() if font.is_file() else None
    except OSError as error:
        raise HardSubtitleError("SUBTITLE_FONT_INVALID") from error
    if font_hash != FONT_SHA256:
        raise HardSubtitleError("SUBTITLE_FONT_INVALID")
    if destination.exists():
        raise HardSubtitleError("SUBTITLE_OUTPUT_EXISTS")
    try:
        source_info = probe_media(mp4)
        with TemporaryDirectory(prefix="hard-subtitles-", dir=mp4.parent) as directory:
            stage = Path(directory)
            shutil.copyfile(mp4, stage / "input.mp4")
            shutil.copyfile(srt, stage / "captions.srt")
            shutil.copyfile(font, stage / "NotoSansCJKkr-Regular.otf")
            mount = f"type=bind,source={stage.resolve()},target=/work"
            command = [docker, "run", "--rm", "--network", "none", "--platform", "linux/amd64",
                       "--memory", "2g", "--cpus", "2", "--pids-limit", "128",
                       "--mount", mount, "--entrypoint", "ffmpeg", IMAGE,
                       "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-i", "/work/input.mp4", "-vf",
                       "subtitles=/work/captions.srt:fontsdir=/work:force_style=FontName=Noto Sans CJK KR",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy",
                       "/work/output.mp4"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=1800, check=False)
            if result.returncode != 0:
                raise HardSubtitleError("SUBTITLE_RENDER_FAILED")
            output = stage / "output.mp4"
            if not output.is_file() or output.stat().st_size == 0:
                raise HardSubtitleError("SUBTITLE_OUTPUT_MISSING")
            output_info = probe_media(output)
            if (output_info.video_codec != "h264" or output_info.audio_codec != "aac"
                    or not output_info.has_video_stream or not output_info.has_audio_stream
                    or abs(output_info.duration_seconds - source_info.duration_seconds) > 0.1):
                raise HardSubtitleError("SUBTITLE_OUTPUT_INVALID")
            shutil.copyfile(output, stage / "validated.mp4")
            (stage / "validated.mp4").replace(destination)
        return destination
    except (OSError, UnicodeError, MediaProbeError, subprocess.TimeoutExpired) as error:
        raise HardSubtitleError("SUBTITLE_RENDER_FAILED") from error
