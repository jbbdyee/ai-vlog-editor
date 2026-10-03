from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.services.event_grouping import EventGroupingResult, process_event_grouping
from backend.app.services.scene_fingerprints import canonical_fingerprint
from backend.app.services.scene_processing_state import (
    SceneResumePlan,
    SceneWorkSpec,
    active_candidate_ids,
    determine_scene_resume_plan,
)


@dataclass(frozen=True)
class SourceSceneProcessingSummary:
    source_video_id: UUID
    reused_work_count: int
    executed_work_count: int
    failed_work_count: int
    blocked_work_count: int
    invalidated_work_count: int
    candidate_result_changed: bool
    changed_candidate_ids: tuple[UUID, ...]
    reason_counts: dict[str, int]


@dataclass(frozen=True)
class ProjectEventUpdateSummary:
    project_id: UUID
    executed: bool
    incremental: bool
    focus_candidate_count: int
    result: EventGroupingResult | None


class SourceSceneCoordinator:
    """Thin planner/executor boundary; discovery algorithms remain in their services."""

    def plan(
        self, session: Session, specs: Iterable[SceneWorkSpec]
    ) -> SceneResumePlan:
        return determine_scene_resume_plan(session, tuple(specs))

    def execute(
        self,
        session: Session,
        *,
        project_id: UUID,
        source_video_id: UUID,
        specs: Iterable[SceneWorkSpec],
        executor: Callable[[SceneWorkSpec], None],
    ) -> SourceSceneProcessingSummary:
        before = active_candidate_ids(session, project_id)
        plan = self.plan(session, specs)
        failed = 0
        executed = 0
        for spec in plan.execution_specs:
            try:
                executor(spec)
                executed += 1
            except Exception:
                failed += 1
        session.expire_all()
        after = active_candidate_ids(session, project_id)
        changed = tuple(sorted(set(before) ^ set(after), key=lambda value: value.hex))
        return SourceSceneProcessingSummary(
            source_video_id=source_video_id,
            reused_work_count=len(plan.reusable_work_items),
            executed_work_count=executed,
            failed_work_count=failed,
            blocked_work_count=len(plan.blocked_work_items),
            invalidated_work_count=len(plan.invalid_work_items),
            candidate_result_changed=canonical_fingerprint(before)
            != canonical_fingerprint(after),
            changed_candidate_ids=changed,
            reason_counts=plan.reason_counts,
        )


class ProjectEventCoordinator:
    def update(
        self,
        session: Session,
        project_id: UUID,
        *,
        changed_candidate_ids: Iterable[UUID] = (),
        force_full: bool = False,
    ) -> ProjectEventUpdateSummary:
        changed = tuple(sorted(set(changed_candidate_ids), key=lambda value: value.hex))
        if not changed and not force_full:
            return ProjectEventUpdateSummary(project_id, False, True, 0, None)
        result = process_event_grouping(
            session,
            project_id,
            focus_candidate_ids=None if force_full else changed,
        )
        return ProjectEventUpdateSummary(
            project_id, True, not force_full, len(changed), result
        )
