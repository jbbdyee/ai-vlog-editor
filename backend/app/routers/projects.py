from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStageKind,
    ProcessingStageStatus,
    ProjectStatus,
    SourceVideoStatus,
)
from backend.app.services.project_processing import process_project
from backend.app.services.project_scene_execution import SceneRunStatus
from backend.app.services.project_scene_processing import (
    SceneSourceOutcome,
    process_project_scenes,
)
from backend.app.services.project_scene_candidates import (
    SceneProjectNotFoundError,
    list_active_project_candidates,
)
from backend.app.services.project_scene_edit_plan import (
    SceneEditPlanInvalidSelectionError,
    SceneEditPlanSnapshot,
    get_scene_edit_plan,
    save_scene_edit_plan,
)
from backend.app.services.project_render_execution import RenderRunStatus
from backend.app.services.project_rendering import (
    ProjectRenderError,
    ProjectRenderResult,
    render_project_edit_plan,
    validate_project_render_request,
)
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


class CandidateEvidenceSummaryResponse(BaseModel):
    modality: str
    evidence_type: str
    count: int


class ActiveSceneCandidateResponse(BaseModel):
    candidate_id: UUID
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    evidence: list[CandidateEvidenceSummaryResponse]


class ProjectSceneCandidatesResponse(BaseModel):
    project_id: UUID
    candidates: list[ActiveSceneCandidateResponse]


class SceneEditPlanSaveRequest(BaseModel):
    candidate_ids: Annotated[list[UUID], Field(max_length=10000)]


class SceneEditPlanResponse(BaseModel):
    project_id: UUID
    candidate_ids: list[UUID]
    invalid_candidate_ids: list[UUID]


class ProjectRenderAcceptedResponse(BaseModel):
    project_id: UUID
    accepted: bool
    status_url: str


class ProjectRenderFileResponse(BaseModel):
    filename: str
    duration_seconds: float
    video_codec: str | None
    audio_codec: str | None
    file_size_bytes: int
    download_url: str | None


class ProjectRenderingStatusResponse(BaseModel):
    project_id: UUID
    status: RenderRunStatus
    render_id: UUID | None
    is_active: bool
    succeeded: bool
    failed: bool
    safe_error_code: str | None
    download_available: bool
    output: ProjectRenderFileResponse | None


class ProjectSceneProcessingAcceptedResponse(BaseModel):
    project_id: UUID
    accepted: bool
    status_url: str


class SceneSourceStatusResponse(BaseModel):
    source_video_id: UUID
    status: SceneSourceOutcome
    candidate_count: int
    safe_error_code: str | None
    warnings: list[str]


class ProjectSceneProcessingStatusResponse(BaseModel):
    project_id: UUID
    run_status: SceneRunStatus
    total_sources: int
    processed_count: int
    completed_count: int
    abstained_count: int
    failed_count: int
    blocked_count: int
    skipped_count: int
    safe_error_code: str | None
    sources: list[SceneSourceStatusResponse]


router = APIRouter(prefix="/projects", tags=["projects"])
_RENDER_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


@router.get(
    "/{project_id}/scene-candidates", response_model=ProjectSceneCandidatesResponse
)
async def get_project_scene_candidates(
    request: Request, project_id: UUID
) -> ProjectSceneCandidatesResponse:
    factory = _session_factory(request)
    try:
        candidates = await run_in_threadpool(
            _list_active_candidates_sync, factory, project_id
        )
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "SCENE_CANDIDATE_READ_FAILED",
                "message": "Scene candidates could not be loaded.",
            },
        ) from error
    return ProjectSceneCandidatesResponse(
        project_id=project_id,
        candidates=[
            ActiveSceneCandidateResponse(
                candidate_id=item.candidate_id,
                source_video_id=item.source_video_id,
                start_seconds=float(item.start_seconds),
                end_seconds=float(item.end_seconds),
                evidence=[CandidateEvidenceSummaryResponse(**row.__dict__) for row in item.evidence],
            )
            for item in candidates
        ],
    )


def _list_active_candidates_sync(factory, project_id):
    with factory() as session:
        return list_active_project_candidates(session, project_id)


@router.get("/{project_id}/scene-edit-plan", response_model=SceneEditPlanResponse)
async def read_project_scene_edit_plan(request: Request, project_id: UUID) -> SceneEditPlanResponse:
    try:
        snapshot = await run_in_threadpool(_read_scene_edit_plan_sync, _session_factory(request), project_id)
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "SCENE_EDIT_PLAN_READ_FAILED", "message": "Scene edit plan could not be loaded."}) from error
    return _scene_edit_plan_response(snapshot)


