from dataclasses import dataclass, replace
from enum import Enum
import math
from numbers import Real
from pathlib import Path
import subprocess
from typing import Iterable, Mapping

from app.services.stt_service import TranscriptSegment
from app.services.transcript_scene_retriever import TranscriptBlock


CONFIG_VERSION = "scene-boundary-proposals-v0.1"
THREE_FRAME_SAMPLING_FRACTIONS = (0.10, 0.50, 0.90)
FIVE_FRAME_SAMPLING_FRACTIONS = (0.10, 0.30, 0.50, 0.70, 0.90)


class ProposalGenerationError(ValueError):
    """Raised when safe scene-boundary proposals cannot be produced."""


class ProposalKind(str, Enum):
    RAW_BLOCK = "RAW_BLOCK"
    FIXED_PADDING = "FIXED_PADDING"
    TRANSCRIPT_CONTEXT = "TRANSCRIPT_CONTEXT"
    FIRST_SEGMENT = "FIRST_SEGMENT"
    LAST_SEGMENT = "LAST_SEGMENT"
    SIGNAL_ENVELOPE = "SIGNAL_ENVELOPE"


@dataclass(frozen=True)
class ProposalConfig:
    padding_seconds: float = 2.0
    signal_connection_gap_seconds: float = 2.0
    frames_per_proposal: int = 3
    frame_sampling_fractions: tuple[float, ...] = THREE_FRAME_SAMPLING_FRACTIONS
    frame_long_edge_pixels: int = 512
    jpeg_quality: int = 3
    maximum_proposals: int = 6


DEFAULT_PROPOSAL_CONFIG = ProposalConfig()


@dataclass(frozen=True)
class BoundarySignalInterval:
    interval_id: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ProposalFrameSample:
    frame_id: str
    timestamp_seconds: float
    jpeg_bytes: bytes


@dataclass(frozen=True)
class SceneBoundaryProposal:
    proposal_id: str
    proposal_kind: ProposalKind
    start_seconds: float
    end_seconds: float
    source_block_id: str
    source_segment_ids: tuple[str, ...]
    source_audio_interval_ids: tuple[str, ...]
    source_visual_interval_ids: tuple[str, ...]
    frame_samples: tuple[ProposalFrameSample, ...]
    config_version: str = CONFIG_VERSION


def generate_scene_boundary_proposals(
    *,
    selected_block: TranscriptBlock,
    source_segments: Mapping[str, TranscriptSegment],
    video_duration_seconds: float,
    memo_start_seconds: float,
    previous_block_end_seconds: float | None,
    next_block_start_seconds: float | None,
    audio_intervals: Iterable[BoundarySignalInterval] = (),
    visual_intervals: Iterable[BoundarySignalInterval] = (),
    config: ProposalConfig = DEFAULT_PROPOSAL_CONFIG,
) -> tuple[SceneBoundaryProposal, ...]:
    """Build ordered, deduplicated proposals without using Ground Truth."""
    duration = _positive_number(video_duration_seconds, "Video duration")
    memo_start = _bounded_time(memo_start_seconds, duration, "Memo start")
    _validate_config(config)
    block_start, block_end = _validate_block(selected_block, duration, memo_start)
    search_start = _optional_boundary(
        previous_block_end_seconds, 0.0, block_start, "Previous block end"
    )
    search_end = _optional_boundary(
        next_block_start_seconds, memo_start, memo_start, "Next block start"
    )
    if search_start > block_start or search_end < block_end:
        raise ProposalGenerationError(
            "Local search range must contain the complete selected block."
        )

    selected_segments = _selected_segments(selected_block, source_segments)
    audio = _validate_intervals(audio_intervals, duration, "audio")
    visual = _validate_intervals(visual_intervals, duration, "visual")

    drafts: list[tuple[ProposalKind, float, float, tuple[str, ...], tuple[str, ...]]] = [
        (ProposalKind.RAW_BLOCK, block_start, block_end, (), ()),
        (
            ProposalKind.FIXED_PADDING,
            max(search_start, block_start - config.padding_seconds),
            min(search_end, block_end + config.padding_seconds),
            (),
            (),
        ),
        (ProposalKind.TRANSCRIPT_CONTEXT, search_start, search_end, (), ()),
        (
            ProposalKind.FIRST_SEGMENT,
            selected_segments[0][1].start_seconds,
            selected_segments[0][1].end_seconds,
            (),
            (),
        ),
        (
            ProposalKind.LAST_SEGMENT,
            selected_segments[-1][1].start_seconds,
            selected_segments[-1][1].end_seconds,
            (),
            (),
        ),
    ]

    envelope = _signal_envelope(
        block_start,
        block_end,
        search_start,
        search_end,
        audio,
        visual,
        config.signal_connection_gap_seconds,
    )
    if envelope is not None:
        drafts.append((ProposalKind.SIGNAL_ENVELOPE, *envelope))

    proposals: list[SceneBoundaryProposal] = []
    seen: set[tuple[float, float]] = set()
    for kind, start, end, audio_ids, visual_ids in drafts:
        start = max(0.0, start)
        end = min(duration, memo_start, end)
        if start >= end:
            continue
        interval_key = (round(start, 6), round(end, 6))
        if interval_key in seen:
            continue
        seen.add(interval_key)
        proposals.append(
            SceneBoundaryProposal(
                proposal_id=f"proposal-{len(proposals) + 1:03d}",
                proposal_kind=kind,
                start_seconds=start,
                end_seconds=end,
                source_block_id=selected_block.block_id,
                source_segment_ids=selected_block.segment_ids,
                source_audio_interval_ids=audio_ids,
                source_visual_interval_ids=visual_ids,
                frame_samples=(),
            )
        )
        if len(proposals) == config.maximum_proposals:
            break

    if len(proposals) < 3:
        raise ProposalGenerationError(
            "At least three distinct scene-boundary proposals are required."
        )
    return tuple(proposals)


