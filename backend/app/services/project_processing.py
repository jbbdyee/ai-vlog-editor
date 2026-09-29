from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.source_processing import (
    SourceProcessingError,
    SourceProcessingResult,
    SourceProcessingServices,
    SourceProcessingStateError,
    resume_source,
)
from backend.app.services.source_processing_state import (
    STAGE_ORDER,
    SourceStateError,
    StageVersionExpectation,
    determine_resume_plan,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import SourceStorage


DEFAULT_MAX_CONCURRENCY = 1


class ProjectProcessingError(RuntimeError):
    """Base error for a Project-level source processing run."""


class ProjectNotFoundError(ProjectProcessingError):
    """Raised before processing when the requested Project does not exist."""


class ProjectSourceOutcome(str, Enum):
    PROCESSED = "PROCESSED"
    REUSED = "REUSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REMAINING = "REMAINING"


@dataclass(frozen=True)
class ProjectSourceResult:
    source_video_id: UUID
    outcome: ProjectSourceOutcome
    processing_status: SourceVideoStatus
    attempted: bool = False
    completed_stage: ProcessingStageKind | None = None
    safe_error_code: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectProcessingSummary:
    total_sources: int
    processed_count: int
    reused_count: int
    completed_count: int
    failed_count: int
    blocked_count: int
    remaining_count: int
    progress_ratio: float


@dataclass(frozen=True)
class ProjectProcessingResult:
    project_id: UUID
    project_status: ProjectStatus
    summary: ProjectProcessingSummary
    sources: tuple[ProjectSourceResult, ...]


SourceProcessor = Callable[..., SourceProcessingResult]


def process_project(
    *,
    session_factory: sessionmaker[Session],
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    project_id: UUID,
    stt_model: Any | None = None,
    services: SourceProcessingServices | None = None,
    version_expectations: Mapping[
        ProcessingStageKind, StageVersionExpectation
    ] | None = None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    source_processor: SourceProcessor = resume_source,
) -> ProjectProcessingResult:
    """Process eligible Project sources while preserving reusable and blocked state."""
    if max_concurrency <= 0:
        raise ValueError("max_concurrency must be positive.")

    source_ids = _load_ordered_source_ids(
        session_factory=session_factory, project_id=project_id
    )
    if not source_ids:
        _set_project_status(session_factory, project_id, ProjectStatus.CREATED)
        return _empty_project_result(project_id)

    _set_project_status(session_factory, project_id, ProjectStatus.PROCESSING)
    classified = tuple(
        _classify_source(
            session_factory=session_factory,
            source_video_id=source_id,
            version_expectations=version_expectations,
        )
        for source_id in source_ids
    )
    executable = tuple(
        item.source_video_id
        for item in classified
        if item.outcome == ProjectSourceOutcome.REMAINING
        and item.processing_status in (
            SourceVideoStatus.READY,
            SourceVideoStatus.PROCESSING,
        )
    )

    processed = _process_sources(
        session_factory=session_factory,
        storage=storage,
        workspace=workspace,
        source_ids=executable,
        stt_model=stt_model,
        services=services,
        version_expectations=version_expectations,
        max_concurrency=max_concurrency,
        source_processor=source_processor,
    )
    processed_by_id = {item.source_video_id: item for item in processed}
    final_sources = tuple(
        processed_by_id.get(item.source_video_id, item) for item in classified
    )
    summary = _summarize(final_sources)
    project_status = _final_project_status(summary)
    _set_project_status(session_factory, project_id, project_status)
    return ProjectProcessingResult(
        project_id=project_id,
        project_status=project_status,
        summary=summary,
        sources=final_sources,
    )


def _load_ordered_source_ids(
    *, session_factory: sessionmaker[Session], project_id: UUID
) -> tuple[UUID, ...]:
    with session_factory() as session:
        if session.get(Project, project_id) is None:
            raise ProjectNotFoundError("The Project does not exist.")
        return tuple(
            session.scalars(
                select(SourceVideo.id)
                .where(SourceVideo.project_id == project_id)
                .order_by(SourceVideo.created_at, SourceVideo.id)
            ).all()
        )


def _classify_source(
    *,
    session_factory: sessionmaker[Session],
    source_video_id: UUID,
    version_expectations: Mapping[
        ProcessingStageKind, StageVersionExpectation
    ] | None,
) -> ProjectSourceResult:
    with session_factory() as session:
        source = session.get(SourceVideo, source_video_id)
        if source is None:
            raise ProjectProcessingError("A Project SourceVideo disappeared during selection.")
        stages = _stage_rows(session, source_video_id)
        if source.processing_status == SourceVideoStatus.FAILED:
            failed = next(
                (stage for stage in stages if stage.status == ProcessingStageStatus.FAILED),
                None,
            )
            return ProjectSourceResult(
                source_video_id=source.id,
                outcome=ProjectSourceOutcome.FAILED,
                processing_status=source.processing_status,
                completed_stage=_last_completed_stage(stages),
                safe_error_code=None if failed is None else failed.safe_error_code,
            )
        if source.processing_status == SourceVideoStatus.REGISTERED:
            return ProjectSourceResult(
                source_video_id=source.id,
                outcome=ProjectSourceOutcome.REMAINING,
                processing_status=source.processing_status,
                completed_stage=_last_completed_stage(stages),
            )

        if any(stage.status == ProcessingStageStatus.RUNNING for stage in stages):
            return ProjectSourceResult(
                source_video_id=source.id,
                outcome=ProjectSourceOutcome.BLOCKED,
                processing_status=source.processing_status,
                completed_stage=_last_completed_stage(stages),
                safe_error_code="RUNNING_STAGE_BLOCKED",
            )
        plan = determine_resume_plan(
            session=session,
            source_video_id=source.id,
            version_expectations=version_expectations,
        )
        if plan.stale_stages:
            raise ProjectProcessingError("RUNNING stage classification is inconsistent.")
        if not plan.execution_stages:
            return ProjectSourceResult(
                source_video_id=source.id,
                outcome=ProjectSourceOutcome.REUSED,
                processing_status=SourceVideoStatus.COMPLETED,
                completed_stage=ProcessingStageKind.MEMO_DETECTION,
            )
        return ProjectSourceResult(
            source_video_id=source.id,
            outcome=ProjectSourceOutcome.REMAINING,
            processing_status=source.processing_status,
            completed_stage=_last_completed_stage(stages),
        )


def _process_sources(
    *,
    session_factory: sessionmaker[Session],
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    source_ids: tuple[UUID, ...],
    stt_model: Any | None,
    services: SourceProcessingServices | None,
    version_expectations: Mapping[
        ProcessingStageKind, StageVersionExpectation
    ] | None,
    max_concurrency: int,
    source_processor: SourceProcessor,
) -> tuple[ProjectSourceResult, ...]:
    def run(source_video_id: UUID) -> ProjectSourceResult:
        with session_factory() as session:
            try:
                result = source_processor(
                    session=session,
                    storage=storage,
                    workspace=workspace,
                    source_video_id=source_video_id,
                    stt_model=stt_model,
                    services=services,
                    version_expectations=version_expectations,
                )
            except SourceProcessingStateError:
                session.rollback()
                return _blocked_source_result(session, source_video_id)
            except SourceProcessingError as error:
                session.rollback()
                return _failed_source_result(session, source_video_id, error)
            except SourceStateError:
                session.rollback()
                return _blocked_source_result(session, source_video_id)
            return ProjectSourceResult(
                source_video_id=source_video_id,
                outcome=ProjectSourceOutcome.PROCESSED,
                processing_status=result.processing_status,
                attempted=True,
                completed_stage=(
                    result.completed_stages[-1] if result.completed_stages else None
                ),
                warnings=result.warnings,
            )

    if max_concurrency == 1:
        return tuple(run(source_id) for source_id in source_ids)
    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        return tuple(executor.map(run, source_ids))


def _failed_source_result(
    session: Session, source_video_id: UUID, error: SourceProcessingError
) -> ProjectSourceResult:
    source = session.get(SourceVideo, source_video_id)
    stages = _stage_rows(session, source_video_id)
    failed = next(
        (stage for stage in stages if stage.status == ProcessingStageStatus.FAILED),
        None,
    )
    return ProjectSourceResult(
        source_video_id=source_video_id,
        outcome=ProjectSourceOutcome.FAILED,
        processing_status=(
            SourceVideoStatus.FAILED if source is None else source.processing_status
        ),
        attempted=True,
        completed_stage=_last_completed_stage(stages),
        safe_error_code=(
            failed.safe_error_code
            if failed is not None
            else getattr(error, "safe_error_code", "SOURCE_PROCESSING_FAILED")
        ),
        warnings=error.warnings,
    )


def _blocked_source_result(
    session: Session, source_video_id: UUID
) -> ProjectSourceResult:
    source = session.get(SourceVideo, source_video_id)
    stages = _stage_rows(session, source_video_id)
    return ProjectSourceResult(
        source_video_id=source_video_id,
        outcome=ProjectSourceOutcome.BLOCKED,
        processing_status=(
            SourceVideoStatus.PROCESSING
            if source is None
            else source.processing_status
        ),
        completed_stage=_last_completed_stage(stages),
        safe_error_code="SOURCE_STATE_BLOCKED",
    )


def _stage_rows(session: Session, source_video_id: UUID) -> tuple[ProcessingStage, ...]:
    return tuple(
        session.scalars(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == source_video_id
            )
        ).all()
    )


