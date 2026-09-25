from dataclasses import dataclass
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from app.services.scene_boundary_proposals import SceneBoundaryProposal


CONTACT_SHEET_CONFIG_VERSION = "proposal-contact-sheet-v0.2"
CONTACT_SHEET_LAYOUT = "horizontal_3"


class ProposalContactSheetError(ValueError):
    """Raised when a proposal contact sheet cannot be built safely."""


@dataclass(frozen=True)
class ProposalContactSheet:
    proposal_id: str
    jpeg_bytes: bytes
    source_frame_ids: tuple[str, str, str]
    source_frame_timestamps: tuple[float, float, float]
    layout: str = CONTACT_SHEET_LAYOUT
    config_version: str = CONTACT_SHEET_CONFIG_VERSION


def build_proposal_contact_sheets(
    proposals: tuple[SceneBoundaryProposal, ...],
    *,
    ffmpeg_executable: str = "ffmpeg",
) -> tuple[ProposalContactSheet, ...]:
    """Combine each proposal's existing 10/50/90% JPEGs into one image."""
    if not isinstance(proposals, tuple) or not proposals:
        raise ProposalContactSheetError("At least one proposal is required.")
    return tuple(
        _build_contact_sheet(proposal, ffmpeg_executable=ffmpeg_executable)
        for proposal in proposals
    )


def validate_proposal_contact_sheets(
    proposals: tuple[SceneBoundaryProposal, ...],
    contact_sheets: tuple[ProposalContactSheet, ...],
) -> None:
    if not isinstance(contact_sheets, tuple) or len(contact_sheets) != len(proposals):
        raise ProposalContactSheetError(
            "Each proposal requires exactly one contact sheet."
        )
    for proposal, sheet in zip(proposals, contact_sheets):
        _validate_contact_sheet_manifest(proposal, sheet)


def _build_contact_sheet(
    proposal: SceneBoundaryProposal, *, ffmpeg_executable: str
) -> ProposalContactSheet:
    frame_ids, timestamps, frame_bytes = _validated_source_frames(proposal)
    with TemporaryDirectory(prefix="proposal-contact-sheet-") as temporary_directory:
        directory = Path(temporary_directory)
        paths: list[Path] = []
        for index, image in enumerate(frame_bytes, start=1):
            path = directory / f"frame-{index:02d}.jpg"
            path.write_bytes(image)
            paths.append(path)
        command = [ffmpeg_executable, "-v", "error", "-nostdin"]
        for path in paths:
            command.extend(("-i", str(path)))
        command.extend(
            (
                "-filter_complex",
                "[0:v][1:v][2:v]hstack=inputs=3[out]",
                "-map",
                "[out]",
                "-frames:v",
                "1",
                "-map_metadata",
                "-1",
                "-q:v",
                "3",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            )
        )
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except OSError as exc:
            raise ProposalContactSheetError(
                f"Could not start FFmpeg for contact sheet: {exc}"
            ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProposalContactSheetError(
            f"FFmpeg contact sheet generation failed: {detail or 'no details'}"
        )
    if not result.stdout:
        raise ProposalContactSheetError("FFmpeg returned an empty contact sheet.")
    return ProposalContactSheet(
        proposal_id=proposal.proposal_id,
        jpeg_bytes=result.stdout,
        source_frame_ids=frame_ids,
        source_frame_timestamps=timestamps,
    )


def _validate_contact_sheet_manifest(
    proposal: SceneBoundaryProposal, sheet: ProposalContactSheet
) -> None:
    if not isinstance(sheet, ProposalContactSheet):
        raise ProposalContactSheetError("Invalid contact sheet manifest.")
    expected_ids, expected_timestamps, _ = _validated_source_frames(proposal)
    if sheet.proposal_id != proposal.proposal_id:
        raise ProposalContactSheetError("Contact sheet proposal ID does not match.")
    if sheet.source_frame_ids != expected_ids:
        raise ProposalContactSheetError("Contact sheet source frame order is invalid.")
    if sheet.source_frame_timestamps != expected_timestamps:
        raise ProposalContactSheetError(
            "Contact sheet source timestamps do not match proposal frames."
        )
    if sheet.layout != CONTACT_SHEET_LAYOUT:
        raise ProposalContactSheetError("Contact sheet layout is invalid.")
    if not isinstance(sheet.jpeg_bytes, bytes) or not sheet.jpeg_bytes:
        raise ProposalContactSheetError("Contact sheet JPEG must not be empty.")


def _validated_source_frames(
    proposal: SceneBoundaryProposal,
) -> tuple[tuple[str, str, str], tuple[float, float, float], tuple[bytes, bytes, bytes]]:
    if not isinstance(proposal, SceneBoundaryProposal):
        raise ProposalContactSheetError("Invalid scene boundary proposal.")
    if len(proposal.frame_samples) != 3:
        raise ProposalContactSheetError(
            "Contact sheet requires exactly three source frames."
        )
    duration = proposal.end_seconds - proposal.start_seconds
    expected_timestamps = tuple(
        proposal.start_seconds + duration * fraction
        for fraction in (0.10, 0.50, 0.90)
    )
    expected_ids = tuple(
        f"{proposal.proposal_id}-frame-{index:02d}" for index in range(1, 4)
    )
    actual_ids = tuple(frame.frame_id for frame in proposal.frame_samples)
    actual_timestamps = tuple(
        frame.timestamp_seconds for frame in proposal.frame_samples
    )
    if actual_ids != expected_ids:
        raise ProposalContactSheetError("Source frame IDs are missing or out of order.")
    if any(
        abs(actual - expected) > 1e-6
        for actual, expected in zip(actual_timestamps, expected_timestamps)
    ):
        raise ProposalContactSheetError(
            "Source frame timestamps must match 10/50/90% sampling."
        )
    images = tuple(frame.jpeg_bytes for frame in proposal.frame_samples)
    if any(not isinstance(image, bytes) or not image for image in images):
        raise ProposalContactSheetError("Source frame JPEG must not be empty.")
    return actual_ids, actual_timestamps, images