@router.put("/{project_id}/scene-edit-plan", response_model=SceneEditPlanResponse)
async def update_project_scene_edit_plan(
    request: Request, project_id: UUID, payload: SceneEditPlanSaveRequest
) -> SceneEditPlanResponse:
    try:
        snapshot = await run_in_threadpool(
            _save_scene_edit_plan_sync, _session_factory(request), project_id, tuple(payload.candidate_ids)
        )
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except SceneEditPlanInvalidSelectionError as error:
        raise HTTPException(status_code=409, detail={"code": "SCENE_EDIT_PLAN_CANDIDATE_CONFLICT", "message": "Selected scenes are no longer valid or contain duplicates. Refresh candidates and resolve the selection."}) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "SCENE_EDIT_PLAN_SAVE_FAILED", "message": "Scene edit plan could not be saved."}) from error
    return _scene_edit_plan_response(snapshot)


def _read_scene_edit_plan_sync(factory, project_id):
    with factory() as session:
        return get_scene_edit_plan(session, project_id)


def _save_scene_edit_plan_sync(factory, project_id, candidate_ids):
    with factory() as session:
        return save_scene_edit_plan(session, project_id, candidate_ids)


def _scene_edit_plan_response(snapshot: SceneEditPlanSnapshot) -> SceneEditPlanResponse:
    return SceneEditPlanResponse(
        project_id=snapshot.project_id,
        candidate_ids=list(snapshot.candidate_ids),
        invalid_candidate_ids=list(snapshot.invalid_candidate_ids),
    )


@router.post("/{project_id}/render", response_model=ProjectRenderAcceptedResponse, status_code=202)
async def start_project_render(request: Request, project_id: UUID) -> ProjectRenderAcceptedResponse:
    await _snapshot_or_404(request, project_id)
    registry = request.app.state.project_render_run_registry
    if registry.is_active(project_id):
        raise _render_already_active()
    factory = _session_factory(request)
    try:
        await run_in_threadpool(validate_project_render_request, factory, project_id)
    except ProjectRenderError as error:
        raise _render_preflight_error(error) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "RENDER_PREFLIGHT_FAILED", "message": "Render request could not be validated."}) from error

    def operation() -> ProjectRenderResult:
        return render_project_edit_plan(
            session_factory=factory,
            source_storage=request.app.state.source_storage,
            project_id=project_id,
            output_root=request.app.state.project_render_output_root,
        )

    try:
        accepted = registry.start(project_id, operation)
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "RENDER_START_FAILED", "message": "Render could not be started."}) from error
    if not accepted:
        raise _render_already_active()
    return ProjectRenderAcceptedResponse(
        project_id=project_id, accepted=True, status_url=f"/projects/{project_id}/rendering"
    )


@router.get("/{project_id}/rendering", response_model=ProjectRenderingStatusResponse)
async def get_project_rendering(request: Request, project_id: UUID) -> ProjectRenderingStatusResponse:
    await _snapshot_or_404(request, project_id)
    snapshot = request.app.state.project_render_run_registry.snapshot(project_id)
    result = snapshot.result
    available = result is not None and _completed_render_file(request, project_id, result) is not None
    output = None
    if result is not None:
        output = ProjectRenderFileResponse(
            filename="final.mp4", duration_seconds=result.duration_seconds,
            video_codec=result.video_codec, audio_codec=result.audio_codec,
            file_size_bytes=result.file_size_bytes,
            download_url=(f"/projects/{project_id}/renders/{result.render_id.hex}/download" if available else None),
        )
    return ProjectRenderingStatusResponse(
        project_id=project_id, status=snapshot.status,
        render_id=result.render_id if result else None,
        is_active=snapshot.status in {RenderRunStatus.QUEUED, RenderRunStatus.RUNNING},
        succeeded=snapshot.status is RenderRunStatus.COMPLETED,
        failed=snapshot.status is RenderRunStatus.FAILED,
        safe_error_code=snapshot.safe_error_code,
        download_available=available, output=output,
    )


