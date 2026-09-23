from collections.abc import Iterable
from dataclasses import dataclass
import math
from numbers import Real

from app.services.memo_detector import EditMemo


DEFAULT_WINDOWS_SECONDS = (5.0, 10.0, 15.0, 30.0)


class CandidateGenerationError(ValueError):
    """Raised when a scene candidate cannot be generated safely."""


@dataclass(frozen=True)
class SceneCandidate:
    window_seconds: float
    start_seconds: float
    end_seconds: float


def generate_candidates(
    memo: EditMemo,
    *,
    windows_seconds: Iterable[float] = DEFAULT_WINDOWS_SECONDS,
) -> tuple[SceneCandidate, ...]:
    """Generate fixed-window scene candidates ending at an edit memo."""
    if not isinstance(memo, EditMemo):
        raise CandidateGenerationError("Input must be an EditMemo.")

    memo_start = _validate_number(memo.start_seconds, "Memo start timestamp")
    if memo_start < 0:
        raise CandidateGenerationError("Memo start timestamp must not be negative.")

    try:
        windows = tuple(windows_seconds)
    except TypeError as exc:
        raise CandidateGenerationError("Windows must be an iterable of numbers.") from exc

    candidates: list[SceneCandidate] = []
    for raw_window in windows:
        window = _validate_number(raw_window, "Window")
        if window <= 0:
            raise CandidateGenerationError("Window must be greater than zero.")

        candidates.append(
            SceneCandidate(
                window_seconds=window,
                start_seconds=max(0.0, memo_start - window),
                end_seconds=memo_start,
            )
        )

    return tuple(candidates)


def _validate_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CandidateGenerationError(f"{label} must be a valid number.")

    number = float(value)
    if not math.isfinite(number):
        raise CandidateGenerationError(f"{label} must be a finite number.")
    return number
