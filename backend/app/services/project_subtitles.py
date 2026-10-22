"""Pure planned-timeline subtitle mapping for ordered SceneCandidates.

This module does not read the database or use rendered clip PTS. Callers must
provide candidates in edit-plan order and Transcripts keyed by SourceVideo ID.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping, Sequence
from uuid import UUID

from backend.app.models import SceneCandidate, Transcript


@dataclass(frozen=True)
class SubtitleCue:
    start_seconds: Decimal
    end_seconds: Decimal
    text: str


def _time(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _interval(item: Mapping[str, object]) -> tuple[Decimal, Decimal] | None:
    start = _time(item.get("start_seconds"))
    end = _time(item.get("end_seconds"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    # Keep spoken text, but never let stored newlines/control characters or an
    # SRT timing arrow inject another cue into the output.
    return " ".join(value.replace("-->", "→").split())


def map_subtitle_cues(
    ordered_candidates: Sequence[SceneCandidate],
    transcripts_by_source: Mapping[UUID, Transcript | None],
    *,
    output_clip_durations_seconds: Sequence[object] | None = None,
) -> tuple[SubtitleCue, ...]:
    """Map stored transcript times to the *planned* concatenated clip timeline.

    Word intervals use half-open overlap: a word crossing a clip boundary is
    included, clipped to that boundary; merely touching it is excluded. Valid
    words are grouped by their original segment. With no word timestamps, only
    a wholly selected segment may use its measured segment interval and text.
    Invalid word records are skipped, never assigned inferred times.
    """
    if output_clip_durations_seconds is not None and len(output_clip_durations_seconds) != len(ordered_candidates):
        raise ValueError("Output clip durations must match the ordered candidates.")
    offset = Decimal(0)
    cues: list[SubtitleCue] = []
    for index, candidate in enumerate(ordered_candidates):
        start = _time(candidate.start_seconds)
        end = _time(candidate.end_seconds)
        if start is None or end is None or end <= start:
            raise ValueError("Selected candidate interval is invalid.")
        planned_duration = end - start
        output_duration = planned_duration if output_clip_durations_seconds is None else _time(output_clip_durations_seconds[index])
        if output_duration is None or output_duration <= 0:
            raise ValueError("Output clip duration is invalid.")
        scale = output_duration / planned_duration
        transcript = transcripts_by_source.get(candidate.source_video_id)
        if transcript is not None:
            if transcript.source_video_id != candidate.source_video_id:
                raise ValueError("Transcript belongs to another SourceVideo.")
            for segment in transcript.segments:
                if not isinstance(segment, dict):
                    continue
                segment_interval = _interval(segment)
                if segment_interval is None:
                    continue
                segment_start, segment_end = segment_interval
                if segment_start >= end or segment_end <= start:
                    continue
                words = segment.get("words")
                if isinstance(words, list) and words:
                    selected: list[tuple[Decimal, Decimal, str]] = []
                    for word in words:
                        if not isinstance(word, dict):
                            continue
                        word_interval = _interval(word)
                        if word_interval is None:
                            continue
                        word_start, word_end = word_interval
                        # Do not use a word outside its measured segment.
                        if word_start < segment_start or word_end > segment_end:
                            continue
                        word_text = word.get("text")
                        if word_start < end and word_end > start and isinstance(word_text, str):
                            selected.append((max(word_start, start), min(word_end, end), word_text))
                    if not selected:
                        continue
                    text = _clean_text("".join(part[2] for part in selected))
                    cue_start = min(part[0] for part in selected)
                    cue_end = max(part[1] for part in selected)
                elif not words and segment_start >= start and segment_end <= end:
                    text = _clean_text(segment.get("text"))
                    cue_start, cue_end = segment_start, segment_end
                else:
                    continue
                if text and cue_end > cue_start:
                    cues.append(SubtitleCue(
                        offset + (cue_start - start) * scale,
                        offset + min((cue_end - start) * scale, output_duration), text,
                    ))
        offset += output_duration
    return tuple(sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds)))


def _srt_time(seconds: Decimal) -> str:
    milliseconds = int((seconds * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def format_srt(cues: Sequence[SubtitleCue]) -> str:
    """Return UTF-8-ready SRT text, or an empty string when there are no cues."""
    blocks = []
    for cue in sorted(cues, key=lambda item: (item.start_seconds, item.end_seconds)):
        start = _time(cue.start_seconds)
        end = _time(cue.end_seconds)
        text = _clean_text(cue.text)
        if start is None or end is None or not text or _srt_time(end) <= _srt_time(start):
            continue
        blocks.append(f"{len(blocks) + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_srt(
    ordered_candidates: Sequence[SceneCandidate],
    transcripts_by_source: Mapping[UUID, Transcript | None],
) -> str:
    """Generate SRT from existing records without I/O or model inference."""
    return format_srt(map_subtitle_cues(ordered_candidates, transcripts_by_source))