@router.get("/{project_id}/renders/{render_id:path}/download", response_class=FileResponse)
async def download_project_render(request: Request, project_id: UUID, render_id: str) -> FileResponse:
    if _RENDER_ID_PATTERN.fullmatch(render_id) is None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RENDER_ID", "message": "Render ID must be a lowercase 32-character hex value."})
    await _snapshot_or_404(request, project_id)
    registry = request.app.state.project_render_run_registry
    result = registry.completed_result(project_id, UUID(hex=render_id))
    if result is None:
        snapshot = registry.snapshot(project_id)
        if snapshot.status in {RenderRunStatus.QUEUED, RenderRunStatus.RUNNING, RenderRunStatus.FAILED}:
            raise HTTPException(status_code=409, detail={"code": "RENDER_NOT_COMPLETED", "message": "Render is not completed."})
        raise _render_not_found()
    path = _completed_render_file(request, project_id, result)
    if path is None:
        raise _render_not_found()
    return FileResponse(
        path=path, media_type="video/mp4", filename=f"{render_id}.mp4",
        content_disposition_type="inline",
    )


def _completed_render_file(request: Request, project_id: UUID, result: ProjectRenderResult) -> Path | None:
    try:
        root = Path(request.app.state.project_render_output_root).resolve()
        expected = root / "projects" / project_id.hex / "renders" / result.render_id.hex / "final.mp4"
        actual = expected.resolve()
        if (result.project_id != project_id or expected.is_symlink()
            or not actual.is_relative_to(root) or result.output_path.resolve() != actual
            or not actual.is_file() or actual.stat().st_size != result.file_size_bytes
            or result.file_size_bytes <= 0):
            return None
    except OSError:
        return None
    return actual


def _render_already_active() -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "RENDER_ALREADY_ACTIVE", "message": "A render is already active for this Project in this process."})


def _render_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "RENDER_NOT_FOUND", "message": "Completed render was not found."})


def _render_preflight_error(error: ProjectRenderError) -> HTTPException:
    status_code = 409 if error.code == "PLAN_CANDIDATE_CONFLICT" else 422
    if error.code == "PROJECT_NOT_FOUND":
        return _project_not_found()
    return HTTPException(status_code=status_code, detail={"code": error.code, "message": str(error)})


@router.post(
    "/{project_id}/scene-process",
    response_model=ProjectSceneProcessingAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_project_scene_processing(
    request: Request, project_id: UUID
) -> ProjectSceneProcessingAcceptedResponse:
    await _snapshot_or_404(request, project_id)
    factory = _session_factory(request)
    registry = request.app.state.project_scene_run_registry

    def operation(on_source_result):
        return process_project_scenes(
            session_factory=factory,
            storage=request.app.state.source_storage,
            scene_workspace=request.app.state.scene_processing_workspace,
            project_id=project_id,
            on_source_result=on_source_result,
        )

    try:
        accepted = registry.start(project_id, operation)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "PROJECT_SCENE_PROCESSING_START_FAILED",
                "message": "Scene processing could not be started.",
            },
        ) from error
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROJECT_SCENE_PROCESSING_ALREADY_ACTIVE",
                "message": "Scene processing is already active for this Project in this process.",
            },
        )
    return ProjectSceneProcessingAcceptedResponse(
        project_id=project_id,
        accepted=True,
        status_url=f"/projects/{project_id}/scene-processing",
    )


@router.get(
    "/{project_id}/scene-processing",
    response_model=ProjectSceneProcessingStatusResponse,
)
async def get_project_scene_processing_status(
    request: Request, project_id: UUID
) -> ProjectSceneProcessingStatusResponse:
    project = await _snapshot_or_404(request, project_id)
    snapshot = request.app.state.project_scene_run_registry.snapshot(project_id)
    sources = snapshot.sources
    return ProjectSceneProcessingStatusResponse(
        project_id=project_id,
        run_status=snapshot.run_status,
        total_sources=len(project.sources),
        processed_count=len(sources),
        completed_count=sum(item.outcome is SceneSourceOutcome.COMPLETED for item in sources),
        abstained_count=sum(item.outcome is SceneSourceOutcome.ABSTAINED for item in sources),
        failed_count=sum(item.outcome is SceneSourceOutcome.FAILED for item in sources),
        blocked_count=sum(item.outcome is SceneSourceOutcome.BLOCKED for item in sources),
        skipped_count=sum(item.outcome is SceneSourceOutcome.SKIPPED_V1_INCOMPLETE for item in sources),
        safe_error_code=snapshot.safe_error_code,
        sources=[
            SceneSourceStatusResponse(
                source_video_id=item.source_video_id,
                status=item.outcome,
                candidate_count=item.candidate_count,
                safe_error_code=item.safe_error_code,
                warnings=list(item.warnings),
            )
            for item in sources
        ],
    )


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
