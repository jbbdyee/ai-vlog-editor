"""TODO 27: small pictures (320 wide) of one moment of a source video, for the "다른 장면으로" choices.

One FFmpeg call per picture, saved under ``outputs/projects/<id>/thumbs/<source>_<ms>.jpg`` and reused next time.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import UUID

WIDTH = 320
TIMEOUT_SECONDS = 60


class ThumbError(RuntimeError):
    pass


def thumb_path(output_root: Path, project_id: UUID, source_id: UUID, seconds: float, width: int = WIDTH) -> Path:
    size = "" if width == WIDTH else f"_w{width}"  # TODO 41: bigger pictures for Claude live next to the small ones
    return Path(output_root) / str(project_id) / "thumbs" / f"{source_id.hex}_{int(round(seconds * 1000))}{size}.jpg"


def scene_thumb(output_root: Path, project_id: UUID, source_id: UUID, source: Path, seconds: float,
                ffmpeg: str | None = None, width: int = WIDTH) -> Path:
    path = thumb_path(output_root, project_id, source_id, seconds, width)
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.jpg")
    command = [ffmpeg or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{max(0.0, seconds):.3f}", "-i", str(source), "-frames:v", "1",
               "-vf", f"scale={width}:-2", "-q:v", "4", str(temporary)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        temporary.unlink(missing_ok=True)
        raise ThumbError("THUMB_FAILED") from error
    if not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise ThumbError("THUMB_FAILED")
    temporary.replace(path)
    return path
