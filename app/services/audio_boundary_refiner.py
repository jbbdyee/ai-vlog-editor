from array import array
from dataclasses import dataclass
from enum import Enum
import math
from numbers import Real
from pathlib import Path
from statistics import median
import sys
import wave

from app.services.candidate_generator import SceneCandidate
from app.services.transcript_scene_retriever import TranscriptBlock


CONFIG_VERSION = "audio-boundary-v0.1"


class AudioBoundaryRefinementError(ValueError):
    """Raised when WAV activity cannot produce a valid refined boundary."""


class BoundaryEvidence(str, Enum):
    SPEECH_ACTIVITY = "SPEECH_ACTIVITY"
    ENERGY_ONSET = "ENERGY_ONSET"
    ENERGY_OFFSET = "ENERGY_OFFSET"
    NO_REFINEMENT = "NO_REFINEMENT"


@dataclass(frozen=True)
class AudioBoundaryConfig:
    frame_duration_ms: int = 20
    energy_margin_db: float = 10.0
    minimum_activity_duration_seconds: float = 0.08
    maximum_quiet_gap_seconds: float = 0.25


DEFAULT_AUDIO_BOUNDARY_CONFIG = AudioBoundaryConfig()


@dataclass(frozen=True)
class AudioActivityInterval:
    start_seconds: float
    end_seconds: float
    peak_dbfs: float
    mean_dbfs: float
    overlaps_selected_block: bool


@dataclass(frozen=True)
class RefinedSceneCandidate:
    source_block_id: str
    original_start_seconds: float
    original_end_seconds: float
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    start_adjustment_seconds: float
    end_adjustment_seconds: float
    start_evidence: BoundaryEvidence
    end_evidence: BoundaryEvidence
    refinement_method: str
    config_version: str

    def to_scene_candidate(self) -> SceneCandidate:
        return SceneCandidate(
            window_seconds=self.duration_seconds,
            start_seconds=self.start_seconds,
            end_seconds=self.end_seconds,
        )


@dataclass(frozen=True)
class AudioBoundaryRefinementResult:
    search_start_seconds: float
    search_end_seconds: float
    noise_floor_dbfs: float
    activity_threshold_dbfs: float
    activity_intervals: tuple[AudioActivityInterval, ...]
    selected_activity_interval: AudioActivityInterval
    candidate: RefinedSceneCandidate


