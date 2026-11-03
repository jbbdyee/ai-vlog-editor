from __future__ import annotations

from datetime import datetime
from pathlib import Path
from ipaddress import ip_address
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
from backend.app.models.product import Project, SourceVideo
from backend.app.models.edit_plan import ProjectSceneEditPlan
from backend.app.models.render import ProjectRenderRun
from backend.app.services.project_processing import process_project
from backend.app.services.edit_request import MAX_REQUEST_LENGTH
from backend.app.services.llm_edit_interpreter import interpret_with_llm
from backend.app.services.project_scene_vision import start_vision, vision_status
from backend.app.services.project_scene_execution import SceneRunStatus
from backend.app.services.project_scene_processing import (
    SceneSourceOutcome,
    process_project_scenes,
)
from backend.app.services.project_scene_candidates import (
    SceneProjectNotFoundError,
    list_active_project_candidates,
)
from backend.app.services.project_scene_diagnostics import (
    SceneDiagnosticsProjectNotFoundError,
    list_project_scene_diagnostics,
)
from backend.app.services.project_scene_edit_plan import (
    SceneEditPlanInvalidSelectionError,
    SceneEditPlanSnapshot,
    get_scene_edit_plan,
    save_scene_edit_plan,
)
from backend.app.services.project_render_execution import RenderRunStatus
from backend.app.services.render_integrity import IntegrityStatus, VerifiedFile, verify_file
from backend.app.routers.verified_file_response import VerifiedFileResponse
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
from backend.app.storage.source_storage import LocalSourceStorage, SourceStorageError


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


class ProjectListItemResponse(BaseModel):
    project_id: UUID
    name: str | None
    created_at: datetime
    updated_at: datetime
    source_count: int
    has_edit_plan: bool
    latest_render_status: str | None


class ProjectListResponse(BaseModel):
    items: list[ProjectListItemResponse]
    next_offset: int | None


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
    transcript_text: str | None = None
    visual_caption: str | None = None
    visual_tags: list[str] = []
    visual_categories: list[str] = []


class ProjectSceneCandidatesResponse(BaseModel):
    project_id: UUID
    candidates: list[ActiveSceneCandidateResponse]


class SceneEvidenceIntervalResponse(BaseModel):
    modality: str
    evidence_type: str
    start_seconds: float
    end_seconds: float


class SceneSourceDiagnosticResponse(BaseModel):
    source_video_id: UUID
    status: str
    has_record: bool
    candidate_count: int | None
    abstain_reason: str | None
    evidence_counts: dict[str, int | None]
    evidence_type_counts: dict[str, int]
    evidence_intervals: list[SceneEvidenceIntervalResponse]
    warnings: list[str]


class ProjectSceneDiagnosticsResponse(BaseModel):
    project_id: UUID
    sources: list[SceneSourceDiagnosticResponse]


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
    render_id: UUID | None = None


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
    hard_subtitle_status: str
    hard_subtitle_error_code: str | None
    hard_subtitle_download_available: bool
    hard_subtitle_download_url: str | None
    # QA-03 per-file content integrity. None = no such file recorded / not checked.
    integrity_status: IntegrityStatus | None = None
    subtitle_integrity_status: IntegrityStatus | None = None
    hard_subtitle_integrity_status: IntegrityStatus | None = None


class ProjectRenderHistoryResponse(BaseModel):
    project_id: UUID
    items: list[ProjectRenderingStatusResponse]
    next_cursor: UUID | None


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


def _source_media_path(factory, storage: LocalSourceStorage, project_id: UUID, source_id: UUID) -> Path:
    with factory() as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
        source = session.get(SourceVideo, source_id)
        if source is None or source.project_id != project_id:
            raise HTTPException(status_code=404, detail={"code": "SOURCE_NOT_FOUND"})
        reference = source.storage_reference
    try:
        path = storage.resolve(reference)
    except SourceStorageError as error:
        raise HTTPException(status_code=404, detail={"code": "SOURCE_MEDIA_UNAVAILABLE"}) from error
    expected_prefix = f"projects/{project_id.hex}/sources/"
    if not reference.startswith(expected_prefix) or path != storage._root.joinpath(*reference.split("/")):
        raise HTTPException(status_code=404, detail={"code": "SOURCE_MEDIA_UNAVAILABLE"})
    if not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail={"code": "SOURCE_MEDIA_UNAVAILABLE"})
    return path


