import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from faster_whisper import WhisperModel


def _register_cuda_dlls() -> None:
    """pip-installed cuBLAS/cuDNN (nvidia-*-cu12) live under site-packages/nvidia/*/bin on Windows."""
    if os.name != "nt":
        return
    for site_dir in sys.path:
        for dll_dir in (Path(site_dir) / "nvidia").glob("*/bin"):
            try:
                os.add_dll_directory(str(dll_dir))
            except OSError:
                continue
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")


_register_cuda_dlls()

logger = logging.getLogger("cutory.stt")

# Safe CPU setting: used when the graphics card cannot be used (TODO 42).
DEFAULT_MODEL_NAME = "small"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"
DEFAULT_LANGUAGE = "ko"

# Preferred setting: large-v3 on the graphics card. Override with CUTORY_STT_MODEL / _DEVICE / _COMPUTE_TYPE.
PREFERRED_MODEL_NAME = "large-v3"
PREFERRED_DEVICE = "cuda"
PREFERRED_COMPUTE_TYPE = "float16"

_fallback_model: WhisperModel | None = None


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


def load_best_model() -> WhisperModel:
    """Load large-v3 on the graphics card; fall back to the CPU setting when that fails."""
    model_name = os.environ.get("CUTORY_STT_MODEL", PREFERRED_MODEL_NAME)
    device = os.environ.get("CUTORY_STT_DEVICE", PREFERRED_DEVICE)
    compute_type = os.environ.get("CUTORY_STT_COMPUTE_TYPE", PREFERRED_COMPUTE_TYPE)
    try:
        model = load_model(model_name, device=device, compute_type=compute_type)
        if device != "cpu":
            # cuBLAS/cuDNN problems only surface on the first real run, so try one second of silence now.
            list(model.transcribe(np.zeros(16000, dtype=np.float32), language=DEFAULT_LANGUAGE)[0])
    except Exception as exc:
        logger.warning(
            "STT %s/%s/%s unavailable (%s); using %s/%s/%s",
            model_name, device, compute_type, exc,
            DEFAULT_MODEL_NAME, DEFAULT_DEVICE, DEFAULT_COMPUTE_TYPE,
        )
        return load_model()
    logger.warning("STT ready: %s/%s/%s", model_name, device, compute_type)
    return model


def _load_fallback_model() -> WhisperModel:
    global _fallback_model
    if _fallback_model is None:
        _fallback_model = load_model()
    return _fallback_model


def _is_gpu_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("cuda", "cublas", "cudnn", "out of memory"))


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

    def run(active_model: Any) -> tuple[tuple[TranscriptSegment, ...], Any]:
        raw_segments, raw_info = active_model.transcribe(
            str(path),
            language=DEFAULT_LANGUAGE,
            word_timestamps=word_timestamps,
        )
        parsed = tuple(
            _parse_segment(segment, include_words=word_timestamps)
            for segment in raw_segments
        )
        return parsed, raw_info

    try:
        try:
            segments, info = run(stt_model)
        except STTError:
            raise
        except Exception as exc:
            if not _is_gpu_error(exc):
                raise
            # e.g. graphics card memory taken by the local AI: redo this file on the CPU setting.
            logger.warning("STT graphics card failed for %s (%s); retrying on CPU", path.name, exc)
            segments, info = run(_load_fallback_model())
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
