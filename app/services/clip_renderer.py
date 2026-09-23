from dataclasses import dataclass
import math
from numbers import Real
from pathlib import Path
import subprocess
from uuid import uuid4

from app.services.candidate_generator import SceneCandidate
from app.services.media_probe import MediaProbeError, probe_media


VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
VIDEO_PIXEL_FORMAT = "yuv420p"
AUDIO_BITRATE = "128k"


class ClipRenderError(RuntimeError):
    """Raised when a scene candidate cannot be rendered as a usable MP4."""


@dataclass(frozen=True)
class RenderedClip:
    source_path: Path
    clip_path: Path
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    video_codec: str | None
    audio_codec: str | None


def render_clip(
    source_path: str | Path,
    candidate: SceneCandidate,
    output_directory: str | Path,
    *,
    ffmpeg_executable: str = "ffmpeg",
) -> RenderedClip:
    """Render one validated scene candidate as a broadly compatible MP4."""
    media_path = Path(source_path)
    destination_directory = Path(output_directory)

    if not media_path.is_file():
        raise ClipRenderError(f"Source video does not exist: {media_path}")
    if not isinstance(candidate, SceneCandidate):
        raise ClipRenderError("Candidate must be a SceneCandidate.")

    window = _validate_number(candidate.window_seconds, "Candidate window")
    if window <= 0:
        raise ClipRenderError("Candidate window must be greater than zero.")
    start, end = _validate_interval(candidate.start_seconds, candidate.end_seconds)

    try:
        source_info = probe_media(media_path)
    except MediaProbeError as exc:
        raise ClipRenderError(f"Could not inspect source video: {exc}") from exc

    if not source_info.has_video_stream:
        raise ClipRenderError(f"Source has no video stream: {media_path.name}")
    if end > source_info.duration_seconds + 1e-6:
        raise ClipRenderError(
            "Candidate end exceeds source video duration: "
            f"{end} > {source_info.duration_seconds}"
        )

    try:
        destination_directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ClipRenderError(
            f"Could not create clip output directory: {destination_directory}"
        ) from exc

    clip_path = _reserve_clip_path(destination_directory)
    requested_duration = end - start
    command = [
        ffmpeg_executable,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(media_path),
        "-t",
        str(requested_duration),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-c:v",
        VIDEO_CODEC,
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        VIDEO_PIXEL_FORMAT,
        "-c:a",
        AUDIO_CODEC,
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        str(clip_path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        clip_path.unlink(missing_ok=True)
        raise ClipRenderError(f"Could not start FFmpeg: {exc}") from exc

    if result.returncode != 0:
        clip_path.unlink(missing_ok=True)
        detail = result.stderr.strip() or "No error details were returned."
        raise ClipRenderError(
            f"FFmpeg clip rendering failed for {media_path.name}: {detail}"
        )

    if not clip_path.is_file() or clip_path.stat().st_size == 0:
        clip_path.unlink(missing_ok=True)
        raise ClipRenderError(
            f"FFmpeg did not create a usable clip for {media_path.name}."
        )

    try:
        clip_info = probe_media(clip_path)
    except MediaProbeError as exc:
        clip_path.unlink(missing_ok=True)
        raise ClipRenderError(f"Could not verify rendered clip: {exc}") from exc

    if not clip_info.has_video_stream:
        clip_path.unlink(missing_ok=True)
        raise ClipRenderError("Rendered clip has no video stream.")

    return RenderedClip(
        source_path=media_path,
        clip_path=clip_path,
        start_seconds=start,
        end_seconds=end,
        duration_seconds=clip_info.duration_seconds,
        video_codec=clip_info.video_codec,
        audio_codec=clip_info.audio_codec,
    )


def _validate_interval(raw_start: object, raw_end: object) -> tuple[float, float]:
    start = _validate_number(raw_start, "Candidate start")
    end = _validate_number(raw_end, "Candidate end")

    if start < 0:
        raise ClipRenderError("Candidate start must not be negative.")
    if end <= start:
        raise ClipRenderError("Candidate end must be greater than start.")
    return start, end


def _validate_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ClipRenderError(f"{label} must be a valid number.")

    number = float(value)
    if not math.isfinite(number):
        raise ClipRenderError(f"{label} must be a finite number.")
    return number


def _reserve_clip_path(output_directory: Path) -> Path:
    while True:
        candidate = output_directory / f"{uuid4().hex}.mp4"
        try:
            candidate.touch(exist_ok=False)
        except FileExistsError:
            continue
        else:
            return candidate