@router.get("/{project_id}/sources/{source_id}/media", response_class=FileResponse)
async def get_project_source_media(request: Request, project_id: UUID, source_id: UUID) -> FileResponse:
    try:
        local = ip_address(request.client.host).is_loopback if request.client else False
    except ValueError:
        local = False
    if not local:
        raise HTTPException(status_code=403, detail={"code": "LOCAL_ACCESS_ONLY"})
    storage = request.app.state.source_storage
    if not isinstance(storage, LocalSourceStorage):
        raise HTTPException(status_code=500, detail={"code": "SOURCE_STORAGE_UNAVAILABLE"})
    path = await run_in_threadpool(_source_media_path, _session_factory(request), storage, project_id, source_id)
    media_type = "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
    return FileResponse(path, media_type=media_type, filename=f"source-preview{path.suffix.lower()}", content_disposition_type="inline", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"
    })


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
                transcript_text=item.transcript_text,
                visual_caption=item.visual_caption,
                visual_tags=list(item.visual_tags),
                visual_categories=list(item.visual_categories),
            )
            for item in candidates
        ],
    )


def _list_active_candidates_sync(factory, project_id):
    with factory() as session:
        return list_active_project_candidates(session, project_id)


@router.get("/{project_id}/scene-diagnostics", response_model=ProjectSceneDiagnosticsResponse)
async def get_project_scene_diagnostics(request: Request, project_id: UUID) -> ProjectSceneDiagnosticsResponse:
    try:
        sources = await run_in_threadpool(_list_scene_diagnostics_sync, _session_factory(request), project_id)
    except SceneDiagnosticsProjectNotFoundError as error:
        raise _project_not_found() from error
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "SCENE_DIAGNOSTICS_READ_FAILED",
                                                      "message": "Scene diagnostics could not be loaded."}) from error
    return ProjectSceneDiagnosticsResponse(
        project_id=project_id,
        sources=[SceneSourceDiagnosticResponse(
            source_video_id=item.source_video_id, status=item.status,
            has_record=item.has_record, candidate_count=item.candidate_count,
            abstain_reason=item.abstain_reason, evidence_counts=item.evidence_counts,
            evidence_type_counts=item.evidence_type_counts,
            evidence_intervals=[SceneEvidenceIntervalResponse(**row.__dict__) for row in item.evidence_intervals],
            warnings=list(item.warnings),
        ) for item in sources],
    )


def _list_scene_diagnostics_sync(factory, project_id):
    with factory() as session:
        return list_project_scene_diagnostics(session, project_id)


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


class EditSuggestionRequest(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_REQUEST_LENGTH)


class SuggestedSceneResponse(BaseModel):
    candidate_id: UUID
    reasons: list[str]


class EditSuggestionResponse(BaseModel):
    project_id: UUID
    candidate_ids: list[UUID]
    scenes: list[SuggestedSceneResponse]
    total_seconds: float
    target_seconds: float | None
    max_count: int | None
    keywords: list[str]
    excluded: list[str]
    categories: list[str]
    order: str
    notes: list[str]
    engine: str = "rule"
    interpretation: str | None = None
    mood: str | None = None
    fallback_reason: str | None = None


class SceneVisionStatusResponse(BaseModel):
    project_id: UUID
    status: str
    model: str
    total: int
    captioned: int
    skipped: int
    failed: int
    error_codes: list[str]


