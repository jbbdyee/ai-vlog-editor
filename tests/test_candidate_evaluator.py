from unittest import TestCase

from app.services.candidate_evaluator import (
    EvaluationError,
    GroundTruthSegment,
    evaluate_candidate,
)
from app.services.candidate_generator import SceneCandidate


class CandidateEvaluatorTests(TestCase):
    def test_exact_match_has_perfect_overlap_and_no_boundary_error(self) -> None:
        result = evaluate_candidate(
            self._candidate(10.0, 15.0),
            self._ground_truth(10.0, 15.0),
        )

        self.assertEqual(result.iou, 1.0)
        self.assertEqual(result.coverage, 1.0)
        self.assertEqual(result.start_boundary_error, 0.0)
        self.assertEqual(result.end_boundary_error, 0.0)
        self.assertEqual(result.total_boundary_error, 0.0)

    def test_partial_overlap_calculates_all_metrics(self) -> None:
        result = evaluate_candidate(
            self._candidate(5.0, 15.0),
            self._ground_truth(10.0, 20.0),
        )

        self.assertAlmostEqual(result.iou, 5.0 / 15.0)
        self.assertEqual(result.coverage, 0.5)
        self.assertEqual(result.start_boundary_error, 5.0)
        self.assertEqual(result.end_boundary_error, 5.0)
        self.assertEqual(result.total_boundary_error, 10.0)

    def test_no_overlap_has_zero_iou_and_coverage(self) -> None:
        result = evaluate_candidate(
            self._candidate(0.0, 5.0),
            self._ground_truth(10.0, 15.0),
        )

        self.assertEqual(result.iou, 0.0)
        self.assertEqual(result.coverage, 0.0)

    def test_candidate_containing_ground_truth_has_full_coverage(self) -> None:
        result = evaluate_candidate(
            self._candidate(5.0, 25.0),
            self._ground_truth(10.0, 20.0),
        )

        self.assertEqual(result.iou, 0.5)
        self.assertEqual(result.coverage, 1.0)

    def test_ground_truth_containing_candidate_uses_ground_truth_for_coverage(
        self,
    ) -> None:
        result = evaluate_candidate(
            self._candidate(12.0, 18.0),
            self._ground_truth(10.0, 20.0),
        )

        self.assertEqual(result.iou, 0.6)
        self.assertEqual(result.coverage, 0.6)
        self.assertEqual(result.start_boundary_error, 2.0)
        self.assertEqual(result.end_boundary_error, 2.0)
        self.assertEqual(result.total_boundary_error, 4.0)

    def test_invalid_intervals_are_rejected(self) -> None:
        invalid_cases = (
            (self._candidate(10.0, 10.0), self._ground_truth(10.0, 15.0)),
            (self._candidate(10.0, 9.0), self._ground_truth(10.0, 15.0)),
            (self._candidate(10.0, 15.0), self._ground_truth(10.0, 10.0)),
            (self._candidate(-1.0, 5.0), self._ground_truth(10.0, 15.0)),
        )

        for candidate, ground_truth in invalid_cases:
            with self.subTest(candidate=candidate, ground_truth=ground_truth):
                with self.assertRaises(EvaluationError):
                    evaluate_candidate(candidate, ground_truth)

    def test_nan_inf_and_wrong_types_are_rejected(self) -> None:
        invalid_values = (float("nan"), float("inf"), "10", True)
        for value in invalid_values:
            with self.subTest(candidate_start=value):
                with self.assertRaises(EvaluationError):
                    evaluate_candidate(
                        self._candidate(value, 15.0),
                        self._ground_truth(10.0, 15.0),
                    )

            with self.subTest(ground_truth_end=value):
                with self.assertRaises(EvaluationError):
                    evaluate_candidate(
                        self._candidate(10.0, 15.0),
                        self._ground_truth(10.0, value),
                    )

        with self.assertRaises(EvaluationError):
            evaluate_candidate(
                SceneCandidate(
                    window_seconds=float("nan"),
                    start_seconds=10.0,
                    end_seconds=15.0,
                ),
                self._ground_truth(10.0, 15.0),
            )

    @staticmethod
    def _candidate(start: object, end: object) -> SceneCandidate:
        return SceneCandidate(
            window_seconds=5.0,
            start_seconds=start,  # type: ignore[arg-type]
            end_seconds=end,  # type: ignore[arg-type]
        )

    @staticmethod
    def _ground_truth(start: object, end: object) -> GroundTruthSegment:
        return GroundTruthSegment(
            start_seconds=start,  # type: ignore[arg-type]
            end_seconds=end,  # type: ignore[arg-type]
        )
