from dataclasses import dataclass
from enum import Enum
import math
from numbers import Real
from pathlib import Path
from statistics import median
import subprocess

from app.services.candidate_generator import SceneCandidate
from app.services.transcript_scene_retriever import TranscriptBlock


CONFIG_VERSION = "visual-motion-v0.1"


class VisualBoundaryStatus(str, Enum):
    REFINED = "REFINED"
    NO_SIGNAL = "NO_SIGNAL"
    AMBIGUOUS_SIGNAL = "AMBIGUOUS_SIGNAL"
    INVALID_INPUT = "INVALID_INPUT"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class VisualSignalType(str, Enum):
    MOTION_ONSET = "MOTION_ONSET"
    MOTION_PEAK = "MOTION_PEAK"
    MOTION_OFFSET = "MOTION_OFFSET"


@dataclass(frozen=True)
class VisualBoundaryConfig:
    sample_fps: int = 5
    frame_width: int = 160
    smoothing_window_frames: int = 3
    threshold_mad_multiplier: float = 3.0
    minimum_motion_duration_seconds: float = 0.4
    maximum_quiet_gap_seconds: float = 0.6


DEFAULT_VISUAL_BOUNDARY_CONFIG = VisualBoundaryConfig()


@dataclass(frozen=True)
class VisualBoundarySignal:
    timestamp_seconds: float
    score: float
    signal_type: VisualSignalType


@dataclass(frozen=True)
class VisualActivityInterval:
    start_seconds: float
    end_seconds: float
    peak_score: float
    mean_score: float
    overlaps_selected_block: bool


@dataclass(frozen=True)
class VisualBoundaryRefinementResult:
    status: VisualBoundaryStatus
    source_block_id: str
    search_start_seconds: float | None
    search_end_seconds: float | None
    original_start_seconds: float | None
    original_end_seconds: float | None
    refined_start_seconds: float | None
    refined_end_seconds: float | None
    sample_fps: int
    frame_width: int
    frame_height: int | None
    motion_score_count: int
    motion_score_min: float | None
    motion_score_max: float | None
    motion_score_mean: float | None
    motion_score_median: float | None
    median_absolute_deviation: float | None
    activity_threshold: float | None
    visual_signals: tuple[VisualBoundarySignal, ...]
    activity_intervals: tuple[VisualActivityInterval, ...]
    selected_interval: VisualActivityInterval | None
    failure_reason: str | None
    refinement_method: str
    config_version: str

    def to_scene_candidate(self) -> SceneCandidate:
        if (
            self.status is not VisualBoundaryStatus.REFINED
            or self.refined_start_seconds is None
            or self.refined_end_seconds is None
        ):
            raise ValueError("Only a REFINED visual result can become a SceneCandidate.")
        return SceneCandidate(
            window_seconds=self.refined_end_seconds - self.refined_start_seconds,
            start_seconds=self.refined_start_seconds,
            end_seconds=self.refined_end_seconds,
        )


@dataclass(frozen=True)
class _MotionScore:
    timestamp_seconds: float
    score: float


@dataclass(frozen=True)
class _DecodedFrames:
    width: int
    height: int
    frames: tuple[bytes, ...]


