from unittest import TestCase

from app.services.candidate_generator import (
    CandidateGenerationError,
    SceneCandidate,
    generate_candidates,
)
from app.services.memo_detector import EditMemo


class CandidateGeneratorTests(TestCase):
    def test_default_windows_generate_expected_eval_01_candidates(self) -> None:
        candidates = generate_candidates(self._memo(start_seconds=15.8))

        self.assertEqual(len(candidates), 4)
        self._assert_candidate(candidates[0], 5.0, 10.8, 15.8)
        self._assert_candidate(candidates[1], 10.0, 5.8, 15.8)
        self._assert_candidate(candidates[2], 15.0, 0.8, 15.8)
        self._assert_candidate(candidates[3], 30.0, 0.0, 15.8)

    def test_start_timestamp_is_clamped_to_zero(self) -> None:
        candidate = generate_candidates(
            self._memo(start_seconds=3.0), windows_seconds=(5.0,)
        )[0]

        self.assertEqual(candidate.start_seconds, 0.0)

    def test_candidate_end_is_always_memo_start(self) -> None:
        memo = self._memo(start_seconds=12.25)

        candidates = generate_candidates(memo)

        self.assertTrue(
            all(candidate.end_seconds == memo.start_seconds for candidate in candidates)
        )

    def test_negative_memo_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(CandidateGenerationError, "must not be negative"):
            generate_candidates(self._memo(start_seconds=-0.1))

    def test_zero_or_negative_window_is_rejected(self) -> None:
        for window in (0.0, -5.0):
            with self.subTest(window=window):
                with self.assertRaisesRegex(
                    CandidateGenerationError, "greater than zero"
                ):
                    generate_candidates(
                        self._memo(start_seconds=15.8),
                        windows_seconds=(window,),
                    )

    def test_invalid_numbers_are_rejected(self) -> None:
        invalid_memo_values = (float("nan"), float("inf"), "15.8", True)
        for value in invalid_memo_values:
            with self.subTest(memo_start=value):
                with self.assertRaises(CandidateGenerationError):
                    generate_candidates(self._memo(start_seconds=value))

        invalid_windows = (float("nan"), float("inf"), "5", False)
        for value in invalid_windows:
            with self.subTest(window=value):
                with self.assertRaises(CandidateGenerationError):
                    generate_candidates(
                        self._memo(start_seconds=15.8),
                        windows_seconds=(value,),
                    )

    def test_custom_window_order_is_preserved(self) -> None:
        candidates = generate_candidates(
            self._memo(start_seconds=15.8),
            windows_seconds=(15.0, 5.0, 30.0, 10.0),
        )

        self.assertEqual(
            tuple(candidate.window_seconds for candidate in candidates),
            (15.0, 5.0, 30.0, 10.0),
        )

    @staticmethod
    def _memo(start_seconds: object) -> EditMemo:
        return EditMemo(
            start_seconds=start_seconds,  # type: ignore[arg-type]
            end_seconds=18.72,
            transcript_text="에이아이아 지금 장면 꼭 살려줘.",
            matched_trigger="에이아이아",
            matched_reference="지금",
            matched_action="살려줘",
        )

    def _assert_candidate(
        self,
        candidate: SceneCandidate,
        window_seconds: float,
        start_seconds: float,
        end_seconds: float,
    ) -> None:
        self.assertEqual(candidate.window_seconds, window_seconds)
        self.assertAlmostEqual(candidate.start_seconds, start_seconds)
        self.assertEqual(candidate.end_seconds, end_seconds)
