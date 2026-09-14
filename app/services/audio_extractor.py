from dataclasses import dataclass
from pathlib import Path
import subprocess
from uuid import uuid4

from app.services.media_probe import MediaProbeError, probe_media


DEFAULT_SAMPLE_RATE_HZ = 16_000
DEFAULT_CHANNELS = 1
DEFAULT_PCM_CODEC = "pcm_s16le"


class AudioExtractionError(RuntimeError):
    """Raised when a source video cannot produce a usable WAV file."""


@dataclass(frozen=True)
class ExtractedAudio:
    source_path: Path
    audio_path: Path
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    codec: str


def extract_audio(
    source_path: str | Path,
    output_directory: str | Path,
    *,
    ffmpeg_executable: str = "ffmpeg",
) -> ExtractedAudio:
    """Extract the first audio stream from a local video as a PCM WAV file."""
    media_path = Path(source_path)
    destination_directory = Path(output_directory)

    if not media_path.is_file():
        raise AudioExtractionError(f"Media file does not exist: {media_path}")

    try:
        media_info = probe_media(media_path)
    except MediaProbeError as exc:
        raise AudioExtractionError(f"Could not inspect source media: {exc}") from exc

    if not media_info.has_audio_stream:
        raise AudioExtractionError(
            f"Source media has no audio stream: {media_path.name}"
        )

    try:
        destination_directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AudioExtractionError(
            f"Could not create audio output directory: {destination_directory}"
        ) from exc

    audio_path = _reserve_audio_path(destination_directory)
    command = [
        ffmpeg_executable,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(media_path),
        "-map",
        "0:a:0",
        "-vn",
        "-acodec",
        DEFAULT_PCM_CODEC,
        "-ar",
        str(DEFAULT_SAMPLE_RATE_HZ),
        "-ac",
        str(DEFAULT_CHANNELS),
        str(audio_path),
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
        audio_path.unlink(missing_ok=True)
        raise AudioExtractionError(f"Could not start FFmpeg: {exc}") from exc

    if result.returncode != 0:
        audio_path.unlink(missing_ok=True)
        detail = result.stderr.strip() or "No error details were returned."
        raise AudioExtractionError(
            f"FFmpeg audio extraction failed for {media_path.name}: {detail}"
        )

    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        audio_path.unlink(missing_ok=True)
        raise AudioExtractionError(
            f"FFmpeg did not create a usable audio file for {media_path.name}."
        )

    return ExtractedAudio(
        source_path=media_path,
        audio_path=audio_path,
        duration_seconds=media_info.duration_seconds,
        sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
        channels=DEFAULT_CHANNELS,
        codec=DEFAULT_PCM_CODEC,
    )


def _reserve_audio_path(output_directory: Path) -> Path:
    """Atomically reserve an unpredictable path owned by this extraction attempt."""
    while True:
        candidate = output_directory / f"{uuid4().hex}.wav"
        try:
            candidate.touch(exist_ok=False)
        except FileExistsError:
            continue
        else:
            return candidate