def refine_visual_boundary(
    source_video_path: str | Path,
    *,
    video_duration_seconds: float,
    selected_block: TranscriptBlock,
    previous_block_end_seconds: float | None,
    next_block_start_seconds: float | None,
    memo_start_seconds: float,
    config: VisualBoundaryConfig = DEFAULT_VISUAL_BOUNDARY_CONFIG,
    ffmpeg_executable: str = "ffmpeg",
) -> VisualBoundaryRefinementResult:
    """Refine one selected block using deterministic local visual motion."""
    source_path = Path(source_video_path)
    block_id = _safe_block_id(selected_block)
    base = _empty_result(block_id, config)

    try:
        duration = _positive_number(video_duration_seconds, "Video duration")
        _validate_config(config)
        if not source_path.is_file():
            raise ValueError(f"Source video does not exist: {source_path}")
        memo_start = _bounded_time(memo_start_seconds, duration, "Memo start")
        block_start, block_end = _validate_block(
            selected_block, duration, memo_start
        )
        search_start, search_end = _search_range(
            duration=duration,
            block_start=block_start,
            block_end=block_end,
            previous_block_end=previous_block_end_seconds,
            next_block_start=next_block_start_seconds,
            memo_start=memo_start,
        )
    except ValueError as exc:
        return _replace_result(
            base,
            status=VisualBoundaryStatus.INVALID_INPUT,
            failure_reason=str(exc),
        )

    prepared = _replace_result(
        base,
        search_start_seconds=search_start,
        search_end_seconds=search_end,
        original_start_seconds=block_start,
        original_end_seconds=block_end,
    )
    try:
        decoded = _extract_pgm_frames(
            source_path,
            search_start=search_start,
            search_end=search_end,
            config=config,
            ffmpeg_executable=ffmpeg_executable,
        )
        raw_scores = _motion_scores(
            decoded.frames,
            search_start=search_start,
            sample_fps=config.sample_fps,
        )
        smoothed_scores = _median_smooth(
            raw_scores, config.smoothing_window_frames
        )
        score_values = tuple(score.score for score in smoothed_scores)
        score_median = median(score_values)
        median_absolute_deviation = median(
            abs(score - score_median) for score in score_values
        )
        raw_threshold = (
            score_median
            + config.threshold_mad_multiplier * median_absolute_deviation
        )
        activity_threshold = (
            math.nextafter(score_median, math.inf)
            if median_absolute_deviation == 0.0
            else raw_threshold
        )
        active_scores = tuple(
            score for score in smoothed_scores if score.score >= activity_threshold
        )
        intervals, signals = _build_motion_intervals(
            active_scores,
            block_start=block_start,
            block_end=block_end,
            sample_fps=config.sample_fps,
            minimum_duration=config.minimum_motion_duration_seconds,
            maximum_gap=config.maximum_quiet_gap_seconds,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _replace_result(
            prepared,
            status=VisualBoundaryStatus.PROCESSING_FAILED,
            failure_reason=str(exc),
        )

    analyzed = _replace_result(
        prepared,
        frame_height=decoded.height,
        motion_score_count=len(score_values),
        motion_score_min=min(score_values),
        motion_score_max=max(score_values),
        motion_score_mean=sum(score_values) / len(score_values),
        motion_score_median=score_median,
        median_absolute_deviation=median_absolute_deviation,
        activity_threshold=activity_threshold,
        visual_signals=signals,
        activity_intervals=intervals,
    )
    connected = tuple(interval for interval in intervals if interval.overlaps_selected_block)
    if not connected:
        return _replace_result(
            analyzed,
            status=VisualBoundaryStatus.NO_SIGNAL,
            failure_reason="No motion episode connects to the selected block.",
        )
    if len(connected) > 1:
        return _replace_result(
            analyzed,
            status=VisualBoundaryStatus.AMBIGUOUS_SIGNAL,
            failure_reason=(
                "Multiple motion episodes connect to the selected block; "
                "v0.1 does not choose among them."
            ),
        )

    selected = connected[0]
    refined_start = max(0.0, selected.start_seconds)
    refined_end = min(duration, selected.end_seconds)
    if refined_start >= refined_end:
        return _replace_result(
            analyzed,
            status=VisualBoundaryStatus.PROCESSING_FAILED,
            failure_reason="Visual refinement produced an invalid interval.",
        )
    return _replace_result(
        analyzed,
        status=VisualBoundaryStatus.REFINED,
        refined_start_seconds=refined_start,
        refined_end_seconds=refined_end,
        selected_interval=selected,
    )


def _extract_pgm_frames(
    source_path: Path,
    *,
    search_start: float,
    search_end: float,
    config: VisualBoundaryConfig,
    ffmpeg_executable: str,
) -> _DecodedFrames:
    command = [
        ffmpeg_executable,
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{search_start:.6f}",
        "-t",
        f"{search_end - search_start:.6f}",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps={config.sample_fps},scale={config.frame_width}:-2:flags=bicubic,format=gray",
        "-f",
        "image2pipe",
        "-vcodec",
        "pgm",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start FFmpeg: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"FFmpeg visual frame extraction failed: "
            f"{detail or 'No error details were returned.'}"
        )
    return _parse_pgm_stream(result.stdout, expected_width=config.frame_width)


def _parse_pgm_stream(data: bytes, *, expected_width: int) -> _DecodedFrames:
    frames: list[bytes] = []
    width: int | None = None
    height: int | None = None
    position = 0
    while position < len(data):
        magic, position = _pgm_token(data, position)
        if magic != b"P5":
            raise ValueError("FFmpeg returned a malformed grayscale frame stream.")
        raw_width, position = _pgm_token(data, position)
        raw_height, position = _pgm_token(data, position)
        raw_max, position = _pgm_token(data, position)
        try:
            frame_width = int(raw_width)
            frame_height = int(raw_height)
            max_value = int(raw_max)
        except ValueError as exc:
            raise ValueError("FFmpeg returned invalid PGM frame metadata.") from exc
        if frame_width != expected_width or frame_height <= 0 or max_value != 255:
            raise ValueError("FFmpeg returned unexpected PGM frame dimensions.")
        if position >= len(data) or data[position] not in b" \t\r\n":
            raise ValueError("FFmpeg returned a malformed PGM header.")
        if data[position : position + 2] == b"\r\n":
            position += 2
        else:
            position += 1
        frame_size = frame_width * frame_height
        frame_end = position + frame_size
        if frame_end > len(data):
            raise ValueError("FFmpeg returned a truncated frame byte stream.")
        if width is not None and (frame_width != width or frame_height != height):
            raise ValueError("FFmpeg frame dimensions changed within the stream.")
        width, height = frame_width, frame_height
        frames.append(data[position:frame_end])
        position = frame_end

    if width is None or height is None or len(frames) < 2:
        raise ValueError("Visual motion analysis requires at least two frames.")
    return _DecodedFrames(width=width, height=height, frames=tuple(frames))


def _pgm_token(data: bytes, position: int) -> tuple[bytes, int]:
    while position < len(data):
        if data[position] in b" \t\r\n":
            position += 1
            continue
        if data[position] == ord("#"):
            newline = data.find(b"\n", position)
            if newline < 0:
                raise ValueError("FFmpeg returned a malformed PGM comment.")
            position = newline + 1
            continue
        break
    start = position
    while position < len(data) and data[position] not in b" \t\r\n#":
        position += 1
    if start == position:
        raise ValueError("FFmpeg returned a malformed PGM header.")
    return data[start:position], position


def _motion_scores(
    frames: tuple[bytes, ...], *, search_start: float, sample_fps: int
) -> tuple[_MotionScore, ...]:
    scores = []
    for index in range(1, len(frames)):
        previous, current = frames[index - 1], frames[index]
        if len(previous) != len(current) or not current:
            raise ValueError("Frame byte lengths are inconsistent.")
        difference = sum(abs(current_pixel - previous_pixel) for previous_pixel, current_pixel in zip(previous, current))
        scores.append(
            _MotionScore(
                timestamp_seconds=search_start + index / sample_fps,
                score=difference / (len(current) * 255.0),
            )
        )
    if not scores:
        raise ValueError("Visual motion analysis requires at least two frames.")
    return tuple(scores)


def _median_smooth(
    scores: tuple[_MotionScore, ...], window_frames: int
) -> tuple[_MotionScore, ...]:
    half_window = window_frames // 2
    return tuple(
        _MotionScore(
            timestamp_seconds=score.timestamp_seconds,
            score=median(
                neighbor.score
                for neighbor in scores[
                    max(0, index - half_window) : min(
                        len(scores), index + half_window + 1
                    )
                ]
            ),
        )
        for index, score in enumerate(scores)
    )


def _build_motion_intervals(
    active_scores: tuple[_MotionScore, ...],
    *,
    block_start: float,
    block_end: float,
    sample_fps: int,
    minimum_duration: float,
    maximum_gap: float,
) -> tuple[tuple[VisualActivityInterval, ...], tuple[VisualBoundarySignal, ...]]:
    if not active_scores:
        return (), ()
    frame_duration = 1.0 / sample_fps
    groups: list[list[_MotionScore]] = []
    current: list[_MotionScore] = []
    for score in active_scores:
        score_start = score.timestamp_seconds - frame_duration
        current_end = current[-1].timestamp_seconds if current else None
        if (
            current_end is not None
            and score_start - current_end > maximum_gap + 1e-12
        ):
            groups.append(current)
            current = []
        current.append(score)
    groups.append(current)

    intervals = []
    signals = []
    for group in groups:
        start = group[0].timestamp_seconds - frame_duration
        end = group[-1].timestamp_seconds
        if end - start + 1e-12 < minimum_duration:
            continue
        peak = max(group, key=lambda score: (score.score, -score.timestamp_seconds))
        interval = VisualActivityInterval(
            start_seconds=start,
            end_seconds=end,
            peak_score=peak.score,
            mean_score=sum(score.score for score in group) / len(group),
            overlaps_selected_block=start < block_end and end > block_start,
        )
        intervals.append(interval)
        signals.extend(
            (
                VisualBoundarySignal(start, group[0].score, VisualSignalType.MOTION_ONSET),
                VisualBoundarySignal(peak.timestamp_seconds, peak.score, VisualSignalType.MOTION_PEAK),
                VisualBoundarySignal(end, group[-1].score, VisualSignalType.MOTION_OFFSET),
            )
        )
    return tuple(intervals), tuple(signals)


def _search_range(
    *,
    duration: float,
    block_start: float,
    block_end: float,
    previous_block_end: float | None,
    next_block_start: float | None,
    memo_start: float,
) -> tuple[float, float]:
    search_start = 0.0
    if previous_block_end is not None:
        search_start = _bounded_time(previous_block_end, duration, "Previous block end")
        if search_start > block_start:
            raise ValueError("Previous block end must not exceed selected block start.")
    search_end = min(memo_start, duration)
    if next_block_start is not None:
        next_start = _bounded_time(next_block_start, duration, "Next block start")
        if next_start < block_end:
            raise ValueError("Next block start must not precede selected block end.")
        search_end = min(search_end, next_start)
    if search_start > block_start or search_end < block_end or search_start >= search_end:
        raise ValueError("Search range must contain the complete selected block.")
    return search_start, search_end


def _validate_config(config: object) -> None:
    if not isinstance(config, VisualBoundaryConfig):
        raise ValueError("Config must be a VisualBoundaryConfig.")
    for value, label in (
        (config.sample_fps, "Sample FPS"),
        (config.frame_width, "Frame width"),
        (config.smoothing_window_frames, "Smoothing window"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{label} must be a positive integer.")
    if config.smoothing_window_frames % 2 == 0:
        raise ValueError("Smoothing window must be odd.")
    _positive_number(config.threshold_mad_multiplier, "Threshold MAD multiplier")
    _positive_number(config.minimum_motion_duration_seconds, "Minimum motion duration")
    _non_negative_number(config.maximum_quiet_gap_seconds, "Maximum quiet gap")


def _validate_block(
    block: object, duration: float, memo_start: float
) -> tuple[float, float]:
    if not isinstance(block, TranscriptBlock):
        raise ValueError("Selected block must be a TranscriptBlock.")
    if not isinstance(block.block_id, str) or not block.block_id.strip():
        raise ValueError("Selected block ID must not be empty.")
    start = _bounded_time(block.start_seconds, duration, "Selected block start")
    end = _bounded_time(block.end_seconds, duration, "Selected block end")
    if start >= end:
        raise ValueError("Selected block must have positive duration.")
    if end > memo_start:
        raise ValueError("Selected block must end before the memo.")
    return start, end


def _safe_block_id(block: object) -> str:
    if isinstance(block, TranscriptBlock) and isinstance(block.block_id, str):
        return block.block_id
    return ""


def _empty_result(
    block_id: str, config: object
) -> VisualBoundaryRefinementResult:
    sample_fps = config.sample_fps if isinstance(config, VisualBoundaryConfig) else 0
    frame_width = config.frame_width if isinstance(config, VisualBoundaryConfig) else 0
    return VisualBoundaryRefinementResult(
        status=VisualBoundaryStatus.INVALID_INPUT,
        source_block_id=block_id,
        search_start_seconds=None,
        search_end_seconds=None,
        original_start_seconds=None,
        original_end_seconds=None,
        refined_start_seconds=None,
        refined_end_seconds=None,
        sample_fps=sample_fps,
        frame_width=frame_width,
        frame_height=None,
        motion_score_count=0,
        motion_score_min=None,
        motion_score_max=None,
        motion_score_mean=None,
        motion_score_median=None,
        median_absolute_deviation=None,
        activity_threshold=None,
        visual_signals=(),
        activity_intervals=(),
        selected_interval=None,
        failure_reason=None,
        refinement_method="LOCAL_GRAYSCALE_FRAME_DIFFERENCE",
        config_version=CONFIG_VERSION,
    )


def _replace_result(
    result: VisualBoundaryRefinementResult, **changes: object
) -> VisualBoundaryRefinementResult:
    values = result.__dict__ | changes
    return VisualBoundaryRefinementResult(**values)  # type: ignore[arg-type]


def _bounded_time(value: object, duration: float, label: str) -> float:
    number = _non_negative_number(value, label)
    if number > duration:
        raise ValueError(f"{label} exceeds video duration.")
    return number


def _positive_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return number


def _non_negative_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise ValueError(f"{label} must not be negative.")
    return number


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number