@router.post("/{project_id}/scene-vision", response_model=SceneVisionStatusResponse, status_code=202)
async def start_project_scene_vision(request: Request, project_id: UUID) -> SceneVisionStatusResponse:
    """Run the VLM over active candidates: visual caption/tags only, stored as non-authoritative evidence."""
    await _snapshot_or_404(request, project_id)
    if not start_vision(project_id, _session_factory(request), request.app.state.source_storage):
        raise HTTPException(status_code=409, detail={"code": "SCENE_VISION_ALREADY_ACTIVE", "message": "Scene vision analysis is already running."})
    return SceneVisionStatusResponse(project_id=project_id, **{k: v for k, v in vision_status(project_id).items() if k != "latency_seconds"})


@router.get("/{project_id}/scene-vision", response_model=SceneVisionStatusResponse)
async def get_project_scene_vision(request: Request, project_id: UUID) -> SceneVisionStatusResponse:
    await _snapshot_or_404(request, project_id)
    return SceneVisionStatusResponse(project_id=project_id, **{k: v for k, v in vision_status(project_id).items() if k != "latency_seconds"})


@router.post("/{project_id}/edit-suggestions", response_model=EditSuggestionResponse)
async def suggest_project_edit(request: Request, project_id: UUID, payload: EditSuggestionRequest) -> EditSuggestionResponse:
    """Natural-language request -> suggested scene order. Read-only: nothing is saved."""
    factory = _session_factory(request)
    try:
        candidates = await run_in_threadpool(_list_active_candidates_sync, factory, project_id)
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "SCENE_CANDIDATE_READ_FAILED", "message": "Scene candidates could not be loaded."}) from error
    if not candidates:
        raise HTTPException(status_code=409, detail={"code": "NO_SCENE_CANDIDATES", "message": "Run scene analysis before requesting an edit."})
    result = await run_in_threadpool(interpret_with_llm, payload.request, candidates)
    suggestion = result.suggestion
    intent = suggestion.intent
    return EditSuggestionResponse(
        project_id=project_id, candidate_ids=[scene.candidate_id for scene in suggestion.scenes],
        scenes=[SuggestedSceneResponse(candidate_id=scene.candidate_id, reasons=list(scene.reasons)) for scene in suggestion.scenes],
        total_seconds=suggestion.total_seconds, target_seconds=intent.target_seconds, max_count=intent.max_count,
        keywords=list(intent.keywords), excluded=list(intent.excluded), categories=list(intent.categories),
        order=intent.order, notes=list(suggestion.notes), engine=result.engine,
        interpretation=result.interpretation, mood=result.mood, fallback_reason=result.fallback_reason,
    )


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

    def operation(render_id: UUID | None = None, expected_plan_snapshot=None) -> ProjectRenderResult:
        return render_project_edit_plan(
            session_factory=factory,
            source_storage=request.app.state.source_storage,
            project_id=project_id,
            output_root=request.app.state.project_render_output_root,
            **({"render_id": render_id, "expected_plan_snapshot": expected_plan_snapshot}
               if render_id is not None else {}),
        )

    try:
        accepted = registry.start(project_id, operation)
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "RENDER_START_FAILED", "message": "Render could not be started."}) from error
    if not accepted:
        raise _render_already_active()
    return ProjectRenderAcceptedResponse(
        project_id=project_id, accepted=True, status_url=f"/projects/{project_id}/rendering",
        render_id=accepted if getattr(registry, "persistent", False) else None,
    )


@router.get("/{project_id}/rendering", response_model=ProjectRenderingStatusResponse)
async def get_project_rendering(request: Request, project_id: UUID) -> ProjectRenderingStatusResponse:
    await _snapshot_or_404(request, project_id)
    snapshot = request.app.state.project_render_run_registry.snapshot(project_id)
    # SHA-256 verification reads whole files; keep it off the event loop.
    return await run_in_threadpool(_render_status_response, request, project_id, snapshot)


_BASE_INTEGRITY_CODES = {
    IntegrityStatus.MISSING: "RENDER_FILE_MISSING",
    IntegrityStatus.CORRUPT: "RENDER_FILE_CORRUPT",
    IntegrityStatus.UNVERIFIED: "RENDER_FILE_UNVERIFIED",
}
_HARD_INTEGRITY_STATES = {
    IntegrityStatus.VERIFIED: "AVAILABLE",
    IntegrityStatus.MISSING: "MISSING",
    IntegrityStatus.CORRUPT: "CORRUPT",
    IntegrityStatus.UNVERIFIED: "UNVERIFIED",
}


