from unittest import TestCase

from app.services.candidate_evaluator import GroundTruthSegment, evaluate_candidate
from app.services.memo_detector import EditMemo
from app.services.stt_service import TranscriptSegment
from app.services.transcript_scene_retriever import (
    DEFAULT_SILENCE_THRESHOLD_SECONDS,
    TranscriptRetrievalError,
    build_transcript_blocks,
    retrieve_latest_block,
)


class TranscriptSceneRetrieverTests(TestCase):
    def test_segments_are_grouped_when_gap_does_not_exceed_threshold(self) -> None:
        segments = (
            self._segment(1.0, 2.0, "첫 문장"),
            self._segment(3.5, 4.0, "둘째 문장"),
            self._segment(6.1, 7.0, "새 발화"),
            self._segment(10.0, 12.0, "AI야 방금 장면 꼭 살려줘"),
        )

        blocks = build_transcript_blocks(
            segments,
            self._memo(10.0, 12.0),
            video_duration_seconds=15.0,
        )

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].block_id, "block-0001")
        self.assertEqual(blocks[0].segment_ids, ("segment-0001", "segment-0002"))
        self.assertEqual(blocks[0].transcript_text, "첫 문장 둘째 문장")
        self.assertEqual(blocks[1].segment_ids, ("segment-0003",))

    def test_gap_equal_to_threshold_remains_in_same_block(self) -> None:
        blocks = build_transcript_blocks(
            (
                self._segment(1.0, 2.0, "하나"),
                self._segment(4.0, 5.0, "둘"),
            ),
            self._memo(8.0, 9.0),
            video_duration_seconds=10.0,
        )

        self.assertEqual(DEFAULT_SILENCE_THRESHOLD_SECONDS, 2.0)
        self.assertEqual(len(blocks), 1)

    def test_memo_and_later_segments_are_excluded_from_context(self) -> None:
        blocks = build_transcript_blocks(
            (
                self._segment(1.0, 2.0, "이전 발화"),
                self._segment(5.0, 7.0, "AI야 방금 장면 꼭 살려줘"),
                self._segment(8.0, 9.0, "이후 발화"),
            ),
            self._memo(5.0, 7.0),
            video_duration_seconds=10.0,
        )

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].transcript_text, "이전 발화")

    def test_latest_block_becomes_evaluator_compatible_candidate(self) -> None:
        result = retrieve_latest_block(
            (
                self._segment(1.0, 2.0, "소개"),
                self._segment(5.0, 6.0, "중요한"),
                self._segment(6.5, 8.0, "장면"),
                self._segment(12.0, 14.0, "AI야 방금 장면 꼭 살려줘"),
            ),
            self._memo(12.0, 14.0),
            video_duration_seconds=15.0,
        )

        self.assertEqual(result.selected_block.block_id, "block-0002")
        self.assertEqual(result.candidate.window_seconds, 3.0)
        self.assertEqual(result.candidate.start_seconds, 5.0)
        self.assertEqual(result.candidate.end_seconds, 8.0)
        evaluation = evaluate_candidate(
            result.candidate,
            GroundTruthSegment(start_seconds=5.0, end_seconds=8.0),
        )
        self.assertEqual(evaluation.iou, 1.0)

    def test_empty_or_no_pre_memo_transcript_is_rejected_for_retrieval(self) -> None:
        for segments in (
            (),
            (self._segment(5.0, 7.0, "AI야 방금 장면 꼭 살려줘"),),
        ):
            with self.subTest(segments=segments):
                with self.assertRaisesRegex(
                    TranscriptRetrievalError, "no complete segment"
                ):
                    retrieve_latest_block(
                        segments,
                        self._memo(5.0, 7.0),
                        video_duration_seconds=10.0,
                    )

    def test_invalid_segment_order_and_timestamps_are_rejected(self) -> None:
        invalid_transcripts = (
            (
                self._segment(3.0, 4.0, "뒤"),
                self._segment(1.0, 2.0, "앞"),
            ),
            (self._segment(2.0, 2.0, "길이 없음"),),
            (self._segment(-1.0, 1.0, "음수"),),
        )
        for transcript in invalid_transcripts:
            with self.subTest(transcript=transcript):
                with self.assertRaises(TranscriptRetrievalError):
                    build_transcript_blocks(
                        transcript,
                        self._memo(5.0, 7.0),
                        video_duration_seconds=10.0,
                    )

    def test_nan_inf_and_wrong_numeric_types_are_rejected(self) -> None:
        invalid_values = (float("nan"), float("inf"), "10", True)
        for value in invalid_values:
            with self.subTest(video_duration=value):
                with self.assertRaises(TranscriptRetrievalError):
                    build_transcript_blocks(
                        (self._segment(1.0, 2.0, "문장"),),
                        self._memo(5.0, 7.0),
                        video_duration_seconds=value,  # type: ignore[arg-type]
                    )

            with self.subTest(threshold=value):
                with self.assertRaises(TranscriptRetrievalError):
                    build_transcript_blocks(
                        (self._segment(1.0, 2.0, "문장"),),
                        self._memo(5.0, 7.0),
                        video_duration_seconds=10.0,
                        silence_threshold_seconds=value,  # type: ignore[arg-type]
                    )

            with self.subTest(segment_start=value):
                with self.assertRaises(TranscriptRetrievalError):
                    build_transcript_blocks(
                        (self._segment(value, 2.0, "문장"),),
                        self._memo(5.0, 7.0),
                        video_duration_seconds=10.0,
                    )

            with self.subTest(memo_start=value):
                with self.assertRaises(TranscriptRetrievalError):
                    build_transcript_blocks(
                        (self._segment(1.0, 2.0, "문장"),),
                        self._memo(value, 7.0),
                        video_duration_seconds=10.0,
                    )

    def test_candidate_outside_video_duration_is_rejected(self) -> None:
        with self.assertRaisesRegex(TranscriptRetrievalError, "video duration"):
            retrieve_latest_block(
                (self._segment(8.0, 11.0, "범위 초과"),),
                self._memo(8.0, 9.0),
                video_duration_seconds=10.0,
            )

    @staticmethod
    def _segment(start: object, end: object, text: str) -> TranscriptSegment:
        return TranscriptSegment(
            start_seconds=start,  # type: ignore[arg-type]
            end_seconds=end,  # type: ignore[arg-type]
            text=text,
        )

    @staticmethod
    def _memo(start: object, end: object) -> EditMemo:
        return EditMemo(
            start_seconds=start,  # type: ignore[arg-type]
            end_seconds=end,  # type: ignore[arg-type]
            transcript_text="AI야 방금 장면 꼭 살려줘",
            matched_trigger="AI야",
            matched_reference="방금",
            matched_action="살려줘",
        )
