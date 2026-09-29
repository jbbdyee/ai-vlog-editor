from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStageKind,
    ProcessingStageStatus,
    ProjectStatus,
    SourceVideoStatus,
)
from backend.app.services.project_processing import process_project
from backend.app.services.project_service import (
    ProcessingSummary,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectSnapshot,
    SourceSummary,
    create_project,
    get_project_snapshot,
)
from backend.app.services.source_ingestion import (
    ProjectNotFoundError as IngestionProjectNotFoundError,
    SourceIngestionPersistenceError,
    ingest_source,
)
from backend.app.services.video_storage import VideoValidationError
from backend.app.storage.source_storage import SourceStorageError


class ProjectCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    split_policy: EpisodeSplitPolicy
    target_duration_seconds: Annotated[float | None, Field(gt=0)] = None
    instruction: str | None = None


class ProcessingSummaryResponse(BaseModel):
    total_sources: int
    completed_count: int
    failed_count: int
    blocked_count: int
    remaining_count: int
    progress_ratio: float


class ProjectResponse(BaseModel):
    project_id: UUID
    name: str
    status: ProjectStatus
    target_duration_seconds: float | None
    split_policy: EpisodeSplitPolicy
    instruction: str | None
    created_at: datetime
    updated_at: datetime
    source_count: int
    processing: ProcessingSummaryResponse


class StageSummaryResponse(BaseModel):
    stage: ProcessingStageKind
    status: ProcessingStageStatus
    safe_error_code: str | None


class SourceProcessingSummaryResponse(BaseModel):
    source_video_id: UUID
    original_filename: str
    processing_status: SourceVideoStatus
    stages: list[StageSummaryResponse]


class ProjectProcessingStatusResponse(BaseModel):
    project_id: UUID
    project_status: ProjectStatus
    total_sources: int
    completed_count: int
    failed_count: int
    blocked_count: int
    remaining_count: int
    progress_ratio: float
    sources: list[SourceProcessingSummaryResponse]


class SourceIngestionResponse(BaseModel):
    source_video_id: UUID
    project_id: UUID
    original_filename: str
    processing_status: SourceVideoStatus
    duplicate_fingerprint_in_project: bool


class ProjectProcessingAcceptedResponse(BaseModel):
    project_id: UUID
    accepted: bool
    current_project_status: ProjectStatus
    status_url: str


router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_route(
    request: Request, payload: ProjectCreateRequest
) -> ProjectResponse:
    factory = _session_factory(request)
    record = await run_in_threadpool(_create_project_sync, factory, payload)
    snapshot = ProjectSnapshot(
        project=record,
        summary=ProcessingSummary(0, 0, 0, 0, 0, 0.0),
        sources=(),
    )
    return _project_response(snapshot)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_route(request: Request, project_id: UUID) -> ProjectResponse:
    snapshot = await _snapshot_or_404(request, project_id)
    return _project_response(snapshot)


@router.post(
    "/{project_id}/sources",
    response_model=SourceIngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_project_source(
    request: Request,
    project_id: UUID,
    file: UploadFile = File(...),
) -> SourceIngestionResponse:
    factory = _session_factory(request)
    try:
        result = await run_in_threadpool(
            _ingest_source_sync,
            factory,
            request.app.state.source_storage,
            project_id,
            file,
        )
    except IngestionProjectNotFoundError as error:
        raise _project_not_found() from error
    except VideoValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "INVALID_SOURCE_MEDIA", "message": str(error)},
        ) from error
    except (SourceStorageError, SourceIngestionPersistenceError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "SOURCE_INGESTION_FAILED",
                "message": "Source ingestion failed safely.",
            },
        ) from error
    finally:
        await file.close()

    return SourceIngestionResponse(
        source_video_id=result.source_video_id,
        project_id=result.project_id,
        original_filename=result.original_filename,
        processing_status=result.processing_status,
        duplicate_fingerprint_in_project=result.duplicate_fingerprint_in_project,
    )


