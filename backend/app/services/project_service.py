from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.source_processing_state import STAGE_ORDER, determine_resume_plan


class ProjectServiceError(RuntimeError):
    """Base error for Project persistence use cases."""


class ProjectNotFoundError(ProjectServiceError):
    """Raised when a valid Project UUID does not exist."""


@dataclass(frozen=True)
class ProjectRecord:
    project_id: UUID
    name: str
    status: ProjectStatus
    target_duration_seconds: float | None
    split_policy: EpisodeSplitPolicy
    instruction: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StageSummary:
    stage: ProcessingStageKind
    status: ProcessingStageStatus
    safe_error_code: str | None


@dataclass(frozen=True)
class SourceSummary:
    source_video_id: UUID
    original_filename: str
    processing_status: SourceVideoStatus
    stages: tuple[StageSummary, ...]


@dataclass(frozen=True)
class ProcessingSummary:
    total_sources: int
    completed_count: int
    failed_count: int
    blocked_count: int
    remaining_count: int
    progress_ratio: float


@dataclass(frozen=True)
class ProjectSnapshot:
    project: ProjectRecord
    summary: ProcessingSummary
    sources: tuple[SourceSummary, ...]


def create_project(
    *,
    session: Session,
    name: str,
    split_policy: EpisodeSplitPolicy,
    target_duration_seconds: float | None = None,
    instruction: str | None = None,
) -> ProjectRecord:
    project = Project(
        name=name,
        split_policy=split_policy,
        target_duration_seconds=target_duration_seconds,
        instruction=instruction,
        status=ProjectStatus.CREATED,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return _project_record(project)


def get_project_snapshot(
    *, session: Session, project_id: UUID
) -> ProjectSnapshot:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError("The Project does not exist.")

    sources = tuple(
        session.scalars(
            select(SourceVideo)
            .where(SourceVideo.project_id == project_id)
            .order_by(SourceVideo.created_at, SourceVideo.id)
        ).all()
    )
    stage_rows = session.scalars(
        select(ProcessingStage)
        .join(SourceVideo)
        .where(SourceVideo.project_id == project_id)
    ).all()
    stages_by_source: dict[UUID, list[ProcessingStage]] = {
        source.id: [] for source in sources
    }
    for stage in stage_rows:
        stages_by_source[stage.source_video_id].append(stage)

    completed = failed = blocked = remaining = 0
    source_summaries: list[SourceSummary] = []
    for source in sources:
        stages = stages_by_source[source.id]
        has_running = any(
            stage.status == ProcessingStageStatus.RUNNING for stage in stages
        )
        if has_running:
            blocked += 1
        elif source.processing_status == SourceVideoStatus.FAILED:
            failed += 1
        elif source.processing_status == SourceVideoStatus.COMPLETED:
            plan = determine_resume_plan(session=session, source_video_id=source.id)
            if not plan.execution_stages and not plan.stale_stages:
                completed += 1
            else:
                remaining += 1
        else:
            remaining += 1
        source_summaries.append(
            SourceSummary(
                source_video_id=source.id,
                original_filename=source.original_filename,
                processing_status=source.processing_status,
                stages=tuple(
                    StageSummary(stage.stage, stage.status, stage.safe_error_code)
                    for stage in sorted(
                        stages, key=lambda item: STAGE_ORDER.index(item.stage)
                    )
                ),
            )
        )

    total = len(sources)
    summary = ProcessingSummary(
        total_sources=total,
        completed_count=completed,
        failed_count=failed,
        blocked_count=blocked,
        remaining_count=remaining,
        progress_ratio=0.0 if total == 0 else (completed + failed) / total,
    )
    return ProjectSnapshot(
        project=_project_record(project),
        summary=summary,
        sources=tuple(source_summaries),
    )


def _project_record(project: Project) -> ProjectRecord:
    return ProjectRecord(
        project_id=project.id,
        name=project.name,
        status=project.status,
        target_duration_seconds=(
            None
            if project.target_duration_seconds is None
            else float(project.target_duration_seconds)
        ),
        split_policy=project.split_policy,
        instruction=project.instruction,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
