from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel


DEFAULT_MODEL_NAME = "small"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"
DEFAULT_LANGUAGE = "ko"


class STTError(RuntimeError):
    """Raised when a local audio file cannot be transcribed."""


@dataclass(frozen=True)
class TranscriptWord:
    start_seconds: float
    end_seconds: float
    text: str
    probability: float | None


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[TranscriptWord, ...] = ()


@dataclass(frozen=True)
class STTResult:
    text: str
    segments: tuple[TranscriptSegment, ...]
    language: str
    language_probability: float | None


def load_model(
    model_name: str = DEFAULT_MODEL_NAME,
    *,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
) -> WhisperModel:
    """Load the configured faster-whisper model for local inference."""
    try:
        return WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:
        raise STTError(f"Could not load faster-whisper model '{model_name}'.") from exc


def transcribe_audio(
    audio_path: str | Path,
    *,
    model: WhisperModel | None = None,
    word_timestamps: bool = False,
) -> STTResult:
    """Transcribe one local WAV file into timestamped Korean segments."""
    path = Path(audio_path)
    if not path.is_file():
        raise STTError(f"Audio file does not exist: {path}")
    if path.suffix.lower() != ".wav":
        raise STTError(f"Audio file must be WAV: {path.name}")
    if path.stat().st_size == 0:
        raise STTError(f"Audio file is empty: {path.name}")

    stt_model = model if model is not None else load_model()

    try:
        raw_segments, info = stt_model.transcribe(
            str(path),
            language=DEFAULT_LANGUAGE,
            word_timestamps=word_timestamps,
        )
        segments = tuple(
            _parse_segment(segment, include_words=word_timestamps)
            for segment in raw_segments
        )
    except STTError:
        raise
    except Exception as exc:
        raise STTError(f"STT transcription failed for {path.name}.") from exc

    return STTResult(
        text=" ".join(segment.text for segment in segments).strip(),
        segments=segments,
        language=_optional_string(getattr(info, "language", None))
        or DEFAULT_LANGUAGE,
        language_probability=_optional_float(
            getattr(info, "language_probability", None)
        ),
    )


def _parse_segment(segment: Any, *, include_words: bool) -> TranscriptSegment:
    try:
        start_seconds = float(segment.start)
        end_seconds = float(segment.end)
        text = str(segment.text).strip()
    except (AttributeError, TypeError, ValueError) as exc:
        raise STTError("faster-whisper returned an invalid transcript segment.") from exc

    if start_seconds < 0 or end_seconds < start_seconds:
        raise STTError("faster-whisper returned invalid segment timestamps.")

    words = ()
    if include_words:
        words = tuple(_parse_word(word) for word in (segment.words or ()))

    return TranscriptSegment(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
        words=words,
    )


def _parse_word(word: Any) -> TranscriptWord:
    try:
        start_seconds = float(word.start)
        end_seconds = float(word.end)
        text = str(word.word).strip()
    except (AttributeError, TypeError, ValueError) as exc:
        raise STTError("faster-whisper returned an invalid word timestamp.") from exc

    if start_seconds < 0 or end_seconds < start_seconds:
        raise STTError("faster-whisper returned invalid word timestamps.")

    return TranscriptWord(
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
        probability=_optional_float(getattr(word, "probability", None)),
    )


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
