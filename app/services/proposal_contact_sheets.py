from dataclasses import dataclass
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from app.services.scene_boundary_proposals import SceneBoundaryProposal


CONTACT_SHEET_CONFIG_VERSION = "proposal-contact-sheet-v0.2"
CONTACT_SHEET_LAYOUT = "horizontal_3"
FIVE_FRAME_CONTACT_SHEET_CONFIG_VERSION = "contact-sheet-v0.2-5frame"
FIVE_FRAME_CONTACT_SHEET_LAYOUT = "horizontal_5"
THREE_FRAME_SAMPLING_FRACTIONS = (0.10, 0.50, 0.90)
FIVE_FRAME_SAMPLING_FRACTIONS = (0.10, 0.30, 0.50, 0.70, 0.90)


class ProposalContactSheetError(ValueError):
    """Raised when a proposal contact sheet cannot be built safely."""


@dataclass(frozen=True)
class ProposalContactSheetConfig:
    sampling_fractions: tuple[float, ...]
    layout: str
    config_version: str


DEFAULT_CONTACT_SHEET_CONFIG = ProposalContactSheetConfig(
    THREE_FRAME_SAMPLING_FRACTIONS,
    CONTACT_SHEET_LAYOUT,
    CONTACT_SHEET_CONFIG_VERSION,
)
FIVE_FRAME_CONTACT_SHEET_CONFIG = ProposalContactSheetConfig(
    FIVE_FRAME_SAMPLING_FRACTIONS,
    FIVE_FRAME_CONTACT_SHEET_LAYOUT,
    FIVE_FRAME_CONTACT_SHEET_CONFIG_VERSION,
)


@dataclass(frozen=True)
class ProposalContactSheet:
    proposal_id: str
    jpeg_bytes: bytes
    source_frame_ids: tuple[str, ...]
    source_frame_timestamps: tuple[float, ...]
    sampling_fractions: tuple[float, ...] = THREE_FRAME_SAMPLING_FRACTIONS
    layout: str = CONTACT_SHEET_LAYOUT
    config_version: str = CONTACT_SHEET_CONFIG_VERSION


def build_proposal_contact_sheets(
    proposals: tuple[SceneBoundaryProposal, ...],
    *,
    ffmpeg_executable: str = "ffmpeg",
    config: ProposalContactSheetConfig = DEFAULT_CONTACT_SHEET_CONFIG,
) -> tuple[ProposalContactSheet, ...]:
    """Combine each proposal's configured JPEG samples into one image."""
    if not isinstance(proposals, tuple) or not proposals:
        raise ProposalContactSheetError("At least one proposal is required.")
    _validate_config(config)
    return tuple(
        _build_contact_sheet(
            proposal, ffmpeg_executable=ffmpeg_executable, config=config
        )
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
    manifest_configs = {
        (sheet.config_version, sheet.layout, sheet.sampling_fractions)
        for sheet in contact_sheets
        if isinstance(sheet, ProposalContactSheet)
    }
    if len(manifest_configs) != 1:
        raise ProposalContactSheetError(
            "Contact sheets must use one consistent manifest config."
        )
    for proposal, sheet in zip(proposals, contact_sheets):
        _validate_contact_sheet_manifest(proposal, sheet)


def _build_contact_sheet(
    proposal: SceneBoundaryProposal,
    *,
    ffmpeg_executable: str,
    config: ProposalContactSheetConfig,
) -> ProposalContactSheet:
    frame_ids, timestamps, frame_bytes = _validated_source_frames(proposal, config)
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
        input_labels = "".join(f"[{index}:v]" for index in range(len(paths)))
        command.extend(
            (
                "-filter_complex",
                f"{input_labels}hstack=inputs={len(paths)}[out]",
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
        sampling_fractions=config.sampling_fractions,
        layout=config.layout,
        config_version=config.config_version,
    )


def _validate_contact_sheet_manifest(
    proposal: SceneBoundaryProposal, sheet: ProposalContactSheet
) -> None:
    if not isinstance(sheet, ProposalContactSheet):
        raise ProposalContactSheetError("Invalid contact sheet manifest.")
    config = _config_for_sheet(sheet)
    expected_ids, expected_timestamps, _ = _validated_source_frames(proposal, config)
    if sheet.proposal_id != proposal.proposal_id:
        raise ProposalContactSheetError("Contact sheet proposal ID does not match.")
    if sheet.source_frame_ids != expected_ids:
        raise ProposalContactSheetError("Contact sheet source frame order is invalid.")
    if sheet.source_frame_timestamps != expected_timestamps:
        raise ProposalContactSheetError(
            "Contact sheet source timestamps do not match proposal frames."
        )
    if sheet.sampling_fractions != config.sampling_fractions:
        raise ProposalContactSheetError("Contact sheet sampling fractions are invalid.")
    if sheet.layout != config.layout:
        raise ProposalContactSheetError("Contact sheet layout is invalid.")
    if sheet.config_version != config.config_version:
        raise ProposalContactSheetError("Contact sheet config version is invalid.")
    if not isinstance(sheet.jpeg_bytes, bytes) or not sheet.jpeg_bytes:
        raise ProposalContactSheetError("Contact sheet JPEG must not be empty.")


def _validated_source_frames(
    proposal: SceneBoundaryProposal,
    config: ProposalContactSheetConfig,
) -> tuple[tuple[str, ...], tuple[float, ...], tuple[bytes, ...]]:
    if not isinstance(proposal, SceneBoundaryProposal):
        raise ProposalContactSheetError("Invalid scene boundary proposal.")
    frame_count = len(config.sampling_fractions)
    if len(proposal.frame_samples) != frame_count:
        raise ProposalContactSheetError(
            f"Contact sheet requires exactly {frame_count} source frames."
        )
    duration = proposal.end_seconds - proposal.start_seconds
    expected_timestamps = tuple(
        proposal.start_seconds + duration * fraction
        for fraction in config.sampling_fractions
    )
    expected_ids = tuple(
        f"{proposal.proposal_id}-frame-{index:02d}"
        for index in range(1, frame_count + 1)
    )
    actual_ids = tuple(frame.frame_id for frame in proposal.frame_samples)
    if len(set(actual_ids)) != len(actual_ids):
        raise ProposalContactSheetError("Source frame IDs must be unique.")
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
            "Source frame timestamps must match configured sampling fractions."
        )
    images = tuple(frame.jpeg_bytes for frame in proposal.frame_samples)
    if any(not isinstance(image, bytes) or not image for image in images):
        raise ProposalContactSheetError("Source frame JPEG must not be empty.")
    return actual_ids, actual_timestamps, images


def _config_for_sheet(sheet: ProposalContactSheet) -> ProposalContactSheetConfig:
    for config in (DEFAULT_CONTACT_SHEET_CONFIG, FIVE_FRAME_CONTACT_SHEET_CONFIG):
        if (
            sheet.config_version == config.config_version
            and sheet.layout == config.layout
            and sheet.sampling_fractions == config.sampling_fractions
        ):
            return config
    raise ProposalContactSheetError("Unsupported contact sheet manifest config.")


def _validate_config(config: ProposalContactSheetConfig) -> None:
    if config not in (DEFAULT_CONTACT_SHEET_CONFIG, FIVE_FRAME_CONTACT_SHEET_CONFIG):
        raise ProposalContactSheetError("Unsupported contact sheet config.")
