from dataclasses import replace
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from app.services.proposal_contact_sheets import (
    ProposalContactSheetError,
    build_proposal_contact_sheets,
    validate_proposal_contact_sheets,
)
from app.services.scene_boundary_proposals import (
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)


def proposal(number: int = 1) -> SceneBoundaryProposal:
    proposal_id = f"proposal-{number:03d}"
    return SceneBoundaryProposal(
        proposal_id=proposal_id,
        proposal_kind=ProposalKind.RAW_BLOCK,
        start_seconds=10.0,
        end_seconds=20.0,
        source_block_id="block-0001",
        source_segment_ids=("segment-0001",),
        source_audio_interval_ids=(),
        source_visual_interval_ids=(),
        frame_samples=tuple(
            ProposalFrameSample(
                frame_id=f"{proposal_id}-frame-{index:02d}",
                timestamp_seconds=timestamp,
                jpeg_bytes=image,
            )
            for index, (timestamp, image) in enumerate(
                ((11.0, b"early"), (15.0, b"middle"), (19.0, b"late")),
                start=1,
            )
        ),
    )


class ProposalContactSheetTests(unittest.TestCase):
    @patch("app.services.proposal_contact_sheets.subprocess.run")
    def test_combines_three_frames_in_early_middle_late_order(self, run_mock) -> None:
        captured: list[bytes] = []

        def run(command, **kwargs):
            input_paths = [command[index + 1] for index, item in enumerate(command) if item == "-i"]
            captured.extend(Path(path).read_bytes() for path in input_paths)
            return subprocess.CompletedProcess(command, 0, b"contact-sheet", b"")

        run_mock.side_effect = run
        sheet = build_proposal_contact_sheets((proposal(),))[0]

        self.assertEqual(captured, [b"early", b"middle", b"late"])
        self.assertEqual(sheet.proposal_id, "proposal-001")
        self.assertEqual(
            sheet.source_frame_ids,
            (
                "proposal-001-frame-01",
                "proposal-001-frame-02",
                "proposal-001-frame-03",
            ),
        )
        self.assertEqual(sheet.source_frame_timestamps, (11.0, 15.0, 19.0))
        self.assertEqual(sheet.layout, "horizontal_3")
        self.assertEqual(sheet.jpeg_bytes, b"contact-sheet")
        self.assertIn("[0:v][1:v][2:v]hstack=inputs=3[out]", run_mock.call_args.args[0])

    @patch("app.services.proposal_contact_sheets.subprocess.run")
    def test_six_proposals_create_at_most_six_images(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess([], 0, b"sheet", b"")
        sheets = build_proposal_contact_sheets(
            tuple(proposal(index) for index in range(1, 7))
        )
        self.assertEqual(len(sheets), 6)
        self.assertEqual(run_mock.call_count, 6)

    def test_rejects_missing_or_reordered_frames(self) -> None:
        original = proposal()
        with self.assertRaises(ProposalContactSheetError):
            build_proposal_contact_sheets(
                (replace(original, frame_samples=original.frame_samples[:2]),)
            )
        with self.assertRaises(ProposalContactSheetError):
            build_proposal_contact_sheets(
                (replace(original, frame_samples=tuple(reversed(original.frame_samples))),)
            )

    def test_rejects_wrong_timestamp_and_empty_contact_sheet(self) -> None:
        original = proposal()
        wrong_frame = replace(original.frame_samples[0], timestamp_seconds=10.5)
        with self.assertRaises(ProposalContactSheetError):
            build_proposal_contact_sheets(
                (replace(original, frame_samples=(wrong_frame, *original.frame_samples[1:])),)
            )

        valid_sheet = replace(
            self._sheet(original),
            jpeg_bytes=b"",
        )
        with self.assertRaises(ProposalContactSheetError):
            validate_proposal_contact_sheets((original,), (valid_sheet,))

    @staticmethod
    def _sheet(original: SceneBoundaryProposal):
        from app.services.proposal_contact_sheets import ProposalContactSheet

        return ProposalContactSheet(
            proposal_id=original.proposal_id,
            jpeg_bytes=b"sheet",
            source_frame_ids=tuple(frame.frame_id for frame in original.frame_samples),
            source_frame_timestamps=tuple(
                frame.timestamp_seconds for frame in original.frame_samples
            ),
        )


if __name__ == "__main__":
    unittest.main()