def attach_representative_frames(
    source_video_path: str | Path,
    proposals: tuple[SceneBoundaryProposal, ...],
    *,
    config: ProposalConfig = DEFAULT_PROPOSAL_CONFIG,
    ffmpeg_executable: str = "ffmpeg",
) -> tuple[SceneBoundaryProposal, ...]:
    """Extract configured local JPEG samples per proposal with timestamp reuse."""
    _validate_config(config)
    source = Path(source_video_path)
    if not source.is_file():
        raise ProposalGenerationError(f"Source video does not exist: {source}")
    if not proposals:
        raise ProposalGenerationError("At least one proposal is required.")

    cache: dict[float, bytes] = {}
    framed: list[SceneBoundaryProposal] = []
    for proposal in proposals:
        _validate_proposal(proposal)
        duration = proposal.end_seconds - proposal.start_seconds
        timestamps = tuple(
            proposal.start_seconds + duration * fraction
            for fraction in config.frame_sampling_fractions
        )
        samples: list[ProposalFrameSample] = []
        for index, timestamp in enumerate(timestamps, start=1):
            cache_key = round(timestamp, 6)
            image = cache.get(cache_key)
            if image is None:
                image = _extract_jpeg(
                    source,
                    timestamp,
                    config=config,
                    ffmpeg_executable=ffmpeg_executable,
                )
                cache[cache_key] = image
            samples.append(
                ProposalFrameSample(
                    frame_id=f"{proposal.proposal_id}-frame-{index:02d}",
                    timestamp_seconds=timestamp,
                    jpeg_bytes=image,
                )
            )
        framed.append(replace(proposal, frame_samples=tuple(samples)))
    return tuple(framed)