def _render_status_response(request: Request, project_id: UUID, snapshot) -> ProjectRenderingStatusResponse:
    result = snapshot.result
    base_integrity = _verify_base_file(request, project_id, result).status if result is not None else None
    available = base_integrity is IntegrityStatus.VERIFIED
    srt_integrity = None
    if result is not None and result.subtitle_path is not None and not result.subtitle_error_code:
        srt_integrity = _verify_srt_file(request, project_id, result).status
    hard_integrity = None
    # Current dependency contract: the subtitled MP4 is offered only with a verified base MP4.
    if (result is not None and available and result.hard_subtitle_path is not None
            and not result.hard_subtitle_error_code):
        hard_integrity = _verify_hard_file(request, project_id, result).status
    hard_available = hard_integrity is IntegrityStatus.VERIFIED
    if result is None:
        hard_status = "NOT_STARTED"
    elif result.hard_subtitle_error_code:
        hard_status = "FAILED"
    elif result.hard_subtitle_path is not None:
        hard_status = _HARD_INTEGRITY_STATES[hard_integrity] if available else "BASE_UNAVAILABLE"
    elif result.subtitle_error_code:
        hard_status = "SUBTITLE_FAILED"
    elif result.subtitle_path is None:
        hard_status = "NO_SUBTITLES"
    else:
        hard_status = "NOT_CONFIGURED"
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
        render_id=result.render_id if result else snapshot.render_id,
        is_active=snapshot.status in {RenderRunStatus.QUEUED, RenderRunStatus.RUNNING},
        succeeded=snapshot.status is RenderRunStatus.COMPLETED,
        failed=snapshot.status is RenderRunStatus.FAILED,
        # The stored status stays COMPLETED; only current availability is reported.
        safe_error_code=(_BASE_INTEGRITY_CODES[base_integrity] if snapshot.status is RenderRunStatus.COMPLETED
                         and result is not None and not available else snapshot.safe_error_code),
        download_available=available, output=output,
        hard_subtitle_status=hard_status,
        hard_subtitle_error_code=(result.hard_subtitle_error_code or result.subtitle_error_code) if result else None,
        hard_subtitle_download_available=hard_available,
        hard_subtitle_download_url=(f"/projects/{project_id}/renders/{result.render_id.hex}/subtitled/download"
                                    if hard_available else None),
        integrity_status=base_integrity,
        subtitle_integrity_status=srt_integrity,
        hard_subtitle_integrity_status=hard_integrity,
    )


@router.get("/{project_id}/renders", response_model=ProjectRenderHistoryResponse)
async def get_project_render_history(request: Request, project_id: UUID,
                                     limit: int = 20, before: UUID | None = None) -> ProjectRenderHistoryResponse:
    await _snapshot_or_404(request, project_id)
    if limit < 1 or limit > 50:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PAGE_SIZE", "message": "Limit must be 1–50."})
    registry = request.app.state.project_render_run_registry
    if not getattr(registry, "persistent", False):
        return ProjectRenderHistoryResponse(project_id=project_id, items=[], next_cursor=None)
    snapshots, cursor = registry.history(project_id, limit, before)
    items = await run_in_threadpool(
        lambda: [_render_status_response(request, project_id, item) for item in snapshots])
    return ProjectRenderHistoryResponse(project_id=project_id, items=items, next_cursor=cursor)


