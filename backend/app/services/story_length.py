"""Fit a recommended story direction to a target length.

Scene candidates are short "moments" (3-6 s). To reach a vlog length (minutes, not seconds) every chosen
moment is widened into a clip around it: the same padding is added on both sides, found by binary search so
the total lands near the target. A clip never crosses the midpoint to the next chosen moment of the same
video (so clips never overlap), never leaves the video, and is capped at MAX_CLIP_SECONDS. When widening,
clip edges that fall inside a spoken sentence move out to that sentence's edge, so speech is not cut.
Nothing here is saved; the candidates themselves are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import SourceVideo

MIN_MINUTES = 3
MAX_MINUTES = 25
RULE_RATIO = 0.25  # about a quarter of the footage
MAX_CLIP_SECONDS = 45.0
SNAP_SECONDS = 4.0
LENGTH_OPTIONS = (3, 5, 8, 10, 15, 20)


@dataclass(frozen=True)
class SourceTiming:
    duration: float | None
    speech: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class Moment:
    """One chosen scene: which video, and the original candidate range."""
    source_video_id: UUID
    start: float
    end: float


@dataclass(frozen=True)
class LengthFit:
    clips: tuple[tuple[float, float], ...]  # same order as the moments given
    total_seconds: float
    max_seconds: float  # longest total reachable with these scenes
    target_seconds: float


def load_source_timing(session: Session, project_id: UUID) -> dict[UUID, SourceTiming]:
    rows = session.scalars(select(SourceVideo).where(SourceVideo.project_id == project_id)
                           .options(selectinload(SourceVideo.transcript))).all()
    timing = {}
    for row in rows:
        speech = ()
        if row.transcript is not None:
            speech = tuple(sorted((float(s["start_seconds"]), float(s["end_seconds"])) for s in row.transcript.segments
                                  if float(s["end_seconds"]) > float(s["start_seconds"])))
        timing[row.id] = SourceTiming(float(row.duration_seconds) if row.duration_seconds is not None else None, speech)
    return timing


def footage_seconds(timing: dict[UUID, SourceTiming]) -> float:
    return sum(t.duration or 0.0 for t in timing.values())


def rule_minutes(footage: float) -> int:
    """About a quarter of the footage, between 3 and 25 minutes, never longer than the footage itself."""
    minutes = max(MIN_MINUTES, min(MAX_MINUTES, round(footage / 60 * RULE_RATIO)))
    return max(1, min(minutes, floor(footage / 60) or 1))


def accept_minutes(value: int | None, footage: float) -> bool:
    return value is not None and 1 <= value <= MAX_MINUTES and value * 60 <= footage


def _bounds(moments: Sequence[Moment], timing: dict[UUID, SourceTiming],
            walls: Sequence[tuple[float, float]] | None = None) -> list[tuple[float, float]]:
    """Each moment may grow up to the midpoint towards its chosen neighbours in the same video (and never past its
    walls, e.g. a scene Claude said to leave out)."""
    bounds: list[tuple[float, float]] = [(0.0, 0.0)] * len(moments)
    by_source: dict[UUID, list[int]] = {}
    for index, moment in enumerate(moments):
        by_source.setdefault(moment.source_video_id, []).append(index)
    for source_id, indexes in by_source.items():
        duration = timing.get(source_id, SourceTiming(None)).duration
        indexes.sort(key=lambda i: (moments[i].start, moments[i].end))
        for position, i in enumerate(indexes):
            low = 0.0
            high = duration if duration is not None else moments[i].end
            if position > 0:
                prev = moments[indexes[position - 1]]
                low = max(low, (prev.end + moments[i].start) / 2)
            if position + 1 < len(indexes):
                nxt = moments[indexes[position + 1]]
                high = min(high, (moments[i].end + nxt.start) / 2)
            if walls is not None:
                low, high = max(low, walls[i][0]), min(high, walls[i][1])
            low, high = min(low, moments[i].start), max(high, moments[i].end)
            bounds[i] = (low, high)
    return bounds


def _snap(start: float, end: float, low: float, high: float, speech: Sequence[tuple[float, float]]) -> tuple[float, float]:
    for seg_start, seg_end in speech:
        if seg_start < start < seg_end and start - seg_start <= SNAP_SECONDS and seg_start >= low:
            start = seg_start
        if seg_start < end < seg_end and seg_end - end <= SNAP_SECONDS and seg_end <= high:
            end = seg_end
    return start, end


def _clips(moments, bounds, timing, pad: float) -> list[tuple[float, float]]:
    clips = []
    for moment, (low, high) in zip(moments, bounds):
        length = moment.end - moment.start
        grow = max(0.0, min(pad, (MAX_CLIP_SECONDS - length) / 2))
        start, end = max(low, moment.start - grow), min(high, moment.end + grow)
        if grow > 0:
            start, end = _snap(start, end, low, high, timing.get(moment.source_video_id, SourceTiming(None)).speech)
        clips.append((round(start, 3), round(end, 3)))
    return clips


def _total(clips) -> float:
    return round(sum(end - start for start, end in clips), 3)


def fit_to_length(moments: Sequence[Moment], timing: dict[UUID, SourceTiming], target_seconds: float,
                  walls: Sequence[tuple[float, float]] | None = None) -> LengthFit:
    if not moments:
        return LengthFit((), 0.0, 0.0, target_seconds)
    bounds = _bounds(moments, timing, walls)
    widest = _clips(moments, bounds, timing, MAX_CLIP_SECONDS)
    best = _clips(moments, bounds, timing, 0.0)
    if _total(best) < target_seconds:
        if _total(widest) <= target_seconds:
            best = widest
        else:
            low, high = 0.0, MAX_CLIP_SECONDS
            for _ in range(40):
                middle = (low + high) / 2
                if _total(_clips(moments, bounds, timing, middle)) >= target_seconds:
                    high = middle
                else:
                    low = middle
            best = _clips(moments, bounds, timing, high)
    return LengthFit(tuple(best), _total(best), _total(widest), target_seconds)


def length_notes(fit: LengthFit) -> tuple[str, ...]:
    if fit.max_seconds < fit.target_seconds * 0.9:
        return (f"고른 장면을 최대한 넓혀도 약 {_minutes_text(fit.max_seconds)}입니다. "
                "더 길게 만들려면 장면이 더 필요합니다.",)
    if fit.total_seconds > fit.target_seconds * 1.1:
        return (f"고른 장면만으로 이미 약 {_minutes_text(fit.total_seconds)}이라 목표보다 깁니다.",)
    return ()


def _minutes_text(seconds: float) -> str:
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}분 {rest}초" if minutes else f"{rest}초"
