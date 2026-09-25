import subprocess
import unittest
from unittest.mock import patch

from app.services.scene_boundary_proposals import (
    BoundarySignalInterval,
    ProposalConfig,
    ProposalGenerationError,
    ProposalKind,
    attach_representative_frames,
    generate_scene_boundary_proposals,
)
from app.services.stt_service import TranscriptSegment
from app.services.transcript_scene_retriever import TranscriptBlock


class SceneBoundaryProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = TranscriptBlock(
            block_id="block-0001",
            start_seconds=3.0,
            end_seconds=9.0,
            segment_ids=("segment-0001", "segment-0002", "segment-0003"),
            transcript_text="도입 물건이 떨어졌네 반응",
        )
        self.segments = {
            "segment-0001": TranscriptSegment(3.0, 5.0, "도입", ()),
            "segment-0002": TranscriptSegment(6.0, 7.5, "물건이 떨어졌네", ()),
            "segment-0003": TranscriptSegment(8.0, 9.0, "반응", ()),
        }

    def generate(self, **overrides):
        values = {
            "selected_block": self.block,
            "source_segments": self.segments,
            "video_duration_seconds": 20.0,
            "memo_start_seconds": 15.0,
            "previous_block_end_seconds": 1.0,
            "next_block_start_seconds": 12.0,
            "audio_intervals": (),
            "visual_intervals": (),
        }
        values.update(overrides)
        return generate_scene_boundary_proposals(**values)

    def test_generates_ordered_explainable_proposals(self) -> None:
        proposals = self.generate(
            visual_intervals=(BoundarySignalInterval("visual-1", 1.5, 3.5),)
        )

        self.assertEqual(len(proposals), 6)
        self.assertEqual(
            [proposal.proposal_kind for proposal in proposals],
            [
                ProposalKind.RAW_BLOCK,
                ProposalKind.FIXED_PADDING,
                ProposalKind.TRANSCRIPT_CONTEXT,
                ProposalKind.FIRST_SEGMENT,
                ProposalKind.LAST_SEGMENT,
                ProposalKind.SIGNAL_ENVELOPE,
            ],
        )
        self.assertEqual(proposals[0].proposal_id, "proposal-001")
        self.assertEqual(proposals[-1].proposal_id, "proposal-006")
        self.assertEqual(
            proposals[-1].source_visual_interval_ids, ("visual-1",)
        )

    def test_duplicate_intervals_are_removed(self) -> None:
        single_segment = TranscriptBlock(
            "block-0001", 3.0, 9.0, ("segment-0001",), "한 문장"
        )
        proposals = self.generate(
            selected_block=single_segment,
            source_segments={
                "segment-0001": TranscriptSegment(3.0, 9.0, "한 문장", ())
            },
        )

        intervals = {(item.start_seconds, item.end_seconds) for item in proposals}
        self.assertEqual(len(intervals), len(proposals))
        self.assertEqual(len(proposals), 3)

    def test_maximum_six_is_enforced(self) -> None:
        proposals = self.generate(
            audio_intervals=(BoundarySignalInterval("audio-1", 2.5, 3.2),),
            visual_intervals=(BoundarySignalInterval("visual-1", 8.8, 10.0),),
        )
        self.assertLessEqual(len(proposals), 6)

    @patch("app.services.scene_boundary_proposals.subprocess.run")
    def test_extracts_three_frames_and_builds_manifest(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess([], 0, b"jpeg", b"")
        proposals = self.generate()[:3]

        with patch("pathlib.Path.is_file", return_value=True):
            framed = attach_representative_frames("source.mov", proposals)

        self.assertEqual(len(framed), 3)
        for proposal in framed:
            self.assertEqual(len(proposal.frame_samples), 3)
            self.assertEqual(
                [round(frame.timestamp_seconds, 6) for frame in proposal.frame_samples],
                [
                    round(proposal.start_seconds + (proposal.end_seconds - proposal.start_seconds) * part, 6)
                    for part in (0.1, 0.5, 0.9)
                ],
            )
            self.assertTrue(
                all(frame.frame_id.startswith(proposal.proposal_id) for frame in proposal.frame_samples)
            )

    def test_rejects_invalid_config_numbers(self) -> None:
        with self.assertRaises(ProposalGenerationError):
            self.generate(config=ProposalConfig(padding_seconds=float("nan")))

    def test_last_selected_block_uses_memo_start_as_search_end(self) -> None:
        proposals = self.generate(next_block_start_seconds=None)

        context = next(
            item
            for item in proposals
            if item.proposal_kind is ProposalKind.TRANSCRIPT_CONTEXT
        )
        self.assertEqual(context.start_seconds, 1.0)
        self.assertEqual(context.end_seconds, 15.0)
        self.assertGreaterEqual(len(proposals), 3)
        self.assertTrue(
            all(item.start_seconds < item.end_seconds for item in proposals)
        )

    def test_clipping_drops_invalid_draft_without_weakening_minimum(self) -> None:
        proposals = self.generate(
            next_block_start_seconds=None,
            memo_start_seconds=9.0,
        )

        self.assertGreaterEqual(len(proposals), 3)
        self.assertTrue(all(item.end_seconds <= 9.0 for item in proposals))

    def test_eval_02_shape_stays_at_six_proposals(self) -> None:
        proposals = self.generate(
            selected_block=TranscriptBlock(
                "block-0001",
                3.04,
                10.96,
                ("segment-0001", "segment-0002"),
                "2번째 테스트 영상입니다 아 뭐야 떨어졌네",
            ),
            source_segments={
                "segment-0001": TranscriptSegment(
                    3.04, 5.86, "2번째 테스트 영상입니다", ()
                ),
                "segment-0002": TranscriptSegment(
                    5.86, 10.96, "아 뭐야 떨어졌네", ()
                ),
            },
            video_duration_seconds=40.05,
            memo_start_seconds=32.84,
            previous_block_end_seconds=None,
            next_block_start_seconds=14.0,
            audio_intervals=(BoundarySignalInterval("audio-1", 9.4, 11.16),),
        )

        self.assertEqual(len(proposals), 6)
        self.assertEqual(
            (proposals[2].start_seconds, proposals[2].end_seconds),
            (0.0, 14.0),
        )

    def test_last_block_shapes_from_failed_evals_generate_valid_proposals(self) -> None:
        fixtures = (
            ("eval_01", 12.70, 13.18, 9.90, 15.80),
            ("eval_03", 7.52, 22.26, 4.28, 25.94),
            ("eval_04", 8.08, 10.56, 3.94, 30.14),
            ("eval_05", 22.48, 24.90, 18.20, 26.84),
        )
        for test_id, start, end, previous_end, memo_start in fixtures:
            with self.subTest(test_id=test_id):
                block = TranscriptBlock(
                    "block-last", start, end, ("segment-last",), "마지막 발화"
                )
                proposals = self.generate(
                    selected_block=block,
                    source_segments={
                        "segment-last": TranscriptSegment(
                            start, end, "마지막 발화", ()
                        )
                    },
                    video_duration_seconds=max(memo_start + 1.0, end + 1.0),
                    memo_start_seconds=memo_start,
                    previous_block_end_seconds=previous_end,
                    next_block_start_seconds=None,
                )
                self.assertGreaterEqual(len(proposals), 3)
                context = next(
                    item
                    for item in proposals
                    if item.proposal_kind is ProposalKind.TRANSCRIPT_CONTEXT
                )
                self.assertEqual(context.end_seconds, memo_start)
                self.assertTrue(
                    all(
                        0.0 <= item.start_seconds < item.end_seconds <= memo_start
                        for item in proposals
                    )
                )


if __name__ == "__main__":
    unittest.main()
