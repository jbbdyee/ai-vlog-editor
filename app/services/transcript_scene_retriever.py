from collections.abc import Iterable
from dataclasses import dataclass
import math
from numbers import Real

from app.services.candidate_generator import SceneCandidate
from app.services.memo_detector import EditMemo
from app.services.stt_service import STTResult, TranscriptSegment


DEFAULT_SILENCE_THRESHOLD_SECONDS = 2.0


class TranscriptRetrievalError(ValueError):
    """Raised when transcript blocks cannot produce a valid scene candidate."""


@dataclass(frozen=True)
class TranscriptBlock:
    block_id: str
    start_seconds: float
    end_seconds: float
    segment_ids: tuple[str, ...]
    transcript_text: str


@dataclass(frozen=True)
class TranscriptRetrievalResult:
    blocks: tuple[TranscriptBlock, ...]
    selected_block: TranscriptBlock
    candidate: SceneCandidate


def build_transcript_blocks(
    transcript: STTResult | Iterable[TranscriptSegment],
    memo: EditMemo,
    *,
    video_duration_seconds: float,
    silence_threshold_seconds: float = DEFAULT_SILENCE_THRESHOLD_SECONDS,
) -> tuple[TranscriptBlock, ...]:
    """Group complete pre-memo transcript segments by their silence gaps."""
    segments = _coerce_segments(transcript)
    video_duration = _validate_positive_number(
        video_duration_seconds, "Video duration"
    )
    threshold = _validate_non_negative_number(
        silence_threshold_seconds, "Silence threshold"
    )
    memo_start = _validate_memo(memo, video_duration)
    indexed_segments = _validate_segments(segments, video_duration)
    context = tuple(
        (segment_id, segment)
        for segment_id, segment in indexed_segments
        if segment.end_seconds <= memo_start
    )

    if not context:
        return ()

    grouped: list[list[tuple[str, TranscriptSegment]]] = []
    current_group: list[tuple[str, TranscriptSegment]] = []
    for segment_id, segment in context:
        if (
            current_group
            and segment.start_seconds - current_group[-1][1].end_seconds > threshold
        ):
            grouped.append(current_group)
            current_group = []
        current_group.append((segment_id, segment))
    grouped.append(current_group)

    return tuple(
        _make_block(block_number, group)
        for block_number, group in enumerate(grouped, start=1)
    )


def retrieve_latest_block(
    transcript: STTResult | Iterable[TranscriptSegment],
    memo: EditMemo,
    *,
    video_duration_seconds: float,
    silence_threshold_seconds: float = DEFAULT_SILENCE_THRESHOLD_SECONDS,
) -> TranscriptRetrievalResult:
    """Select the latest pre-memo utterance block as a scene candidate."""
    blocks = build_transcript_blocks(
        transcript,
        memo,
        video_duration_seconds=video_duration_seconds,
        silence_threshold_seconds=silence_threshold_seconds,
    )
    if not blocks:
        raise TranscriptRetrievalError(
            "Transcript has no complete segment before the edit memo."
        )

    selected = blocks[-1]
    candidate = SceneCandidate(
        window_seconds=selected.end_seconds - selected.start_seconds,
        start_seconds=selected.start_seconds,
        end_seconds=selected.end_seconds,
    )
    return TranscriptRetrievalResult(
        blocks=blocks,
        selected_block=selected,
        candidate=candidate,
    )


def _coerce_segments(
    transcript: STTResult | Iterable[TranscriptSegment],
) -> tuple[TranscriptSegment, ...]:
    if isinstance(transcript, STTResult):
        return transcript.segments
    try:
        return tuple(transcript)
    except TypeError as exc:
        raise TranscriptRetrievalError(
            "Transcript must be an STTResult or transcript segments."
        ) from exc


def _validate_memo(memo: EditMemo, video_duration: float) -> float:
    if not isinstance(memo, EditMemo):
        raise TranscriptRetrievalError("Memo must be an EditMemo.")
    start = _validate_non_negative_number(memo.start_seconds, "Memo start")
    end = _validate_non_negative_number(memo.end_seconds, "Memo end")
    if start >= end:
        raise TranscriptRetrievalError("Memo start must be less than memo end.")
    if end > video_duration:
        raise TranscriptRetrievalError("Memo timestamps exceed the video duration.")
    return start


def _validate_segments(
    segments: tuple[TranscriptSegment, ...], video_duration: float
) -> tuple[tuple[str, TranscriptSegment], ...]:
    validated: list[tuple[str, TranscriptSegment]] = []
    previous_end = 0.0
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, TranscriptSegment):
            raise TranscriptRetrievalError(
                "Transcript contains an invalid transcript segment."
            )
        start = _validate_non_negative_number(
            segment.start_seconds, f"Segment {index} start"
        )
        end = _validate_non_negative_number(
            segment.end_seconds, f"Segment {index} end"
        )
        if start >= end:
            raise TranscriptRetrievalError(
                f"Segment {index} start must be less than its end."
            )
        if end > video_duration:
            raise TranscriptRetrievalError(
                f"Segment {index} timestamps exceed the video duration."
            )
        if index > 1 and start < previous_end:
            raise TranscriptRetrievalError(
                "Transcript segments must be ordered and non-overlapping."
            )
        if not isinstance(segment.text, str) or not segment.text.strip():
            raise TranscriptRetrievalError(
                f"Segment {index} must contain transcript text."
            )

        validated.append((f"segment-{index:04d}", segment))
        previous_end = end
    return tuple(validated)


def _make_block(
    block_number: int,
    group: list[tuple[str, TranscriptSegment]],
) -> TranscriptBlock:
    start = group[0][1].start_seconds
    end = group[-1][1].end_seconds
    if start >= end:
        raise TranscriptRetrievalError("Transcript block must have positive duration.")
    return TranscriptBlock(
        block_id=f"block-{block_number:04d}",
        start_seconds=start,
        end_seconds=end,
        segment_ids=tuple(segment_id for segment_id, _ in group),
        transcript_text=" ".join(segment.text.strip() for _, segment in group),
    )


def _validate_positive_number(value: object, label: str) -> float:
    number = _validate_number(value, label)
    if number <= 0:
        raise TranscriptRetrievalError(f"{label} must be greater than zero.")
    return number


def _validate_non_negative_number(value: object, label: str) -> float:
    number = _validate_number(value, label)
    if number < 0:
        raise TranscriptRetrievalError(f"{label} must not be negative.")
    return number


def _validate_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TranscriptRetrievalError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise TranscriptRetrievalError(f"{label} must be a finite number.")
    return number
