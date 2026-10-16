"""Process v1-completed Project sources through the existing Scene adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Project, SourceVideo, SourceVideoStatus
from backend.app.services.source_autonomous_adapter import (
    SourceAutonomousResult,
    process_source_autonomous,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import SourceStorage


class ProjectSceneNotFoundError(LookupError):
    pass


class SceneSourceOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED_V1_INCOMPLETE = "SKIPPED_V1_INCOMPLETE"


@dataclass(frozen=True)
class ProjectSceneSourceResult:
    source_video_id: UUID
    outcome: SceneSourceOutcome
    candidate_count: int = 0
    safe_error_code: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSceneProcessingResult:
    project_id: UUID
    sources: tuple[ProjectSceneSourceResult, ...]


SourceSceneProcessor = Callable[..., SourceAutonomousResult]


def process_project_scenes(
    *,
    session_factory: sessionmaker[Session],
    storage: SourceStorage,
    scene_workspace: LocalProcessingWorkspace,
    project_id: UUID,
    on_source_result: Callable[[ProjectSceneSourceResult], None] | None = None,
    source_processor: SourceSceneProcessor | None = None,
) -> ProjectSceneProcessingResult:
    """Run sources independently, without changing Project/v1 processing status.

    WorkItem/Attempt persistence and reuse remain the responsibility of the
    source adapter. A failure never triggers an automatic retry.
    """
    with session_factory() as session:
        if session.get(Project, project_id) is None:
            raise ProjectSceneNotFoundError("Project was not found.")
        source_rows = tuple(
            session.execute(
                select(SourceVideo.id, SourceVideo.processing_status)
                .where(SourceVideo.project_id == project_id)
                .order_by(SourceVideo.created_at, SourceVideo.id)
            ).all()
        )

    processor = source_processor or process_source_autonomous
    results: list[ProjectSceneSourceResult] = []
    for source_id, v1_status in source_rows:
        if v1_status is not SourceVideoStatus.COMPLETED:
            item = ProjectSceneSourceResult(
                source_id, SceneSourceOutcome.SKIPPED_V1_INCOMPLETE,
                safe_error_code="V1_ANALYSIS_INCOMPLETE",
            )
        else:
            with session_factory() as session:
                try:
                    scene = processor(
                        session=session,
                        storage=storage,
                        scene_workspace=scene_workspace,
                        source_video_id=source_id,
                    )
                    item = _source_result(scene)
                except Exception:
                    session.rollback()
                    item = ProjectSceneSourceResult(
                        source_id, SceneSourceOutcome.FAILED,
                        safe_error_code="SCENE_SOURCE_FAILED",
                    )
        results.append(item)
        if on_source_result is not None:
            on_source_result(item)
    return ProjectSceneProcessingResult(project_id, tuple(results))


def _source_result(scene: SourceAutonomousResult) -> ProjectSceneSourceResult:
    return ProjectSceneSourceResult(
        source_video_id=scene.source_video_id,
        outcome=SceneSourceOutcome(scene.status.value),
        candidate_count=0 if scene.discovery is None else len(scene.discovery.candidate_ids),
        safe_error_code=scene.safe_error_code,
        warnings=scene.warnings,
    )
