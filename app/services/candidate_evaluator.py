from dataclasses import dataclass
import math
from numbers import Real

from app.services.candidate_generator import SceneCandidate


class EvaluationError(ValueError):
    """Raised when candidate evaluation inputs are invalid."""


@dataclass(frozen=True)
class GroundTruthSegment:
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class CandidateEvaluation:
    window_seconds: float
    iou: float
    coverage: float
    start_boundary_error: float
    end_boundary_error: float
    total_boundary_error: float


def evaluate_candidate(
    candidate: SceneCandidate,
    ground_truth: GroundTruthSegment,
) -> CandidateEvaluation:
    """Calculate overlap and boundary metrics without ranking the candidate."""
    if not isinstance(candidate, SceneCandidate):
        raise EvaluationError("Candidate must be a SceneCandidate.")
    if not isinstance(ground_truth, GroundTruthSegment):
        raise EvaluationError("Ground truth must be a GroundTruthSegment.")

    window = _validate_number(candidate.window_seconds, "Candidate window")
    if window <= 0:
        raise EvaluationError("Candidate window must be greater than zero.")

    candidate_start, candidate_end = _validate_interval(
        candidate.start_seconds,
        candidate.end_seconds,
        "Candidate",
    )
    ground_truth_start, ground_truth_end = _validate_interval(
        ground_truth.start_seconds,
        ground_truth.end_seconds,
        "Ground truth",
    )

    intersection = max(
        0.0,
        min(candidate_end, ground_truth_end)
        - max(candidate_start, ground_truth_start),
    )
    candidate_length = candidate_end - candidate_start
    ground_truth_length = ground_truth_end - ground_truth_start
    union = candidate_length + ground_truth_length - intersection

    if union <= 0 or ground_truth_length <= 0:
        raise EvaluationError("Evaluation intervals must have positive length.")

    start_error = abs(candidate_start - ground_truth_start)
    end_error = abs(candidate_end - ground_truth_end)

    return CandidateEvaluation(
        window_seconds=window,
        iou=intersection / union,
        coverage=intersection / ground_truth_length,
        start_boundary_error=start_error,
        end_boundary_error=end_error,
        total_boundary_error=start_error + end_error,
    )


def _validate_interval(
    raw_start: object,
    raw_end: object,
    label: str,
) -> tuple[float, float]:
    start = _validate_number(raw_start, f"{label} start")
    end = _validate_number(raw_end, f"{label} end")

    if start < 0 or end < 0:
        raise EvaluationError(f"{label} timestamps must not be negative.")
    if start >= end:
        raise EvaluationError(f"{label} start must be less than end.")
    return start, end


def _validate_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EvaluationError(f"{label} must be a valid number.")

    number = float(value)
    if not math.isfinite(number):
        raise EvaluationError(f"{label} must be a finite number.")
    return number
