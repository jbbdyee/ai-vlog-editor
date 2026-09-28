from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.storage.source_storage import SourceStorage


class SourceIngestionError(RuntimeError):
    """Base error for a Product SourceVideo ingestion attempt."""


class ProjectNotFoundError(SourceIngestionError):
    """Raised before storage when the target Project does not exist."""


class SourceIngestionPersistenceError(SourceIngestionError):
    """Raised when DB persistence fails after original storage succeeds."""

    def __init__(self, message: str, *, cleanup_warning: str | None = None) -> None:
        super().__init__(message)
        self.cleanup_warning = cleanup_warning


@dataclass(frozen=True)
class IngestedSource:
    source_video_id: UUID
    project_id: UUID
    original_filename: str
    resource_reference: str
    fingerprint: str
    fingerprint_algorithm: str
    processing_status: SourceVideoStatus
    stage_statuses: tuple[tuple[ProcessingStageKind, ProcessingStageStatus], ...]
    duplicate_fingerprint_in_project: bool


def ingest_source(
    *,
    session: Session,
    storage: SourceStorage,
    project_id: UUID,
    file_object: BinaryIO,
    original_filename: str | None,
    content_type: str | None,
) -> IngestedSource:
    """Validate, store and register one original video without starting analysis."""
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError("The target Project does not exist.")

    stored_source = storage.store(
        project_id=project_id,
        file_object=file_object,
        original_filename=original_filename,
        content_type=content_type,
    )

    try:
        duplicate_exists = (
            session.execute(
                select(SourceVideo.id)
                .where(
                    SourceVideo.project_id == project_id,
                    SourceVideo.fingerprint == stored_source.fingerprint,
                    SourceVideo.fingerprint_algorithm
                    == stored_source.fingerprint_algorithm,
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

        source_video = SourceVideo(
            project_id=project_id,
            original_filename=stored_source.original_filename,
            storage_reference=stored_source.resource_reference,
            fingerprint=stored_source.fingerprint,
            fingerprint_algorithm=stored_source.fingerprint_algorithm,
            processing_status=SourceVideoStatus.READY,
        )
        stages = tuple(
            ProcessingStage(
                source_video=source_video,
                stage=stage,
                status=ProcessingStageStatus.PENDING,
            )
            for stage in ProcessingStageKind
        )
        session.add(source_video)
        session.add_all(stages)
        session.commit()
    except Exception as error:
        try:
            session.rollback()
        except Exception:
            pass

        cleanup_warning = None
        try:
            storage.delete(stored_source.resource_reference)
        except Exception:
            cleanup_warning = "Stored original source cleanup failed."

        raise SourceIngestionPersistenceError(
            "SourceVideo persistence failed after original storage.",
            cleanup_warning=cleanup_warning,
        ) from error

    return IngestedSource(
        source_video_id=source_video.id,
        project_id=project_id,
        original_filename=stored_source.original_filename,
        resource_reference=stored_source.resource_reference,
        fingerprint=stored_source.fingerprint,
        fingerprint_algorithm=stored_source.fingerprint_algorithm,
        processing_status=source_video.processing_status,
        stage_statuses=tuple((stage.stage, stage.status) for stage in stages),
        duplicate_fingerprint_in_project=duplicate_exists,
    )
