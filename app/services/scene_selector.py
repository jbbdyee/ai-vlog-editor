from dataclasses import dataclass
import math
from numbers import Real
from pathlib import Path
from typing import Protocol

from app.services.audio_extractor import ExtractedAudio
from app.services.candidate_generator import SceneCandidate
from app.services.media_probe import MediaInfo
from app.services.memo_detector import EditMemo
from app.services.stt_service import STTResult


class SceneSelectionError(ValueError):
    """Raised when a scene selector cannot return a trusted candidate."""


@dataclass(frozen=True)
class SceneSelectionContext:
    source_video_path: Path
    extracted_audio: ExtractedAudio
    media_info: MediaInfo
    transcript: STTResult
    memo: EditMemo
    fixed_candidates: tuple[SceneCandidate, ...]


@dataclass(frozen=True)
class SceneSelectionResult:
    strategy_name: str
    candidate: SceneCandidate | None
    selected_source_id: str | None
    reasoning_code: str
    reasoning_summary: str | None


class SceneSelector(Protocol):
    """Application-level contract for returning a validated scene candidate."""

    def select(self, context: SceneSelectionContext) -> SceneSelectionResult: ...


class FixedWindowSceneSelector:
    """Select the one generated candidate explicitly requested by the caller."""

    def __init__(self, *, window_seconds: float) -> None:
        self.window_seconds = _positive_finite_number(
            window_seconds, "Window seconds"
        )

    def select(self, context: SceneSelectionContext) -> SceneSelectionResult:
        if not isinstance(context, SceneSelectionContext):
            raise SceneSelectionError(
                "Selection context must be a SceneSelectionContext."
            )

        matches = tuple(
            candidate
            for candidate in context.fixed_candidates
            if isinstance(candidate, SceneCandidate)
            and candidate.window_seconds == self.window_seconds
        )
        if not matches:
            raise SceneSelectionError(
                f"No generated candidate matches window {self.window_seconds}."
            )
        if len(matches) > 1:
            raise SceneSelectionError(
                f"Multiple generated candidates match window {self.window_seconds}."
            )

        return SceneSelectionResult(
            strategy_name="fixed_window",
            candidate=matches[0],
            selected_source_id=f"window:{self.window_seconds}",
            reasoning_code="FIXED_WINDOW_SELECTED",
            reasoning_summary=None,
        )


def _positive_finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SceneSelectionError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise SceneSelectionError(f"{label} must be a finite number.")
    if number <= 0:
        raise SceneSelectionError(f"{label} must be greater than zero.")
    return number