def _last_completed_stage(
    stages: tuple[ProcessingStage, ...],
) -> ProcessingStageKind | None:
    completed = {stage.stage for stage in stages if stage.status == ProcessingStageStatus.COMPLETED}
    return next((stage for stage in reversed(STAGE_ORDER) if stage in completed), None)


def _summarize(
    sources: tuple[ProjectSourceResult, ...],
) -> ProjectProcessingSummary:
    processed = sum(item.attempted for item in sources)
    reused = sum(item.outcome == ProjectSourceOutcome.REUSED for item in sources)
    completed = sum(
        item.outcome in (ProjectSourceOutcome.PROCESSED, ProjectSourceOutcome.REUSED)
        and item.processing_status == SourceVideoStatus.COMPLETED
        for item in sources
    )
    failed = sum(item.outcome == ProjectSourceOutcome.FAILED for item in sources)
    blocked = sum(item.outcome == ProjectSourceOutcome.BLOCKED for item in sources)
    remaining = sum(item.outcome == ProjectSourceOutcome.REMAINING for item in sources)
    total = len(sources)
    return ProjectProcessingSummary(
        total_sources=total,
        processed_count=processed,
        reused_count=reused,
        completed_count=completed,
        failed_count=failed,
        blocked_count=blocked,
        remaining_count=remaining,
        progress_ratio=0.0 if total == 0 else (completed + failed) / total,
    )


def _final_project_status(summary: ProjectProcessingSummary) -> ProjectStatus:
    if summary.blocked_count or summary.remaining_count:
        return ProjectStatus.PROCESSING
    if summary.failed_count == summary.total_sources:
        return ProjectStatus.FAILED
    if summary.failed_count:
        return ProjectStatus.COMPLETED_WITH_WARNINGS
    return ProjectStatus.COMPLETED


def _set_project_status(
    session_factory: sessionmaker[Session], project_id: UUID, status: ProjectStatus
) -> None:
    with session_factory() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError("The Project does not exist.")
        project.status = status
        session.commit()


def _empty_project_result(project_id: UUID) -> ProjectProcessingResult:
    summary = ProjectProcessingSummary(0, 0, 0, 0, 0, 0, 0, 0.0)
    return ProjectProcessingResult(
        project_id=project_id,
        project_status=ProjectStatus.CREATED,
        summary=summary,
        sources=(),
    )
