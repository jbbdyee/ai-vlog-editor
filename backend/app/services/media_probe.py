from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any


class MediaProbeError(RuntimeError):
    """Raised when ffprobe cannot produce usable media information."""


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_video_stream: bool
    has_audio_stream: bool
    video_codec: str | None
    audio_codec: str | None
    format_name: str


def probe_media(path: str | Path) -> MediaInfo:
    """Run ffprobe for a local file and return normalized media information."""
    media_path = Path(path)
    if not media_path.is_file():
        raise MediaProbeError(f"Media file does not exist: {media_path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
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
        raise MediaProbeError(f"Could not start ffprobe: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "No error details were returned."
        raise MediaProbeError(f"ffprobe failed for {media_path.name}: {detail}")

    try:
        output = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MediaProbeError("ffprobe returned invalid JSON output.") from exc

    return parse_media_info(output)


def parse_media_info(output: Any) -> MediaInfo:
    """Normalize a decoded ffprobe JSON object into the project data model."""
    if not isinstance(output, dict):
        raise MediaProbeError("ffprobe JSON output is not an object.")

    format_data = output.get("format")
    streams = output.get("streams")
    if not isinstance(format_data, dict) or not isinstance(streams, list):
        raise MediaProbeError("ffprobe output is missing format or stream information.")

    duration_seconds = _parse_duration(format_data.get("duration"))
    format_name = format_data.get("format_name")
    if not isinstance(format_name, str) or not format_name.strip():
        raise MediaProbeError("ffprobe output is missing the container format name.")

    video_stream = _first_stream(streams, "video")
    audio_stream = _first_stream(streams, "audio")

    return MediaInfo(
        duration_seconds=duration_seconds,
        has_video_stream=video_stream is not None,
        has_audio_stream=audio_stream is not None,
        video_codec=_codec_name(video_stream),
        audio_codec=_codec_name(audio_stream),
        format_name=format_name,
    )


def _parse_duration(value: Any) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise MediaProbeError("ffprobe output has an invalid duration.") from exc

    if duration < 0:
        raise MediaProbeError("ffprobe output has an invalid duration.")
    return duration


def _first_stream(
    streams: list[Any], stream_type: str
) -> dict[str, Any] | None:
    return next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == stream_type
        ),
        None,
    )


def _codec_name(stream: dict[str, Any] | None) -> str | None:
    if stream is None:
        return None

    codec_name = stream.get("codec_name")
    return codec_name if isinstance(codec_name, str) and codec_name else None
