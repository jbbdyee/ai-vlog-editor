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
from backend.app.services.story_direction import load_story_inputs, rebuild_direction, recommend_story_direction
from backend.app.services.day_brief import MAX_CHARS as DAY_BRIEF_MAX_CHARS, load_day_brief, save_day_brief
from backend.app.services.project_reel import (ReelEditRefused, ReelOptions, ReelProjectNotFound, edit_history,
                                              edit_reel_draft, unused_shots, job_state, reel_output_dir, render_job_state,
                                              saved_draft, start_reel_draft, start_reel_render, undo_reel_draft)
from backend.app.services.reel_render import draft_fingerprint, saved_video
from backend.app.services import longform_captions, reel_text
from backend.app.services.reel_modes import (AUTO_MODE, DEFAULT_PACE, DEFAULT_SHORT_SECONDS, MODE_BY_KEY, MODES, PACES,
                                             SHORT_LENGTHS)
from backend.app.services.story_length import (LENGTH_OPTIONS, Moment, accept_minutes, fit_to_length, footage_seconds,
                                               length_notes, load_source_timing, rule_minutes)
from backend.app.services.project_scene_vision import start_vision, stored_vision_state, vision_status
from backend.app.services.project_analyze_all import AnalyzeAllSteps
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
    SceneEditPlanInvalidRangeError,
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


class SceneClipRange(BaseModel):
    """Where in the source video a chosen scene starts and ends (the widened clip)."""
    start_seconds: float
    end_seconds: float


class SceneEditPlanSaveRequest(BaseModel):
    candidate_ids: Annotated[list[UUID], Field(max_length=10000)]
    # Optional, same order as candidate_ids; null entries (or no list) keep the scene's own range.
    clip_ranges: Annotated[list[SceneClipRange | None] | None, Field(max_length=10000)] = None


class SceneEditPlanResponse(BaseModel):
    project_id: UUID
    candidate_ids: list[UUID]
    invalid_candidate_ids: list[UUID]
    clip_ranges: list[SceneClipRange | None] = []


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
    # P1 SRT download: offered only for a completed render whose SRT matches its recorded SHA-256.
    subtitle_download_available: bool = False
    subtitle_download_url: str | None = None


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
            _save_scene_edit_plan_sync, _session_factory(request), project_id, tuple(payload.candidate_ids),
            None if payload.clip_ranges is None else
            [None if r is None else (r.start_seconds, r.end_seconds) for r in payload.clip_ranges],
        )
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except SceneEditPlanInvalidRangeError as error:
        raise HTTPException(status_code=422, detail={"code": "SCENE_EDIT_PLAN_RANGE_INVALID", "message": "A scene range is outside its video. Get the recommendation again."}) from error
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
    state_source: str = "PROCESS"


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
    state = await run_in_threadpool(vision_status, project_id, _session_factory(request))
    return SceneVisionStatusResponse(project_id=project_id, **{k: v for k, v in state.items() if k != "latency_seconds"})


class AnalyzeAllStatusResponse(BaseModel):
    project_id: UUID
    phase: str
    running: bool
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _analyze_all_response(request: Request, project_id: UUID) -> AnalyzeAllStatusResponse:
    state = request.app.state.project_analyze_all_registry.state(project_id)
    return AnalyzeAllStatusResponse(project_id=project_id, phase=state.phase, running=state.running, error=state.error,
                                    started_at=state.started_at, finished_at=state.finished_at)