def _completed_result_or_error(request: Request, project_id: UUID, render_id: str) -> ProjectRenderResult:
    registry = request.app.state.project_render_run_registry
    result = registry.completed_result(project_id, UUID(hex=render_id))
    if result is not None:
        return result
    if getattr(registry, "persistent", False):
        status = registry.run_status(project_id, UUID(hex=render_id))
        if status in {RenderRunStatus.QUEUED, RenderRunStatus.RUNNING, RenderRunStatus.FAILED,
                      RenderRunStatus.INTERRUPTED, RenderRunStatus.RECONCILIATION_REQUIRED}:
            raise HTTPException(status_code=409, detail={"code": "RENDER_NOT_COMPLETED", "message": "Render is not completed."})
        raise _render_not_found()
    snapshot = registry.snapshot(project_id)
    if snapshot.status in {RenderRunStatus.QUEUED, RenderRunStatus.RUNNING, RenderRunStatus.FAILED}:
        raise HTTPException(status_code=409, detail={"code": "RENDER_NOT_COMPLETED", "message": "Render is not completed."})
    raise _render_not_found()


def _base_integrity_error(status: IntegrityStatus) -> HTTPException:
    if status is IntegrityStatus.CORRUPT:
        return HTTPException(status_code=409, detail={"code": "RENDER_FILE_CORRUPT",
                                                      "message": "Render file content does not match its recorded digest."})
    if status is IntegrityStatus.UNVERIFIED:
        return HTTPException(status_code=409, detail={"code": "RENDER_FILE_UNVERIFIED",
                                                      "message": "Render has no recorded digest and is not served."})
    return _render_not_found()


def _hard_integrity_error(status: IntegrityStatus) -> HTTPException:
    if status is IntegrityStatus.CORRUPT:
        return HTTPException(status_code=409, detail={"code": "SUBTITLED_RENDER_CORRUPT",
                                                      "message": "Subtitled render content does not match its recorded digest."})
    if status is IntegrityStatus.UNVERIFIED:
        return HTTPException(status_code=409, detail={"code": "SUBTITLED_RENDER_UNVERIFIED",
                                                      "message": "Subtitled render has no recorded digest and is not served."})
    return HTTPException(status_code=404, detail={"code": "SUBTITLED_RENDER_NOT_FOUND", "message": "Subtitled render is unavailable."})


@router.get("/{project_id}/renders/{render_id:path}/subtitled/download", response_class=FileResponse)
async def download_project_subtitled_render(request: Request, project_id: UUID, render_id: str) -> FileResponse:
    if _RENDER_ID_PATTERN.fullmatch(render_id) is None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RENDER_ID", "message": "Render ID must be a lowercase 32-character hex value."})
    await _snapshot_or_404(request, project_id)
    result = _completed_result_or_error(request, project_id, render_id)
    base = await run_in_threadpool(_verify_base_file, request, project_id, result)
    if base.status is not IntegrityStatus.VERIFIED:
        raise _base_integrity_error(base.status)
    if result.hard_subtitle_path is None or result.hard_subtitle_error_code:
        raise _hard_integrity_error(IntegrityStatus.MISSING)
    hard = await run_in_threadpool(_verify_hard_file, request, project_id, result, True)
    if hard.status is not IntegrityStatus.VERIFIED:
        raise _hard_integrity_error(hard.status)
    return VerifiedFileResponse(hard, media_type="video/mp4", filename=f"{render_id}-subtitled.mp4",
                                content_disposition_type="attachment")


@router.get("/{project_id}/renders/{render_id:path}/download", response_class=FileResponse)
async def download_project_render(request: Request, project_id: UUID, render_id: str) -> FileResponse:
    if _RENDER_ID_PATTERN.fullmatch(render_id) is None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RENDER_ID", "message": "Render ID must be a lowercase 32-character hex value."})
    await _snapshot_or_404(request, project_id)
    result = _completed_result_or_error(request, project_id, render_id)
    base = await run_in_threadpool(_verify_base_file, request, project_id, result, True)
    if base.status is not IntegrityStatus.VERIFIED:
        raise _base_integrity_error(base.status)
    return VerifiedFileResponse(base, media_type="video/mp4", filename=f"{render_id}.mp4",
                                content_disposition_type="inline")


