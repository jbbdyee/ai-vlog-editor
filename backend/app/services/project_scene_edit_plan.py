"""Persist an ordered user selection without modifying AI analysis records."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Project, ProjectSceneEditPlan, ProjectSceneEditPlanItem
from backend.app.services.project_scene_candidates import (
    SceneProjectNotFoundError,
    list_active_project_candidates,
)


class SceneEditPlanInvalidSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class SceneEditPlanSnapshot:
    project_id: UUID
    candidate_ids: tuple[UUID, ...]
    invalid_candidate_ids: tuple[UUID, ...]


def get_scene_edit_plan(session: Session, project_id: UUID) -> SceneEditPlanSnapshot:
    active = {row.candidate_id for row in list_active_project_candidates(session, project_id)}
    items = session.scalars(
        select(ProjectSceneEditPlanItem)
        .where(ProjectSceneEditPlanItem.project_id == project_id)
        .order_by(ProjectSceneEditPlanItem.position)
    ).all()
    ids = tuple(item.candidate_id for item in items)
    return SceneEditPlanSnapshot(project_id, ids, tuple(value for value in ids if value not in active))


def save_scene_edit_plan(
    session: Session, project_id: UUID, candidate_ids: tuple[UUID, ...]
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
        ProjectSceneEditPlanItem(project_id=project_id, position=position, candidate_id=candidate_id)
        for position, candidate_id in enumerate(candidate_ids)
    )
    session.commit()
    return SceneEditPlanSnapshot(project_id, candidate_ids, ())