def _analyze_all_steps(request: Request, project_id: UUID) -> AnalyzeAllSteps:
    """Wires the server-side "전체 분석" to the same three steps the separate buttons start."""
    state = request.app.state
    factory = _session_factory(request)

    def sources():
        return _get_snapshot_sync(factory, project_id).sources

    def transcript_needed() -> bool:
        return state.project_run_registry.is_active(project_id) or any(
            item.processing_status in (SourceVideoStatus.READY, SourceVideoStatus.PROCESSING) for item in sources())

    def start_transcript() -> None:
        state.project_run_registry.start(project_id, lambda: process_project(
            session_factory=factory, storage=state.source_storage, workspace=state.processing_workspace,
            project_id=project_id, stt_model=state.stt_model, max_concurrency=1))

    def scenes_needed() -> bool:
        transcribed = {item.source_video_id for item in sources() if item.processing_status is SourceVideoStatus.COMPLETED}
        analyzed = {item.source_video_id for item in _list_scene_diagnostics_sync(factory, project_id) if item.status != "NOT_ANALYZED"}
        return bool(transcribed - analyzed)

    def start_scenes() -> None:
        state.project_scene_run_registry.start(project_id, lambda on_source_result: process_project_scenes(
            session_factory=factory, storage=state.source_storage, scene_workspace=state.scene_processing_workspace,
            project_id=project_id, on_source_result=on_source_result))

    def vision_needed() -> bool:
        with factory() as session:
            stored = stored_vision_state(session, project_id)
        return stored.total > 0 and stored.captioned < stored.total

    return AnalyzeAllSteps(
        transcript_needed=transcript_needed,
        start_transcript=start_transcript,
        transcript_busy=lambda: state.project_run_registry.is_active(project_id),
        transcribed_count=lambda: sum(item.processing_status is SourceVideoStatus.COMPLETED for item in sources()),
        scenes_needed=scenes_needed,
        start_scenes=start_scenes,
        scene_status=lambda: state.project_scene_run_registry.snapshot(project_id).run_status.value,
        vision_needed=vision_needed,
        start_vision=lambda: start_vision(project_id, factory, state.source_storage),
        vision_status=lambda: vision_status(project_id)["status"],
    )


@router.post("/{project_id}/analyze-all", response_model=AnalyzeAllStatusResponse, status_code=202)
async def start_project_analyze_all(request: Request, project_id: UUID) -> AnalyzeAllStatusResponse:
    """Starts transcript → scenes → vision on the server, so closing the page no longer stops the hand-off."""
    await _snapshot_or_404(request, project_id)
    if not request.app.state.project_analyze_all_registry.start(project_id, _analyze_all_steps(request, project_id)):
        raise HTTPException(status_code=409, detail={"code": "ANALYZE_ALL_ALREADY_ACTIVE", "message": "전체 분석이 이미 진행 중입니다."})
    return _analyze_all_response(request, project_id)


@router.get("/{project_id}/analyze-all", response_model=AnalyzeAllStatusResponse)
async def get_project_analyze_all(request: Request, project_id: UUID) -> AnalyzeAllStatusResponse:
    await _snapshot_or_404(request, project_id)
    return _analyze_all_response(request, project_id)


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


class StorySceneResponse(BaseModel):
    candidate_id: UUID
    source_video_id: UUID
    source_filename: str
    start_seconds: float  # the found moment (unchanged candidate)
    end_seconds: float
    clip_start_seconds: float  # the moment widened to fit the target length
    clip_end_seconds: float


class StoryChapterResponse(BaseModel):
    title: str
    description: str
    reason: str
    scenes: list[StorySceneResponse]
    total_seconds: float  # widened clips


class StoryDirectionResponse(BaseModel):
    project_id: UUID
    title: str
    summary: str
    chapters: list[StoryChapterResponse]
    engine: str
    notes: list[str]
    fallback_reason: str | None = None
    target_minutes: int
    recommended_minutes: int
    length_reason: str
    length_options: list[int]
    total_seconds: float
    max_seconds: float
    footage_seconds: float
    day_brief: str = ""  # TODO 23: the "오늘 있었던 일" note this recommendation used


class DayBriefBody(BaseModel):
    text: str = Field(default="", max_length=DAY_BRIEF_MAX_CHARS)