def _render_output_path(request: Request, project_id: UUID, result: ProjectRenderResult,
                        filename: str, recorded: Path | None) -> Path | None:
    """Rebuild the only allowed path; reject foreign IDs, symlinks and mismatched records."""
    if recorded is None or result.project_id != project_id:
        return None
    try:
        root = Path(request.app.state.project_render_output_root).resolve()
        expected = root / "projects" / project_id.hex / "renders" / result.render_id.hex / filename
        if (expected.resolve() != expected or any(path.is_symlink() for path in
                (root / "projects", root / "projects" / project_id.hex,
                 root / "projects" / project_id.hex / "renders", expected.parent, expected))
                or Path(recorded).resolve() != expected):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return expected


def _verify_base_file(request: Request, project_id: UUID, result: ProjectRenderResult,
                      keep_open: bool = False) -> VerifiedFile:
    if result.file_size_bytes <= 0:
        return VerifiedFile(IntegrityStatus.MISSING)
    path = _render_output_path(request, project_id, result, "final.mp4", result.output_path)
    return verify_file(path, result.file_size_bytes, result.file_sha256, keep_open=keep_open)


def _verify_hard_file(request: Request, project_id: UUID, result: ProjectRenderResult,
                      keep_open: bool = False) -> VerifiedFile:
    if result.hard_subtitle_error_code:
        return VerifiedFile(IntegrityStatus.MISSING)
    path = _render_output_path(request, project_id, result, "final-subtitled.mp4", result.hard_subtitle_path)
    return verify_file(path, result.hard_subtitle_size_bytes, result.hard_subtitle_sha256, keep_open=keep_open)


def _verify_srt_file(request: Request, project_id: UUID, result: ProjectRenderResult) -> VerifiedFile:
    path = _render_output_path(request, project_id, result, "final.srt", result.subtitle_path)
    return verify_file(path, result.subtitle_size_bytes, result.subtitle_sha256)


def _completed_render_file(request: Request, project_id: UUID, result: ProjectRenderResult) -> Path | None:
    """Compatibility helper: path only when the base MP4 is present and its SHA-256 matches."""
    verified = _verify_base_file(request, project_id, result)
    return _render_output_path(request, project_id, result, "final.mp4", result.output_path) \
        if verified.status is IntegrityStatus.VERIFIED else None


def _completed_hard_subtitle_file(request: Request, project_id: UUID, result: ProjectRenderResult) -> Path | None:
    """Compatibility helper: path only when the subtitled MP4 is present and its SHA-256 matches."""
    verified = _verify_hard_file(request, project_id, result)
    return _render_output_path(request, project_id, result, "final-subtitled.mp4", result.hard_subtitle_path) \
        if verified.status is IntegrityStatus.VERIFIED else None


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


def _list_projects_sync(factory: sessionmaker[Session], limit: int, offset: int) -> ProjectListResponse:
    source_count = (
        select(func.count(SourceVideo.id))
        .where(SourceVideo.project_id == Project.id).correlate(Project).scalar_subquery()
    )
    has_plan = (
        select(ProjectSceneEditPlan.project_id)
        .where(ProjectSceneEditPlan.project_id == Project.id).correlate(Project).exists()
    )
    latest_render = (
        select(ProjectRenderRun.status)
        .where(ProjectRenderRun.project_id == Project.id)
        .order_by(ProjectRenderRun.created_at.desc(), ProjectRenderRun.render_id.desc())
        .limit(1).correlate(Project).scalar_subquery()
    )
    with factory() as session:
        rows = session.execute(
            select(Project.id, Project.name, Project.created_at, Project.updated_at,
                   source_count, has_plan, latest_render)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .offset(offset).limit(limit + 1)
        ).all()
    return ProjectListResponse(
        items=[ProjectListItemResponse(project_id=row[0], name=row[1], created_at=row[2],
                                       updated_at=row[3], source_count=row[4],
                                       has_edit_plan=row[5], latest_render_status=row[6])
               for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects_route(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> ProjectListResponse:
    return await run_in_threadpool(_list_projects_sync, _session_factory(request), limit, offset)


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