def _extract_jpeg(
    source: Path,
    timestamp: float,
    *,
    config: ProposalConfig,
    ffmpeg_executable: str,
) -> bytes:
    command = [
        ffmpeg_executable,
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{timestamp:.6f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        (
            f"scale='if(gt(iw,ih),{config.frame_long_edge_pixels},-2)':"
            f"'if(gt(iw,ih),-2,{config.frame_long_edge_pixels})'"
        ),
        "-map_metadata",
        "-1",
        "-q:v",
        str(config.jpeg_quality),
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        raise ProposalGenerationError(f"Could not start FFmpeg: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProposalGenerationError(
            f"FFmpeg frame extraction failed: {detail or 'no details'}"
        )
    if not result.stdout:
        raise ProposalGenerationError("FFmpeg returned an empty JPEG frame.")
    return result.stdout


def _signal_envelope(
    block_start: float,
    block_end: float,
    search_start: float,
    search_end: float,
    audio: tuple[BoundarySignalInterval, ...],
    visual: tuple[BoundarySignalInterval, ...],
    maximum_gap: float,
) -> tuple[float, float, tuple[str, ...], tuple[str, ...]] | None:
    connected_audio = _connected_intervals(audio, block_start, block_end, maximum_gap)
    connected_visual = _connected_intervals(visual, block_start, block_end, maximum_gap)
    connected = connected_audio + connected_visual
    if not connected:
        return None
    return (
        max(search_start, min(block_start, *(interval.start_seconds for interval in connected))),
        min(search_end, max(block_end, *(interval.end_seconds for interval in connected))),
        tuple(interval.interval_id for interval in connected_audio),
        tuple(interval.interval_id for interval in connected_visual),
    )


def _connected_intervals(
    intervals: tuple[BoundarySignalInterval, ...],
    block_start: float,
    block_end: float,
    maximum_gap: float,
) -> tuple[BoundarySignalInterval, ...]:
    return tuple(
        interval
        for interval in intervals
        if interval.end_seconds >= block_start - maximum_gap
        and interval.start_seconds <= block_end + maximum_gap
    )


def _selected_segments(
    block: TranscriptBlock,
    source_segments: Mapping[str, TranscriptSegment],
) -> tuple[tuple[str, TranscriptSegment], ...]:
    if not isinstance(source_segments, Mapping):
        raise ProposalGenerationError("Source segments must be a mapping by segment ID.")
    selected: list[tuple[str, TranscriptSegment]] = []
    for segment_id in block.segment_ids:
        segment = source_segments.get(segment_id)
        if not isinstance(segment, TranscriptSegment):
            raise ProposalGenerationError(
                f"Selected block segment is missing or invalid: {segment_id}"
            )
        start = _non_negative_number(segment.start_seconds, "Segment start")
        end = _non_negative_number(segment.end_seconds, "Segment end")
        if start >= end or start < block.start_seconds or end > block.end_seconds:
            raise ProposalGenerationError(
                f"Segment {segment_id} is outside the selected block."
            )
        selected.append((segment_id, segment))
    if not selected:
        raise ProposalGenerationError("Selected block must contain source segments.")
    return tuple(selected)


def _validate_intervals(
    intervals: Iterable[BoundarySignalInterval], duration: float, label: str
) -> tuple[BoundarySignalInterval, ...]:
    try:
        values = tuple(intervals)
    except TypeError as exc:
        raise ProposalGenerationError(f"{label.title()} intervals must be iterable.") from exc
    seen: set[str] = set()
    for interval in values:
        if not isinstance(interval, BoundarySignalInterval):
            raise ProposalGenerationError(f"Invalid {label} signal interval.")
        if not interval.interval_id or interval.interval_id in seen:
            raise ProposalGenerationError(f"Invalid or duplicate {label} interval ID.")
        start = _non_negative_number(interval.start_seconds, f"{label} interval start")
        end = _non_negative_number(interval.end_seconds, f"{label} interval end")
        if start >= end or end > duration:
            raise ProposalGenerationError(f"Invalid {label} signal interval timestamp.")
        seen.add(interval.interval_id)
    return values


def _validate_block(
    block: TranscriptBlock, duration: float, memo_start: float
) -> tuple[float, float]:
    if not isinstance(block, TranscriptBlock) or not block.block_id.strip():
        raise ProposalGenerationError("Selected block is invalid.")
    start = _non_negative_number(block.start_seconds, "Block start")
    end = _non_negative_number(block.end_seconds, "Block end")
    if start >= end or end > duration or end > memo_start:
        raise ProposalGenerationError("Selected block timestamps are invalid.")
    return start, end


def _validate_proposal(proposal: SceneBoundaryProposal) -> None:
    if not isinstance(proposal, SceneBoundaryProposal):
        raise ProposalGenerationError("Invalid scene-boundary proposal.")
    start = _non_negative_number(proposal.start_seconds, "Proposal start")
    end = _non_negative_number(proposal.end_seconds, "Proposal end")
    if start >= end:
        raise ProposalGenerationError("Proposal start must be less than its end.")


def _validate_config(config: ProposalConfig) -> None:
    if not isinstance(config, ProposalConfig):
        raise ProposalGenerationError("Config must be a ProposalConfig.")
    _positive_number(config.padding_seconds, "Padding")
    _non_negative_number(config.signal_connection_gap_seconds, "Signal connection gap")
    if not isinstance(config.frame_sampling_fractions, tuple):
        raise ProposalGenerationError("Frame sampling fractions must be a tuple.")
    supported_sampling = {
        (3, THREE_FRAME_SAMPLING_FRACTIONS),
        (5, FIVE_FRAME_SAMPLING_FRACTIONS),
    }
    if (config.frames_per_proposal, config.frame_sampling_fractions) not in supported_sampling:
        raise ProposalGenerationError(
            "Frame sampling must use the supported three-frame or five-frame policy."
        )
    if isinstance(config.frame_long_edge_pixels, bool) or config.frame_long_edge_pixels <= 0:
        raise ProposalGenerationError("Frame long edge must be a positive integer.")
    if not 2 <= config.jpeg_quality <= 31:
        raise ProposalGenerationError("JPEG quality must be between 2 and 31.")
    if config.maximum_proposals != 6:
        raise ProposalGenerationError("v0.1 maximum proposal count must be six.")


def _optional_boundary(
    value: object, default: float, upper: float, label: str
) -> float:
    if value is None:
        return default
    number = _non_negative_number(value, label)
    if number > upper:
        raise ProposalGenerationError(f"{label} is outside its allowed range.")
    return number


def _bounded_time(value: object, duration: float, label: str) -> float:
    number = _non_negative_number(value, label)
    if number > duration:
        raise ProposalGenerationError(f"{label} exceeds video duration.")
    return number


def _positive_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise ProposalGenerationError(f"{label} must be greater than zero.")
    return number


def _non_negative_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise ProposalGenerationError(f"{label} must not be negative.")
    return number


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ProposalGenerationError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise ProposalGenerationError(f"{label} must be finite.")
    return number