class StoryReuseChapter(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    description: str = Field(max_length=160)
    reason: str = Field(max_length=160)
    candidate_ids: list[UUID] = Field(min_length=1, max_length=200)


class StoryReuse(BaseModel):
    """An earlier recommendation sent back to change only its length (no new AI call)."""
    title: str = Field(min_length=1, max_length=60)
    summary: str = Field(max_length=240)
    engine: str = Field(max_length=120)
    recommended_minutes: int = Field(ge=1, le=60)
    length_reason: str = Field(max_length=200)
    chapters: list[StoryReuseChapter] = Field(min_length=1, max_length=12)


class StoryDirectionRequest(BaseModel):
    target_minutes: int | None = Field(default=None, ge=1, le=60)
    reuse: StoryReuse | None = None
    # TODO 23: sent with a fresh recommendation and saved for the project (empty clears it). None = use the saved one.
    day_brief: str | None = Field(default=None, max_length=DAY_BRIEF_MAX_CHARS)


def _load_story_inputs_sync(factory, project_id):
    with factory() as session:
        candidates, filenames = load_story_inputs(session, project_id)
        return candidates, filenames, load_source_timing(session, project_id)


@router.post("/{project_id}/story-direction", response_model=StoryDirectionResponse)
async def recommend_project_story_direction(request: Request, project_id: UUID,
                                            payload: StoryDirectionRequest | None = None) -> StoryDirectionResponse:
    """All videos -> recommended story outline fitted to a target length. Read-only: nothing is saved.

    Without a body the AI also recommends the length. With `reuse` only the length changes: the earlier chapters
    are re-fitted without asking the AI again.
    """
    payload = payload or StoryDirectionRequest()
    factory = _session_factory(request)
    try:
        candidates, filenames, timing = await run_in_threadpool(_load_story_inputs_sync, factory, project_id)
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except Exception as error:
        raise HTTPException(status_code=500, detail={"code": "SCENE_CANDIDATE_READ_FAILED", "message": "Scene candidates could not be loaded."}) from error
    if not candidates:
        raise HTTPException(status_code=409, detail={"code": "NO_SCENE_CANDIDATES", "message": "Run scene analysis before requesting a story direction."})
    footage = footage_seconds(timing)
    brief = ""
    if payload.reuse is not None:
        reuse = payload.reuse
        try:
            direction = rebuild_direction(
                candidates, filenames, title=reuse.title, summary=reuse.summary, engine=reuse.engine,
                chapters=[(c.title, c.description, c.reason, c.candidate_ids) for c in reuse.chapters],
                recommended_minutes=reuse.recommended_minutes, length_reason=reuse.length_reason)
        except ValueError as error:
            raise HTTPException(status_code=409, detail={"code": "STORY_SCENES_GONE", "message": "The earlier recommendation has no scenes left."}) from error
    else:
        output_root = request.app.state.project_render_output_root
        brief = (save_day_brief(output_root, project_id, payload.day_brief) if payload.day_brief is not None
                 else load_day_brief(output_root, project_id))
        direction = await run_in_threadpool(recommend_story_direction, candidates, filenames, None,
                                            footage / 60 or None, brief)
    if accept_minutes(direction.recommended_minutes, footage):
        recommended = direction.recommended_minutes
        length_reason = direction.length_reason or "AI가 영상 내용을 보고 추천한 길이입니다."
    else:
        recommended = rule_minutes(footage)
        length_reason = (direction.length_reason if payload.reuse is not None and direction.length_reason
                         else f"원본 약 {footage / 60:.0f}분의 1/4 정도로 계산한 기본 길이입니다.")
    target = payload.target_minutes or recommended
    scenes = [s for chapter in direction.chapters for s in chapter.scenes]
    fit = fit_to_length([Moment(s.candidate.source_video_id, float(s.candidate.start_seconds), float(s.candidate.end_seconds))
                         for s in scenes], timing, target * 60)
    clip_of = {s.candidate.candidate_id: clip for s, clip in zip(scenes, fit.clips)}
    chapters = []
    for chapter in direction.chapters:
        scene_rows = [StorySceneResponse(
            candidate_id=s.candidate.candidate_id, source_video_id=s.candidate.source_video_id,
            source_filename=s.source_filename, start_seconds=float(s.candidate.start_seconds),
            end_seconds=float(s.candidate.end_seconds), clip_start_seconds=clip_of[s.candidate.candidate_id][0],
            clip_end_seconds=clip_of[s.candidate.candidate_id][1]) for s in chapter.scenes]
        chapters.append(StoryChapterResponse(
            title=chapter.title, description=chapter.description, reason=chapter.reason, scenes=scene_rows,
            total_seconds=round(sum(r.clip_end_seconds - r.clip_start_seconds for r in scene_rows), 3)))
    return StoryDirectionResponse(
        project_id=project_id, title=direction.title, summary=direction.summary, engine=direction.engine,
        notes=list(direction.notes) + list(length_notes(fit)), fallback_reason=direction.fallback_reason,
        chapters=chapters, target_minutes=target, recommended_minutes=recommended, length_reason=length_reason,
        length_options=sorted({*LENGTH_OPTIONS, recommended}), total_seconds=fit.total_seconds,
        max_seconds=fit.max_seconds, footage_seconds=round(footage, 3),
        day_brief=brief,
    )


@router.get("/{project_id}/day-brief", response_model=DayBriefBody)
async def get_project_day_brief(request: Request, project_id: UUID) -> DayBriefBody:
    """TODO 23: the saved "오늘 있었던 일" note (empty when none)."""
    return DayBriefBody(text=load_day_brief(request.app.state.project_render_output_root, project_id))


class ReelOptionItem(BaseModel):
    key: str
    label: str


class ReelOptionsResponse(BaseModel):
    formats: list[ReelOptionItem]
    modes: list[ReelOptionItem]
    paces: list[ReelOptionItem]
    lengths: list[int]
    default_length: int
    # TODO 13: text looks for the vertical video
    text_templates: list[dict[str, str]]
    text_colors: list[ReelOptionItem]
    text_positions: list[ReelOptionItem]
    text_sizes: list[ReelOptionItem]
    text_motions: list[ReelOptionItem] = []  # TODO 15: how the title and lines come on screen
    text_title_times: list[ReelOptionItem] = []  # TODO 22: title on the first scene only or all along


@router.get("/reel-options", response_model=ReelOptionsResponse)
async def get_reel_options() -> ReelOptionsResponse:
    """Short-form choices from one settings file (reel_modes), so the screen never has its own copy."""
    text = reel_text.options()
    return ReelOptionsResponse(
        formats=[ReelOptionItem(key="short", label="숏폼 (릴스·쇼츠)"), ReelOptionItem(key="long", label="롱폼 (유튜브)")],
        modes=[ReelOptionItem(key=AUTO_MODE, label="자동 (AI가 골라 줌)")] + [ReelOptionItem(key=m.key, label=m.label) for m in MODES],
        paces=[ReelOptionItem(key=key, label=f"{label} (장면당 약 {seconds:g}초)") for key, (label, seconds) in PACES.items()],
        lengths=list(SHORT_LENGTHS), default_length=DEFAULT_SHORT_SECONDS,
        text_templates=text["templates"], text_colors=text["colors"], text_positions=text["positions"],
        text_sizes=text["sizes"], text_motions=text["motions"], text_title_times=text["title_times"],
    )


class ReelDraftRequest(BaseModel):
    format: str = Field(default="short", pattern="^(short|long)$")
    mode: str = Field(default=AUTO_MODE, max_length=32)
    pace: str = Field(default=DEFAULT_PACE, max_length=16)
    target_seconds: int = Field(default=DEFAULT_SHORT_SECONDS, ge=10, le=180)


class ReelSceneResponse(BaseModel):
    shot_index: int
    source_video_id: UUID
    source_filename: str
    start_seconds: float
    end_seconds: float
    caption: str
    label: str
    is_hook: bool
    shot_caption: str


class ReelTitleOptionResponse(BaseModel):
    lead: str
    title: str
    formula: str = ""


class ReelDraftResponse(BaseModel):
    format: str
    mode: str
    mode_label: str
    pace: str
    pace_label: str
    target_seconds: int
    total_seconds: float
    title_lead: str = ""  # TODO 14: small line above the title (its own text box)
    title: str
    title_options: list[ReelTitleOptionResponse] = []  # TODO 20: the AI's title candidates, the one first used first
    engine: str
    scenes: list[ReelSceneResponse]
    shot_count: int
    notes: list[str]
    fallback_reason: str | None = None


class ReelUnusedShotResponse(BaseModel):
    """TODO 18: a cut (piece of the sources, numbered in filmed order) that the draft does not use."""
    index: int
    source_video_id: UUID
    source_filename: str
    start_seconds: float
    end_seconds: float
    caption: str


class ReelDraftStatusResponse(BaseModel):
    project_id: UUID
    status: str
    step: str
    done: int
    total: int
    error_code: str | None = None
    draft: ReelDraftResponse | None = None
    can_undo: bool = False  # TODO 16: the draft before the last chat edit is kept
    undo_count: int = 0  # TODO 18: how many chat edits can be undone (up to 10)
    recent_changes: list[str] = []  # TODO 18: the last chat edits, newest first
    unused_shots: list[ReelUnusedShotResponse] = []  # TODO 18: cuts the draft does not use, to put back


def _reel_status_sync(factory, project_id) -> ReelDraftStatusResponse:
    with factory() as session:
        draft = saved_draft(session, project_id)
        history = edit_history(session, project_id)
        unused = unused_shots(session, project_id)
    job = job_state(project_id)
    return ReelDraftStatusResponse(
        project_id=project_id, status=job.status, step=job.step, done=job.done, total=job.total,
        can_undo=bool(history), undo_count=len(history),
        recent_changes=[entry["change"] for entry in history if entry.get("change")][:3],
        unused_shots=[ReelUnusedShotResponse(index=shot.index, source_video_id=shot.source_video_id,
                                             source_filename=shot.source_filename, start_seconds=shot.start_seconds,
                                             end_seconds=shot.end_seconds, caption=shot.caption) for shot in unused],
        error_code=job.error_code, draft=None if draft is None else ReelDraftResponse(**{
            **draft.to_json(), "scenes": [ReelSceneResponse(**vars(scene)) for scene in draft.scenes],
            "notes": list(draft.notes)}))


@router.post("/{project_id}/reel-draft", response_model=ReelDraftStatusResponse, status_code=202)
async def start_project_reel_draft(request: Request, project_id: UUID, payload: ReelDraftRequest) -> ReelDraftStatusResponse:
    """Short-form only (TODO 10). Long-form uses the story direction card that already exists."""
    if payload.format == "long":
        raise HTTPException(status_code=409, detail={"code": "LONG_FORM_USES_STORY_DIRECTION", "message": "Use the story direction for long-form videos."})
    if (payload.mode != AUTO_MODE and payload.mode not in MODE_BY_KEY) or payload.pace not in PACES:
        raise HTTPException(status_code=422, detail={"code": "REEL_OPTION_INVALID", "message": "Unknown mode or pace."})
    factory = _session_factory(request)
    storage = request.app.state.source_storage
    try:
        await run_in_threadpool(_reel_status_sync, factory, project_id)  # 404 before starting anything
    except ReelProjectNotFound as error:
        raise _project_not_found() from error
    started = start_reel_draft(project_id, factory, storage.resolve,
                               ReelOptions(payload.mode, payload.pace, payload.target_seconds))
    if not started:
        raise HTTPException(status_code=409, detail={"code": "REEL_DRAFT_RUNNING", "message": "A reel draft is already being made."})
    return await run_in_threadpool(_reel_status_sync, factory, project_id)


@router.get("/{project_id}/reel-draft", response_model=ReelDraftStatusResponse)
async def get_project_reel_draft(request: Request, project_id: UUID) -> ReelDraftStatusResponse:
    try:
        return await run_in_threadpool(_reel_status_sync, _session_factory(request), project_id)
    except ReelProjectNotFound as error:
        raise _project_not_found() from error


class ReelEditRequest(BaseModel):
    """TODO 16: one sentence such as "3번 더 길게"; ``selected`` is the scene number picked on the screen."""
    message: str = Field(min_length=1, max_length=300)
    selected: int | None = Field(default=None, ge=1, le=200)


class ReelEditResponse(ReelDraftStatusResponse):
    done_edits: list[str] = []
    skipped_edits: list[str] = []


_REEL_EDIT_STATUS = {"REEL_DRAFT_MISSING": 404, "REEL_EDIT_NOT_UNDERSTOOD": 422, "REEL_UNDO_EMPTY": 409}


def _reel_edit_error(error: ReelEditRefused) -> HTTPException:
    return HTTPException(status_code=_REEL_EDIT_STATUS.get(error.code, 409),
                         detail={"code": error.code, "message": "The reel draft could not be changed."})


def _reel_edit_sync(factory, project_id, payload: ReelEditRequest) -> ReelEditResponse:
    result = edit_reel_draft(factory, project_id, payload.message, payload.selected)
    status = _reel_status_sync(factory, project_id)
    return ReelEditResponse(**status.model_dump(), done_edits=list(result.done), skipped_edits=list(result.skipped))


@router.post("/{project_id}/reel-draft/edit", response_model=ReelEditResponse)
async def edit_project_reel_draft(request: Request, project_id: UUID, payload: ReelEditRequest) -> ReelEditResponse:
    try:
        return await run_in_threadpool(_reel_edit_sync, _session_factory(request), project_id, payload)
    except ReelProjectNotFound as error:
        raise _project_not_found() from error
    except ReelEditRefused as error:
        raise _reel_edit_error(error) from error


class ReelUndoResponse(ReelDraftStatusResponse):
    undone: str = ""  # TODO 18: what the undone edit had changed


def _reel_undo_sync(factory, project_id) -> ReelUndoResponse:
    undone = undo_reel_draft(factory, project_id)
    return ReelUndoResponse(**_reel_status_sync(factory, project_id).model_dump(), undone=undone)


@router.post("/{project_id}/reel-draft/undo", response_model=ReelUndoResponse)
async def undo_project_reel_draft(request: Request, project_id: UUID) -> ReelUndoResponse:
    try:
        return await run_in_threadpool(_reel_undo_sync, _session_factory(request), project_id)
    except ReelProjectNotFound as error:
        raise _project_not_found() from error
    except ReelEditRefused as error:
        raise _reel_edit_error(error) from error



class ReelTextStyle(BaseModel):
    """TODO 13: how the title, name tags and lines look. Unknown values fall back to the defaults."""
    template: str = Field(default=reel_text.DEFAULT_TEMPLATE, max_length=24)
    color: str = Field(default=reel_text.AUTO, max_length=24)
    position: str = Field(default=reel_text.AUTO, max_length=24)
    size: str = Field(default="normal", max_length=24)
    motion: str = Field(default=reel_text.DEFAULT_MOTION, max_length=24)  # TODO 15
    title_time: str = Field(default=reel_text.DEFAULT_TITLE_TIME, max_length=24)  # TODO 22


class ReelVideoRequest(BaseModel):
    text_style: ReelTextStyle = Field(default_factory=ReelTextStyle)


class ReelVideoInfo(BaseModel):
    text_style: ReelTextStyle
    duration_seconds: float
    file_size_bytes: int
    scene_count: int
    matches_draft: bool
    url: str


class ReelVideoStatusResponse(BaseModel):
    project_id: UUID
    status: str
    step: str
    done: int
    total: int
    error_code: str | None = None
    video: ReelVideoInfo | None = None


def _reel_video_status_sync(factory, output_root, project_id) -> ReelVideoStatusResponse:
    with factory() as session:
        draft = saved_draft(session, project_id)  # 404 for an unknown project
    job = render_job_state(project_id)
    video = saved_video(reel_output_dir(output_root, project_id))
    info = None
    if video is not None:
        stamp = int(video.path.stat().st_mtime)
        info = ReelVideoInfo(duration_seconds=video.duration_seconds, file_size_bytes=video.file_size_bytes,
                             scene_count=video.scene_count, text_style=ReelTextStyle(**video.text_style.to_json()),
                             matches_draft=draft is not None and draft_fingerprint(draft) == video.draft_fingerprint,
                             url=f"/projects/{project_id}/reel-video/file?v={stamp}")
    return ReelVideoStatusResponse(project_id=project_id, status=job.status, step=job.step, done=job.done,
                                   total=job.total, error_code=job.error_code, video=info)


@router.post("/{project_id}/reel-video", response_model=ReelVideoStatusResponse, status_code=202)
async def start_project_reel_video(request: Request, project_id: UUID,
                                   payload: ReelVideoRequest | None = None) -> ReelVideoStatusResponse:
    """TODO 12: make the vertical video (title and lines burned in) from the saved reel draft."""
    factory, output_root = _session_factory(request), request.app.state.project_render_output_root
    try:
        await run_in_threadpool(_reel_video_status_sync, factory, output_root, project_id)
    except ReelProjectNotFound as error:
        raise _project_not_found() from error
    style = reel_text.normalize((payload or ReelVideoRequest()).text_style.model_dump())
    reason = await run_in_threadpool(lambda: start_reel_render(
        project_id, factory, request.app.state.source_storage.resolve, output_root, text_style=style))
    if reason is not None:
        raise HTTPException(status_code=409, detail={"code": reason, "message": "The reel video cannot start now."})
    return await run_in_threadpool(_reel_video_status_sync, factory, output_root, project_id)


@router.get("/{project_id}/reel-video", response_model=ReelVideoStatusResponse)
async def get_project_reel_video(request: Request, project_id: UUID) -> ReelVideoStatusResponse:
    try:
        return await run_in_threadpool(_reel_video_status_sync, _session_factory(request),
                                       request.app.state.project_render_output_root, project_id)
    except ReelProjectNotFound as error:
        raise _project_not_found() from error


@router.get("/{project_id}/reel-video/file", response_class=FileResponse)
async def get_project_reel_video_file(request: Request, project_id: UUID) -> FileResponse:
    video = saved_video(reel_output_dir(request.app.state.project_render_output_root, project_id))
    if video is None:
        raise HTTPException(status_code=404, detail={"code": "REEL_VIDEO_MISSING", "message": "No reel video yet."})
    return FileResponse(video.path, media_type="video/mp4", filename="reel.mp4", content_disposition_type="inline")


class CaptionedVideoInfo(BaseModel):
    render_id: str
    duration_seconds: float
    file_size_bytes: int
    line_count: int
    thoughts: list[str]
    thought_engine: str
    matches_render: bool
    url: str


class CaptionedVideoStatusResponse(BaseModel):
    project_id: UUID
    status: str
    step: str
    done: int
    total: int
    error_code: str | None = None
    latest_render_id: str | None = None
    video: CaptionedVideoInfo | None = None


def _latest_render_files(request: Request, project_id: UUID):
    """(render_id, final.mp4, final.srt or None) of the last completed render, or None."""
    snapshot = request.app.state.project_render_run_registry.snapshot(project_id)
    result = snapshot.result
    if snapshot.status is not RenderRunStatus.COMPLETED or result is None:
        return None
    video = _render_output_path(request, project_id, result, "final.mp4", result.output_path)
    if video is None or not video.is_file():
        return None
    srt = None
    if result.subtitle_path is not None and not result.subtitle_error_code:
        srt = _render_output_path(request, project_id, result, "final.srt", result.subtitle_path)
    return result.render_id.hex, video, srt


def _captioned_status(request: Request, project_id: UUID) -> CaptionedVideoStatusResponse:
    latest = _latest_render_files(request, project_id)
    job = longform_captions.job_state(project_id)
    video = longform_captions.saved_video(
        longform_captions.output_dir(request.app.state.project_render_output_root, project_id))
    info = None
    if video is not None:
        stamp = int(video.path.stat().st_mtime)
        info = CaptionedVideoInfo(render_id=video.render_id, duration_seconds=video.duration_seconds,
                                  file_size_bytes=video.file_size_bytes, line_count=video.line_count,
                                  thoughts=list(video.thoughts), thought_engine=video.thought_engine,
                                  matches_render=latest is not None and latest[0] == video.render_id,
                                  url=f"/projects/{project_id}/captioned-video/file?v={stamp}")
    return CaptionedVideoStatusResponse(project_id=project_id, status=job.status, step=job.step, done=job.done,
                                        total=job.total, error_code=job.error_code,
                                        latest_render_id=latest[0] if latest else None, video=info)


@router.post("/{project_id}/captioned-video", response_model=CaptionedVideoStatusResponse, status_code=202)
async def start_project_captioned_video(request: Request, project_id: UUID) -> CaptionedVideoStatusResponse:
    """TODO 21: burn the spoken lines (and a few inner thoughts) onto the last completed long-form render."""
    await _snapshot_or_404(request, project_id)
    latest = await run_in_threadpool(_latest_render_files, request, project_id)
    if latest is None:
        raise HTTPException(status_code=409, detail={"code": "CAPTION_RENDER_MISSING",
                                                     "message": "Render the long-form video first."})
    render_id, video, srt = latest
    if srt is None:
        raise HTTPException(status_code=409, detail={"code": "CAPTION_NO_LINES",
                                                     "message": "This render has no spoken lines (SRT)."})
    reason = longform_captions.start_captioning(project_id, video, srt, render_id,
                                                request.app.state.project_render_output_root)
    if reason is not None:
        raise HTTPException(status_code=409, detail={"code": reason, "message": "Captions are already being made."})
    return await run_in_threadpool(_captioned_status, request, project_id)


@router.get("/{project_id}/captioned-video", response_model=CaptionedVideoStatusResponse)
async def get_project_captioned_video(request: Request, project_id: UUID) -> CaptionedVideoStatusResponse:
    await _snapshot_or_404(request, project_id)
    return await run_in_threadpool(_captioned_status, request, project_id)


@router.get("/{project_id}/captioned-video/file", response_class=FileResponse)
async def get_project_captioned_video_file(request: Request, project_id: UUID) -> FileResponse:
    video = longform_captions.saved_video(
        longform_captions.output_dir(request.app.state.project_render_output_root, project_id))
    if video is None:
        raise HTTPException(status_code=404, detail={"code": "CAPTION_VIDEO_MISSING", "message": "No captioned video yet."})
    return FileResponse(video.path, media_type="video/mp4", filename="vlog-captioned.mp4",
                        content_disposition_type="inline")

def _read_scene_edit_plan_sync(factory, project_id):
    with factory() as session:
        return get_scene_edit_plan(session, project_id)


def _save_scene_edit_plan_sync(factory, project_id, candidate_ids, clip_ranges=None):
    with factory() as session:
        return save_scene_edit_plan(session, project_id, candidate_ids, clip_ranges)


def _scene_edit_plan_response(snapshot: SceneEditPlanSnapshot) -> SceneEditPlanResponse:
    return SceneEditPlanResponse(
        project_id=snapshot.project_id,
        candidate_ids=list(snapshot.candidate_ids),
        invalid_candidate_ids=list(snapshot.invalid_candidate_ids),
        clip_ranges=[None if r is None else SceneClipRange(start_seconds=r[0], end_seconds=r[1])
                     for r in snapshot.clip_ranges],
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
    # The SRT is generated independently of the MP4 encode, so it is offered on its own verification.
    srt_available = (snapshot.status is RenderRunStatus.COMPLETED and srt_integrity is IntegrityStatus.VERIFIED)
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
        subtitle_download_available=srt_available,
        subtitle_download_url=(f"/projects/{project_id}/renders/{result.render_id.hex}/subtitles/download"
                               if srt_available else None),
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


def _srt_integrity_error(status: IntegrityStatus) -> HTTPException:
    if status is IntegrityStatus.CORRUPT:
        return HTTPException(status_code=409, detail={"code": "SUBTITLE_FILE_CORRUPT",
                                                      "message": "Subtitle file content does not match its recorded digest."})
    if status is IntegrityStatus.UNVERIFIED:
        return HTTPException(status_code=409, detail={"code": "SUBTITLE_FILE_UNVERIFIED",
                                                      "message": "Subtitle file has no recorded digest and is not served."})
    return HTTPException(status_code=404, detail={"code": "SUBTITLE_FILE_NOT_FOUND", "message": "Subtitle file is unavailable."})


# Registered before the generic "{render_id:path}/download" route, which would otherwise capture this path.
@router.get("/{project_id}/renders/{render_id:path}/subtitles/download", response_class=FileResponse)
async def download_project_render_subtitles(request: Request, project_id: UUID, render_id: str) -> FileResponse:
    if _RENDER_ID_PATTERN.fullmatch(render_id) is None:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RENDER_ID", "message": "Render ID must be a lowercase 32-character hex value."})
    await _snapshot_or_404(request, project_id)
    result = _completed_result_or_error(request, project_id, render_id)
    if result.subtitle_path is None or result.subtitle_error_code:
        raise _srt_integrity_error(IntegrityStatus.MISSING)
    srt = await run_in_threadpool(_verify_srt_file, request, project_id, result, True)
    if srt.status is not IntegrityStatus.VERIFIED:
        raise _srt_integrity_error(srt.status)
    return VerifiedFileResponse(srt, media_type="application/x-subrip; charset=utf-8", filename=f"{render_id}.srt",
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


def _verify_srt_file(request: Request, project_id: UUID, result: ProjectRenderResult,
                     keep_open: bool = False) -> VerifiedFile:
    path = _render_output_path(request, project_id, result, "final.srt", result.subtitle_path)
    return verify_file(path, result.subtitle_size_bytes, result.subtitle_sha256, keep_open=keep_open)


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