@router.post(
    "/{project_id}/process",
    response_model=ProjectProcessingAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_project_processing(
    request: Request, project_id: UUID
) -> ProjectProcessingAcceptedResponse:
    snapshot = await _snapshot_or_404(request, project_id)
    factory = _session_factory(request)
    storage = request.app.state.source_storage
    workspace = request.app.state.processing_workspace
    stt_model = request.app.state.stt_model
    run_registry = request.app.state.project_run_registry

    def operation() -> None:
        process_project(
            session_factory=factory,
            storage=storage,
            workspace=workspace,
            project_id=project_id,
            stt_model=stt_model,
            max_concurrency=1,
        )

    try:
        accepted = run_registry.start(project_id, operation)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "PROJECT_PROCESSING_START_FAILED",
                "message": "Project processing could not be started.",
            },
        ) from error
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROJECT_PROCESSING_ALREADY_ACTIVE",
                "message": "This Project is already active in this process.",
            },
        )
    return ProjectProcessingAcceptedResponse(
        project_id=project_id,
        accepted=True,
        current_project_status=snapshot.project.status,
        status_url=f"/projects/{project_id}/processing",
    )


@router.get(
    "/{project_id}/processing", response_model=ProjectProcessingStatusResponse
)
async def get_project_processing_status(
    request: Request, project_id: UUID
) -> ProjectProcessingStatusResponse:
    snapshot = await _snapshot_or_404(request, project_id)
    summary = snapshot.summary
    return ProjectProcessingStatusResponse(
        project_id=project_id,
        project_status=snapshot.project.status,
        total_sources=summary.total_sources,
        completed_count=summary.completed_count,
        failed_count=summary.failed_count,
        blocked_count=summary.blocked_count,
        remaining_count=summary.remaining_count,
        progress_ratio=summary.progress_ratio,
        sources=[_source_response(source) for source in snapshot.sources],
    )


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, "project_session_factory", None)
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PROJECT_DATABASE_UNAVAILABLE",
                "message": "Project database configuration is unavailable.",
            },
        )
    return factory


def _create_project_sync(
    factory: sessionmaker[Session], payload: ProjectCreateRequest
) -> ProjectRecord:
    with factory() as session:
        return create_project(
            session=session,
            name=payload.name,
            split_policy=payload.split_policy,
            target_duration_seconds=payload.target_duration_seconds,
            instruction=payload.instruction,
        )


def _ingest_source_sync(factory, storage, project_id, upload_file):
    with factory() as session:
        return ingest_source(
            session=session,
            storage=storage,
            project_id=project_id,
            file_object=upload_file.file,
            original_filename=upload_file.filename,
            content_type=upload_file.content_type,
        )


def _get_snapshot_sync(factory, project_id):
    with factory() as session:
        return get_project_snapshot(session=session, project_id=project_id)


async def _snapshot_or_404(request: Request, project_id: UUID) -> ProjectSnapshot:
    try:
        return await run_in_threadpool(
            _get_snapshot_sync, _session_factory(request), project_id
        )
    except ProjectNotFoundError as error:
        raise _project_not_found() from error


def _project_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PROJECT_NOT_FOUND", "message": "Project was not found."},
    )


def _project_response(snapshot: ProjectSnapshot) -> ProjectResponse:
    project = snapshot.project
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        status=project.status,
        target_duration_seconds=project.target_duration_seconds,
        split_policy=project.split_policy,
        instruction=project.instruction,
        created_at=project.created_at,
        updated_at=project.updated_at,
        source_count=snapshot.summary.total_sources,
        processing=ProcessingSummaryResponse(**snapshot.summary.__dict__),
    )


def _source_response(source: SourceSummary) -> SourceProcessingSummaryResponse:
    return SourceProcessingSummaryResponse(
        source_video_id=source.source_video_id,
        original_filename=source.original_filename,
        processing_status=source.processing_status,
        stages=[
            StageSummaryResponse(
                stage=stage.stage,
                status=stage.status,
                safe_error_code=stage.safe_error_code,
            )
            for stage in source.stages
        ],
    )
