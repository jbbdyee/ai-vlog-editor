from unittest import TestCase

from app.services.candidate_evaluator import GroundTruthSegment, evaluate_candidate
from app.services.memo_detector import EditMemo
from app.services.semantic_block_selector import (
    MAX_REASONING_SUMMARY_CHARACTERS,
    SemanticBlockSelection,
    SemanticBlockSelectionError,
    SemanticBlockSelectionInput,
    run_block_selector,
    validate_block_selection,
)
from app.services.transcript_scene_retriever import TranscriptBlock


class SemanticBlockSelectorTests(TestCase):
    def test_valid_block_id_is_resolved_to_evaluator_compatible_candidate(self) -> None:
        selection_input = self._test_02_input()
        selection = self._selection("block-0001")

        result = validate_block_selection(
            selection_input,
            selection,
            video_duration_seconds=40.05,
        )

        self.assertEqual(result.selected_block.transcript_text, "아 뭐야 떨어졌네")
        self.assertEqual(result.candidate.start_seconds, 3.04)
        self.assertEqual(result.candidate.end_seconds, 10.96)
        self.assertAlmostEqual(result.candidate.window_seconds, 7.92)
        evaluation = evaluate_candidate(
            result.candidate,
            GroundTruthSegment(start_seconds=7.0, end_seconds=11.0),
        )
        self.assertGreater(evaluation.iou, 0.0)

    def test_provider_independent_selector_contract_is_runnable(self) -> None:
        selector = _FixedSelector(self._selection("block-0001"))

        result = run_block_selector(
            selector,
            self._test_02_input(),
            video_duration_seconds=40.05,
        )

        self.assertEqual(result.selected_block.block_id, "block-0001")
        self.assertEqual(selector.received_input, self._test_02_input())

    def test_unknown_block_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            SemanticBlockSelectionError, "does not exist"
        ):
            validate_block_selection(
                self._test_02_input(),
                self._selection("block-9999"),
                video_duration_seconds=40.05,
            )

    def test_empty_selection_is_rejected(self) -> None:
        with self.assertRaisesRegex(SemanticBlockSelectionError, "non-empty"):
            validate_block_selection(
                self._test_02_input(),
                self._selection(""),
                video_duration_seconds=40.05,
            )

    def test_empty_block_options_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            SemanticBlockSelectionError, "at least one transcript block"
        ):
            validate_block_selection(
                SemanticBlockSelectionInput(memo=self._memo(), blocks=()),
                self._selection("block-0001"),
                video_duration_seconds=40.05,
            )

    def test_post_memo_block_is_rejected(self) -> None:
        selection_input = SemanticBlockSelectionInput(
            memo=self._memo(),
            blocks=(self._block("block-after", 34.0, 36.0, "메모 이후"),),
        )

        with self.assertRaisesRegex(
            SemanticBlockSelectionError, "before the edit memo"
        ):
            validate_block_selection(
                selection_input,
                self._selection("block-after"),
                video_duration_seconds=40.05,
            )

    def test_invalid_block_interval_is_rejected(self) -> None:
        for start, end in (
            (10.0, 10.0),
            (11.0, 10.0),
            (float("nan"), 10.0),
            (10.0, float("inf")),
            ("10", 11.0),
        ):
            with self.subTest(start=start, end=end):
                selection_input = SemanticBlockSelectionInput(
                    memo=self._memo(),
                    blocks=(self._block("invalid", start, end, "잘못된 구간"),),
                )
                with self.assertRaises(SemanticBlockSelectionError):
                    validate_block_selection(
                        selection_input,
                        self._selection("invalid"),
                        video_duration_seconds=40.05,
                    )

    def test_block_beyond_video_duration_is_rejected(self) -> None:
        selection_input = SemanticBlockSelectionInput(
            memo=EditMemo(
                start_seconds=29.0,
                end_seconds=29.5,
                transcript_text="AI야 방금 장면 꼭 살려줘",
                matched_trigger="AI야",
                matched_reference="방금",
                matched_action="살려줘",
            ),
            blocks=(self._block("outside", 28.0, 31.0, "범위 초과"),),
        )

        with self.assertRaisesRegex(
            SemanticBlockSelectionError, "video duration"
        ):
            validate_block_selection(
                selection_input,
                self._selection("outside"),
                video_duration_seconds=30.0,
            )

    def test_reasoning_is_required_and_summary_length_is_limited(self) -> None:
        invalid_selections = (
            SemanticBlockSelection("block-0001", "", "짧은 근거"),
            SemanticBlockSelection("block-0001", "free form", "짧은 근거"),
            SemanticBlockSelection("block-0001", "RELATED_EVENT", ""),
            SemanticBlockSelection(
                "block-0001",
                "RELATED_EVENT",
                "가" * (MAX_REASONING_SUMMARY_CHARACTERS + 1),
            ),
        )
        for selection in invalid_selections:
            with self.subTest(selection=selection):
                with self.assertRaises(SemanticBlockSelectionError):
                    validate_block_selection(
                        self._test_02_input(),
                        selection,
                        video_duration_seconds=40.05,
                    )

    def test_schema_and_validation_do_not_require_ground_truth(self) -> None:
        selection_input = self._test_02_input()

        result = validate_block_selection(
            selection_input,
            self._selection("block-0002"),
            video_duration_seconds=40.05,
        )

        self.assertEqual(
            set(selection_input.__dataclass_fields__),
            {"memo", "blocks"},
        )
        self.assertEqual(result.candidate.start_seconds, 14.0)
        self.assertEqual(result.candidate.end_seconds, 23.8)

    @staticmethod
    def _selection(block_id: str) -> SemanticBlockSelection:
        return SemanticBlockSelection(
            selected_block_id=block_id,
            reasoning_code="RELATED_EVENT",
            reasoning_summary="메모와 관련된 사건 발화로 선택했다.",
        )

    @classmethod
    def _test_02_input(cls) -> SemanticBlockSelectionInput:
        return SemanticBlockSelectionInput(
            memo=cls._memo(),
            blocks=(
                cls._block("block-0001", 3.04, 10.96, "아 뭐야 떨어졌네"),
                cls._block(
                    "block-0002",
                    14.0,
                    23.8,
                    "다시 주었습니다... 다음 테스트도 해보겠습니다",
                ),
            ),
        )

    @staticmethod
    def _block(
        block_id: str, start: object, end: object, text: str
    ) -> TranscriptBlock:
        return TranscriptBlock(
            block_id=block_id,
            start_seconds=start,  # type: ignore[arg-type]
            end_seconds=end,  # type: ignore[arg-type]
            segment_ids=("segment-0001",),
            transcript_text=text,
        )

    @staticmethod
    def _memo() -> EditMemo:
        return EditMemo(
            start_seconds=32.84,
            end_seconds=36.32,
            transcript_text="아 AIA 방금 장면 꼭 살려줘",
            matched_trigger="AIA",
            matched_reference="방금",
            matched_action="살려줘",
            trigger_match_type="similarity",
            trigger_similarity=0.7272727272727273,
        )


class _FixedSelector:
    def __init__(self, selection: SemanticBlockSelection) -> None:
        self.selection = selection
        self.received_input: SemanticBlockSelectionInput | None = None

    def select(
        self, selection_input: SemanticBlockSelectionInput
    ) -> SemanticBlockSelection:
        self.received_input = selection_input
        return self.selection
