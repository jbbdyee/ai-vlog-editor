"""TODO 35: a light 720p copy of each source video, so the edit room plays on a phone or another computer.

The originals (4K HEVC 10-bit, ~71 Mbps) are too heavy for phones. Each source gets one H.264 copy at
``outputs/projects/<id>/previews/<source>.mp4`` (short side 720, 30 fps, a keyframe every second so jumping
between cuts is quick). It is made once, in the background, one file at a time. The final 4K render still
reads the originals.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from uuid import UUID

SHORT_SIDE = 720
FPS = 30
TIMEOUT_SECONDS = 3600


class PreviewError(RuntimeError):
    pass


def preview_path(output_root: Path, project_id: UUID, source_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "previews" / f"{source_id.hex}.mp4"


def is_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def make_preview(source: Path, target: Path, ffmpeg: str | None = None) -> Path:
    if is_ready(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.mp4")
    size = (f"scale='if(gt(iw,ih),-2,{SHORT_SIDE})':'if(gt(iw,ih),{SHORT_SIDE},-2)'")
    command = [ffmpeg or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
               "-vf", f"{size},fps={FPS}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-g", str(FPS), "-keyint_min", str(FPS), "-sc_threshold", "0",
               "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(temporary)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        temporary.unlink(missing_ok=True)
        raise PreviewError("PREVIEW_FAILED") from error
    if not is_ready(temporary):
        temporary.unlink(missing_ok=True)
        raise PreviewError("PREVIEW_FAILED")
    temporary.replace(target)
    return target


class PreviewQueue:
    """Makes previews one at a time on a background thread; asking again only adds what is missing."""

    def __init__(self, make=make_preview):
        self._make = make
        self._lock = threading.Lock()
        self._waiting: list[tuple[Path, Path]] = []
        self._current: Path | None = None
        self._failed: set[Path] = set()
        self._thread: threading.Thread | None = None

    def ensure(self, items: list[tuple[Path, Path]]) -> None:
        """``items`` are (original, preview) pairs, most wanted first (they move ahead of older requests)."""
        with self._lock:
            wanted: list[tuple[Path, Path]] = []
            seen: set[Path] = set()
            for source, target in items:
                if target in seen or target == self._current or target in self._failed or is_ready(target):
                    continue
                wanted.append((source, target))
                seen.add(target)
            self._waiting = wanted + [item for item in self._waiting if item[1] not in seen]
            if self._waiting and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, name="source-previews", daemon=True)
                self._thread.start()

    def state(self, target: Path) -> str:
        with self._lock:
            if is_ready(target):
                return "ready"
            if target == self._current:
                return "making"
            if target in self._failed:
                return "failed"
            if any(target == waiting for _, waiting in self._waiting):
                return "waiting"
            return "missing"

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._waiting:
                    self._current = None
                    return
                source, target = self._waiting.pop(0)
                self._current = target
            try:
                self._make(source, target)
            except Exception:  # one broken file must not stop the rest
                with self._lock:
                    self._failed.add(target)


QUEUE = PreviewQueue()
