"""Persist an ordered user selection without modifying AI analysis records."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Project, ProjectSceneEditPlan, ProjectSceneEditPlanItem, SceneCandidate, SourceVideo
from backend.app.services.project_scene_candidates import (
    SceneProjectNotFoundError,
    list_active_project_candidates,
)

ClipRange = tuple[float, float]


class SceneEditPlanInvalidSelectionError(ValueError):
    pass


class SceneEditPlanInvalidRangeError(ValueError):
    pass


@dataclass(frozen=True)
class SceneEditPlanSnapshot:
    project_id: UUID
    candidate_ids: tuple[UUID, ...]
    invalid_candidate_ids: tuple[UUID, ...]
    # Same order as candidate_ids. None = render the candidate's own (unwidened) range.
    clip_ranges: tuple[ClipRange | None, ...] = ()


def _range_of(item: ProjectSceneEditPlanItem) -> ClipRange | None:
    if item.clip_start_seconds is None or item.clip_end_seconds is None:
        return None
    return float(item.clip_start_seconds), float(item.clip_end_seconds)


def get_scene_edit_plan(session: Session, project_id: UUID) -> SceneEditPlanSnapshot:
    active = {row.candidate_id for row in list_active_project_candidates(session, project_id)}
    items = session.scalars(
        select(ProjectSceneEditPlanItem)
        .where(ProjectSceneEditPlanItem.project_id == project_id)
        .order_by(ProjectSceneEditPlanItem.position)
    ).all()
    ids = tuple(item.candidate_id for item in items)
    return SceneEditPlanSnapshot(project_id, ids, tuple(value for value in ids if value not in active),
                                 tuple(_range_of(item) for item in items))


def _check_ranges(session: Session, candidate_ids: tuple[UUID, ...],
                  clip_ranges: Sequence[ClipRange | None]) -> tuple[ClipRange | None, ...]:
    if len(clip_ranges) != len(candidate_ids):
        raise SceneEditPlanInvalidRangeError("Clip ranges must match the selected scenes.")
    checked: list[ClipRange | None] = []
    for candidate_id, clip in zip(candidate_ids, clip_ranges):
        if clip is None:
            checked.append(None)
            continue
        start, end = round(float(clip[0]), 3), round(float(clip[1]), 3)
        candidate = session.get(SceneCandidate, candidate_id)
        source = session.get(SourceVideo, candidate.source_video_id) if candidate is not None else None
        duration = float(source.duration_seconds) if source is not None and source.duration_seconds is not None else None
        if (not isfinite(start) or not isfinite(end) or start < 0 or end <= start
                or duration is None or end > duration + 1e-3):
            raise SceneEditPlanInvalidRangeError("A clip range is outside its video.")
        checked.append((start, end))
    return tuple(checked)


def save_scene_edit_plan(
    session: Session, project_id: UUID, candidate_ids: tuple[UUID, ...],
    clip_ranges: Sequence[ClipRange | None] | None = None,
) -> SceneEditPlanSnapshot:
    # Lock the project row so concurrent plan writers serialize on PostgreSQL.
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise SceneProjectNotFoundError
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SceneEditPlanInvalidSelectionError("Duplicate candidate ID.")
    active = {row.candidate_id for row in list_active_project_candidates(session, project_id)}
    if any(candidate_id not in active for candidate_id in candidate_ids):
        raise SceneEditPlanInvalidSelectionError("Selection contains a candidate that is not currently active in this Project.")
    ranges = _check_ranges(session, candidate_ids, clip_ranges if clip_ranges is not None else [None] * len(candidate_ids))

    plan = session.get(ProjectSceneEditPlan, project_id)
    if plan is None:
        session.add(ProjectSceneEditPlan(project_id=project_id))
        session.flush()
    for item in session.scalars(
        select(ProjectSceneEditPlanItem).where(ProjectSceneEditPlanItem.project_id == project_id)
    ).all():
        session.delete(item)
    session.flush()
    session.add_all(
        ProjectSceneEditPlanItem(
            project_id=project_id, position=position, candidate_id=candidate_id,
            clip_start_seconds=clip[0] if clip else None, clip_end_seconds=clip[1] if clip else None,
        )
        for position, (candidate_id, clip) in enumerate(zip(candidate_ids, ranges))
    )
    session.commit()
    return SceneEditPlanSnapshot(project_id, candidate_ids, (), ranges)