def refine_scene_boundary(
    source_audio_path: str | Path,
    *,
    video_duration_seconds: float,
    selected_block: TranscriptBlock,
    previous_block_end_seconds: float | None,
    next_block_start_seconds: float | None,
    memo_start_seconds: float,
    config: AudioBoundaryConfig = DEFAULT_AUDIO_BOUNDARY_CONFIG,
) -> AudioBoundaryRefinementResult:
    """Refine a selected transcript block using local PCM16 WAV activity."""
    duration = _positive_number(video_duration_seconds, "Video duration")
    memo_start = _bounded_time(memo_start_seconds, duration, "Memo start")
    _validate_config(config)
    block_start, block_end = _validate_block(selected_block, duration, memo_start)

    search_start = 0.0
    if previous_block_end_seconds is not None:
        search_start = _bounded_time(
            previous_block_end_seconds, duration, "Previous block end"
        )
        if search_start > block_start:
            raise AudioBoundaryRefinementError(
                "Previous block end must not exceed selected block start."
            )

    search_end = memo_start
    if next_block_start_seconds is not None:
        next_start = _bounded_time(
            next_block_start_seconds, duration, "Next block start"
        )
        if next_start < block_end:
            raise AudioBoundaryRefinementError(
                "Next block start must not precede selected block end."
            )
        search_end = min(search_end, next_start)

    search_start = max(0.0, min(search_start, block_start))
    search_end = min(duration, max(search_end, block_end))
    if search_start >= search_end:
        raise AudioBoundaryRefinementError("Local search range must have positive duration.")

    frame_dbfs = _read_frame_dbfs(
        Path(source_audio_path), search_start, search_end, config.frame_duration_ms
    )
    if not frame_dbfs:
        raise AudioBoundaryRefinementError("Local search range contains no audio frames.")

    levels = sorted(
        level if math.isfinite(level) else -96.0 for _, _, level in frame_dbfs
    )
    quiet_half = levels[: max(1, math.ceil(len(levels) / 2))]
    noise_floor = median(quiet_half)
    threshold = min(0.0, noise_floor + config.energy_margin_db)
    active_frames = tuple(
        frame for frame in frame_dbfs if frame[2] >= threshold
    )
    intervals = _build_activity_intervals(
        active_frames,
        selected_start=block_start,
        selected_end=block_end,
        minimum_duration=config.minimum_activity_duration_seconds,
        maximum_gap=config.maximum_quiet_gap_seconds,
    )
    overlapping = tuple(interval for interval in intervals if interval.overlaps_selected_block)
    if not overlapping:
        raise AudioBoundaryRefinementError(
            "No valid audio activity episode overlaps the selected transcript block."
        )

    selected_interval = max(
        overlapping,
        key=lambda interval: (
            min(interval.end_seconds, block_end)
            - max(interval.start_seconds, block_start),
            interval.end_seconds - interval.start_seconds,
            -interval.start_seconds,
        ),
    )
    refined_start = max(0.0, selected_interval.start_seconds)
    refined_end = min(duration, selected_interval.end_seconds)
    if refined_start >= refined_end:
        raise AudioBoundaryRefinementError("Refined candidate must have positive duration.")

    candidate = RefinedSceneCandidate(
        source_block_id=selected_block.block_id,
        original_start_seconds=block_start,
        original_end_seconds=block_end,
        start_seconds=refined_start,
        end_seconds=refined_end,
        duration_seconds=refined_end - refined_start,
        start_adjustment_seconds=refined_start - block_start,
        end_adjustment_seconds=refined_end - block_end,
        start_evidence=_start_evidence(refined_start, block_start, refined_end, block_end),
        end_evidence=_end_evidence(refined_start, block_start, refined_end, block_end),
        refinement_method="LOCAL_MEDIAN_RMS_ACTIVITY",
        config_version=CONFIG_VERSION,
    )
    return AudioBoundaryRefinementResult(
        search_start_seconds=search_start,
        search_end_seconds=search_end,
        noise_floor_dbfs=noise_floor,
        activity_threshold_dbfs=threshold,
        activity_intervals=intervals,
        selected_activity_interval=selected_interval,
        candidate=candidate,
    )


def _read_frame_dbfs(
    path: Path, search_start: float, search_end: float, frame_duration_ms: int
) -> tuple[tuple[float, float, float], ...]:
    if not path.is_file():
        raise AudioBoundaryRefinementError(f"Audio file does not exist: {path}")
    try:
        with wave.open(str(path), "rb") as wav_file:
            if (
                wav_file.getnchannels() != 1
                or wav_file.getsampwidth() != 2
                or wav_file.getcomptype() != "NONE"
            ):
                raise AudioBoundaryRefinementError(
                    "Audio must be uncompressed mono PCM16 WAV."
                )
            sample_rate = wav_file.getframerate()
            if sample_rate != 16_000:
                raise AudioBoundaryRefinementError("Audio sample rate must be 16000 Hz.")
            frame_samples = max(1, round(sample_rate * frame_duration_ms / 1000))
            first_sample = min(wav_file.getnframes(), math.floor(search_start * sample_rate))
            last_sample = min(wav_file.getnframes(), math.ceil(search_end * sample_rate))
            wav_file.setpos(first_sample)
            frames: list[tuple[float, float, float]] = []
            position = first_sample
            while position < last_sample:
                count = min(frame_samples, last_sample - position)
                raw = wav_file.readframes(count)
                if len(raw) != count * 2:
                    raise AudioBoundaryRefinementError("WAV sample data is truncated.")
                samples = array("h")
                samples.frombytes(raw)
                if sys.byteorder == "big":
                    samples.byteswap()
                rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
                level = -math.inf if rms == 0 else 20.0 * math.log10(rms / 32768.0)
                start = position / sample_rate
                end = (position + count) / sample_rate
                frames.append((start, end, level))
                position += count
            return tuple(frames)
    except AudioBoundaryRefinementError:
        raise
    except (OSError, EOFError, wave.Error) as exc:
        raise AudioBoundaryRefinementError(f"Could not read PCM WAV: {path.name}") from exc


def _build_activity_intervals(
    active_frames: tuple[tuple[float, float, float], ...],
    *,
    selected_start: float,
    selected_end: float,
    minimum_duration: float,
    maximum_gap: float,
) -> tuple[AudioActivityInterval, ...]:
    if not active_frames:
        return ()
    groups: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] = []
    for frame in active_frames:
        if current and frame[0] - current[-1][1] > maximum_gap:
            groups.append(current)
            current = []
        current.append(frame)
    groups.append(current)

    intervals = []
    for group in groups:
        start, end = group[0][0], group[-1][1]
        if end - start + 1e-12 < minimum_duration:
            continue
        levels = [frame[2] for frame in group]
        intervals.append(
            AudioActivityInterval(
                start_seconds=start,
                end_seconds=end,
                peak_dbfs=max(levels),
                mean_dbfs=sum(levels) / len(levels),
                overlaps_selected_block=start < selected_end and end > selected_start,
            )
        )
    return tuple(intervals)


def _validate_config(config: object) -> None:
    if not isinstance(config, AudioBoundaryConfig):
        raise AudioBoundaryRefinementError("Config must be an AudioBoundaryConfig.")
    if isinstance(config.frame_duration_ms, bool) or not isinstance(
        config.frame_duration_ms, int
    ) or config.frame_duration_ms <= 0:
        raise AudioBoundaryRefinementError("Frame duration must be a positive integer.")
    if config.frame_duration_ms > 1000:
        raise AudioBoundaryRefinementError("Frame duration must not exceed 1000 ms.")
    margin = _positive_number(config.energy_margin_db, "Energy margin")
    minimum = _positive_number(
        config.minimum_activity_duration_seconds, "Minimum activity duration"
    )
    gap = _non_negative_number(config.maximum_quiet_gap_seconds, "Maximum quiet gap")
    if minimum > 10 or gap > 10 or margin > 100:
        raise AudioBoundaryRefinementError("Config values exceed supported baseline limits.")


def _validate_block(
    block: object, video_duration: float, memo_start: float
) -> tuple[float, float]:
    if not isinstance(block, TranscriptBlock):
        raise AudioBoundaryRefinementError("Selected block must be a TranscriptBlock.")
    if not isinstance(block.block_id, str) or not block.block_id.strip():
        raise AudioBoundaryRefinementError("Selected block ID must not be empty.")
    start = _bounded_time(block.start_seconds, video_duration, "Selected block start")
    end = _bounded_time(block.end_seconds, video_duration, "Selected block end")
    if start >= end:
        raise AudioBoundaryRefinementError("Selected block must have positive duration.")
    if end > memo_start:
        raise AudioBoundaryRefinementError("Selected block must end before the memo.")
    return start, end


def _start_evidence(
    start: float, original_start: float, end: float, original_end: float
) -> BoundaryEvidence:
    if math.isclose(start, original_start, abs_tol=1e-9):
        return (
            BoundaryEvidence.NO_REFINEMENT
            if math.isclose(end, original_end, abs_tol=1e-9)
            else BoundaryEvidence.SPEECH_ACTIVITY
        )
    return BoundaryEvidence.ENERGY_ONSET


def _end_evidence(
    start: float, original_start: float, end: float, original_end: float
) -> BoundaryEvidence:
    if math.isclose(end, original_end, abs_tol=1e-9):
        return (
            BoundaryEvidence.NO_REFINEMENT
            if math.isclose(start, original_start, abs_tol=1e-9)
            else BoundaryEvidence.SPEECH_ACTIVITY
        )
    return BoundaryEvidence.ENERGY_OFFSET


def _bounded_time(value: object, duration: float, label: str) -> float:
    number = _non_negative_number(value, label)
    if number > duration:
        raise AudioBoundaryRefinementError(f"{label} exceeds video duration.")
    return number


def _positive_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise AudioBoundaryRefinementError(f"{label} must be greater than zero.")
    return number


def _non_negative_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise AudioBoundaryRefinementError(f"{label} must not be negative.")
    return number


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise AudioBoundaryRefinementError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise AudioBoundaryRefinementError(f"{label} must be finite.")
    return number
