from __future__ import annotations

from datetime import datetime
from pathlib import Path
from ipaddress import ip_address
import re
import shutil
from typing import Annotated
from uuid import UUID, uuid5

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
from backend.app.services.story_direction import (in_day_order, load_story_inputs, rebuild_direction,
                                                  recommend_story_direction)
from backend.app.services.day_brief import MAX_CHARS as DAY_BRIEF_MAX_CHARS, load_day_brief, save_day_brief
from backend.app.services.project_reel import (ReelEditRefused, ReelOptions, ReelProjectNotFound, edit_history,
                                              edit_reel_draft, unused_shots, job_state, reel_output_dir, render_job_state,
                                              saved_draft, start_reel_draft, start_reel_render, undo_reel_draft)
from backend.app.services.reel_render import draft_fingerprint, saved_video
from backend.app.services import edit_brain, edit_rules, face_mosaic, longform_captions, longform_chat, my_edit_compare, reel_text, scene_thumbs, taste_log
from backend.app.services.reel_modes import (AUTO_MODE, DEFAULT_PACE, DEFAULT_SHORT_SECONDS, MODE_BY_KEY, MODES, PACES,
                                             SHORT_LENGTHS)
from backend.app.services.story_length import (LENGTH_OPTIONS, Moment, accept_minutes, fit_to_length, footage_seconds,
                                               length_notes, load_source_timing, rule_minutes)
from backend.app.services.project_scene_vision import start_vision, stored_vision_state, vision_status
from backend.app.services.project_analyze_all import AnalyzeAllSteps
from backend.app.services import speaker_voice
from backend.app.services.speaker_voice import VoiceRunRegistry, VoiceSource
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
    voice_skipped: bool = False  # TODO 24: ④ 목소리 skipped because "my voice" is not registered


def _analyze_all_response(request: Request, project_id: UUID) -> AnalyzeAllStatusResponse:
    state = request.app.state.project_analyze_all_registry.state(project_id)
    return AnalyzeAllStatusResponse(project_id=project_id, phase=state.phase, running=state.running, error=state.error,
                                    started_at=state.started_at, finished_at=state.finished_at,
                                    voice_skipped=state.voice_skipped)


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
        voice_registered=lambda: _load_my_voice(request, project_id).centroid is not None,
        voice_needed=lambda: bool(_voice_registry(request).pending(project_id, _voice_sources_sync(request, project_id))),
        start_voice=lambda: _voice_registry(request).start(project_id, lambda: _voice_sources_sync(request, project_id)),
        voice_status=lambda: _voice_registry(request).state(project_id).status,
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


# ---------- TODO 24: 대사 목록 · 내 목소리 ----------

def _voice_registry(request: Request) -> VoiceRunRegistry:
    state = request.app.state
    registry = getattr(state, "voice_run_registry", None)
    if registry is None:
        from concurrent.futures import ThreadPoolExecutor

        registry = VoiceRunRegistry(ThreadPoolExecutor(max_workers=1, thread_name_prefix="cutory-voice"),
                                    state.project_render_output_root)
        state.voice_run_registry = registry
    return registry


def _load_my_voice(request: Request, project_id: UUID) -> speaker_voice.MyVoice:
    return speaker_voice.load_my_voice(request.app.state.project_render_output_root, project_id)


class _VoiceProjectMissing(Exception):
    pass


def _transcribed_sources_sync(factory, project_id: UUID) -> list[SourceVideo]:
    with factory() as session:
        if session.get(Project, project_id) is None:
            raise _VoiceProjectMissing
        rows = session.scalars(select(SourceVideo).where(SourceVideo.project_id == project_id)
                               .order_by(SourceVideo.original_filename, SourceVideo.created_at)).all()
        for row in rows:
            _ = row.transcript  # load while the session is open
        session.expunge_all()
        return list(rows)


def _segments(source: SourceVideo) -> tuple[dict, ...]:
    if source.transcript is None or not isinstance(source.transcript.segments, list):
        return ()
    return tuple(item for item in source.transcript.segments
                 if isinstance(item, dict) and str(item.get("text", "")).strip())


def _voice_sources_sync(request: Request, project_id: UUID) -> list[VoiceSource]:
    storage = request.app.state.source_storage
    return [VoiceSource(source.id, storage.resolve(source.storage_reference), _segments(source))
            for source in _transcribed_sources_sync(_session_factory(request), project_id) if source.transcript is not None]


class TranscriptLineResponse(BaseModel):
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None  # me | other | unknown; None = not scored yet (or scored for an older "my voice")
    score: float | None = None
    my_voice: bool = False  # this line was registered as "이건 내 목소리"


class TranscriptSourceResponse(BaseModel):
    source_video_id: UUID
    original_filename: str
    lines: list[TranscriptLineResponse]
    voice_current: bool


class MyVoiceSampleResponse(BaseModel):
    source_video_id: UUID
    start_seconds: float
    text: str


class VoiceRunResponse(BaseModel):
    status: str
    done: int
    total: int
    error: str | None = None


class TranscriptLinesResponse(BaseModel):
    project_id: UUID
    sources: list[TranscriptSourceResponse]
    my_voice: list[MyVoiceSampleResponse]
    threshold: float
    model_available: bool
    voice_run: VoiceRunResponse


class MyVoiceRequest(BaseModel):
    source_video_id: UUID
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(default="", max_length=500)


def _transcript_lines_sync(request: Request, project_id: UUID) -> TranscriptLinesResponse:
    output_root = request.app.state.project_render_output_root
    registry = _voice_registry(request)
    voice = speaker_voice.load_my_voice(output_root, project_id)
    marked = {(item["source_video_id"], round(float(item["start"]), 2)) for item in voice.samples}
    sources = []
    for source in _transcribed_sources_sync(_session_factory(request), project_id):
        segments = _segments(source)
        stored = speaker_voice.load_speaker_scores(output_root, project_id, source.id) or {}
        current = bool(voice.version and stored.get("voice_version") == voice.version
                       and stored.get("line_count") == len(segments))
        scores = stored.get("scores") if current else None
        lines = []
        for index, segment in enumerate(segments):
            score = scores[index] if scores else None
            start = float(segment["start_seconds"])
            lines.append(TranscriptLineResponse(
                start_seconds=start, end_seconds=float(segment["end_seconds"]), text=str(segment["text"]).strip(),
                speaker=speaker_voice.speaker_label(score) if scores else None, score=score,
                my_voice=(str(source.id), round(start, 2)) in marked))
        sources.append(TranscriptSourceResponse(source_video_id=source.id, original_filename=source.original_filename,
                                                lines=lines, voice_current=current or not segments))
    run = registry.state(project_id)
    return TranscriptLinesResponse(
        project_id=project_id, sources=sources,
        my_voice=[MyVoiceSampleResponse(source_video_id=item["source_video_id"], start_seconds=float(item["start"]),
                                        text=item.get("text", "")) for item in voice.samples],
        threshold=speaker_voice.MY_VOICE_THRESHOLD,
        model_available=getattr(registry.embedder, "available", lambda: True)(),
        voice_run=VoiceRunResponse(status=run.status, done=run.done, total=run.total, error=run.error))


@router.get("/{project_id}/transcript-lines", response_model=TranscriptLinesResponse)
async def get_project_transcript_lines(request: Request, project_id: UUID) -> TranscriptLinesResponse:
    """TODO 24: every transcript line, with 나/다른 사람 when the voice step has scored it."""
    try:
        return await run_in_threadpool(_transcript_lines_sync, request, project_id)
    except _VoiceProjectMissing as error:
        raise _project_not_found() from error


@router.post("/{project_id}/my-voice", response_model=TranscriptLinesResponse)
async def add_project_my_voice(request: Request, project_id: UUID, payload: MyVoiceRequest) -> TranscriptLinesResponse:
    """TODO 24: "이건 내 목소리" — adds this line's voice print to my voice (up to 10 lines are averaged)."""
    def work():
        sources = {item.id: item for item in _transcribed_sources_sync(_session_factory(request), project_id)}
        source = sources.get(payload.source_video_id)
        if source is None:
            raise HTTPException(status_code=404, detail={"code": "SOURCE_NOT_FOUND", "message": "영상을 찾을 수 없습니다."})
        speaker_voice.add_my_voice_sample(
            request.app.state.project_render_output_root, project_id, source_video_id=source.id,
            media_path=request.app.state.source_storage.resolve(source.storage_reference),
            start=payload.start_seconds, end=max(payload.end_seconds, payload.start_seconds + 0.1), text=payload.text,
            embedder=_voice_registry(request).embedder)
        return _transcript_lines_sync(request, project_id)
    try:
        return await run_in_threadpool(work)
    except _VoiceProjectMissing as error:
        raise _project_not_found() from error
    except speaker_voice.SpeakerVoiceError as error:
        raise HTTPException(status_code=422, detail={"code": "MY_VOICE_FAILED", "message": str(error)}) from error


@router.delete("/{project_id}/my-voice", response_model=TranscriptLinesResponse)
async def clear_project_my_voice(request: Request, project_id: UUID) -> TranscriptLinesResponse:
    """TODO 24: forget the registered voice lines (the 나/다른 사람 marks disappear until registered again)."""
    try:
        await run_in_threadpool(_transcribed_sources_sync, _session_factory(request), project_id)
    except _VoiceProjectMissing as error:
        raise _project_not_found() from error
    speaker_voice.clear_my_voice(request.app.state.project_render_output_root, project_id)
    return await run_in_threadpool(_transcript_lines_sync, request, project_id)


@router.post("/{project_id}/voice-scan", response_model=VoiceRunResponse, status_code=202)
async def start_project_voice_scan(request: Request, project_id: UUID) -> VoiceRunResponse:
    """TODO 24: ④ 목소리 on its own — scores every line that is not up to date with my voice."""
    await _snapshot_or_404(request, project_id)
    registry = _voice_registry(request)
    if not registry.start(project_id, lambda: _voice_sources_sync(request, project_id)):
        raise HTTPException(status_code=409, detail={"code": "VOICE_SCAN_ALREADY_ACTIVE",
                                                     "message": "목소리 분석이 이미 진행 중입니다."})
    run = registry.state(project_id)
    return VoiceRunResponse(status=run.status, done=run.done, total=run.total, error=run.error)


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
    rules_used: list[str] = []  # TODO 27: the "내 편집 규칙" this recommendation read
    max_cut_seconds: float | None = None  # TODO 27: a "N초 넘지 않게" rule kept on every scene


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


def _my_voice_counts_sync(factory, output_root, project_id, candidates) -> dict[UUID, int]:
    """TODO 32-2: how many lines in my voice (TODO 24 voice step) fall inside each scene."""
    with factory() as session:
        lines = longform_chat.load_inputs(session, output_root, project_id).lines
    counts: dict[UUID, int] = {}
    for candidate in candidates:
        start, end = float(candidate.start_seconds), float(candidate.end_seconds)
        mine = sum(1 for line in lines.get(candidate.source_video_id, ())
                   if line.speaker == "me" and line.end > start and line.start < end)
        if mine:
            counts[candidate.candidate_id] = mine
    return counts


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
    rules_used: list[str] = []
    my_voice: dict[UUID, int] = {}
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
        rules = edit_rules.rule_texts(output_root)
        if edit_rules.keeps_my_voice(rules):  # TODO 32-2: "내가 말하는 장면은 살린다"
            my_voice = await run_in_threadpool(_my_voice_counts_sync, factory, output_root, project_id, candidates)
        direction = await run_in_threadpool(recommend_story_direction, candidates, filenames, None,
                                            footage / 60 or None, brief, rules, my_voice)
        rules_used = rules if direction.engine.startswith("llm:") else []
    # TODO 32: the day in order, ending on its last scene (and, 32-2, every scene in my voice)
    direction = in_day_order(direction, candidates, filenames, tuple(my_voice))
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
    # TODO 27: "한 컷은 N초 넘지 않게" is also kept by Python (the small local AI cannot set scene lengths)
    max_cut = edit_rules.max_cut_seconds(edit_rules.rule_texts(request.app.state.project_render_output_root))
    capped = 0
    if max_cut:
        for key, (clip_start, clip_end) in list(clip_of.items()):
            if key in my_voice:
                continue  # TODO 32-2: a scene where I talk keeps its length
            if clip_end - clip_start > max_cut + 1e-3:
                middle = (clip_start + clip_end) / 2
                clip_of[key] = (round(middle - max_cut / 2, 3), round(middle + max_cut / 2, 3))
                capped += 1
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
        notes=list(direction.notes) + list(length_notes(fit))
        + ([f"내 규칙대로 {max_cut:g}초가 넘는 장면 {capped}개를 {max_cut:g}초로 줄였습니다."] if capped else [])
        + ([f"내가 말하는 장면 {len(my_voice)}개는 길이를 줄이지 않았습니다."] if my_voice and max_cut else []),
        fallback_reason=direction.fallback_reason,
        chapters=chapters, target_minutes=target, recommended_minutes=recommended, length_reason=length_reason,
        length_options=sorted({*LENGTH_OPTIONS, recommended}),
        total_seconds=round(sum(chapter.total_seconds for chapter in chapters), 3) if capped else fit.total_seconds,
        max_seconds=fit.max_seconds, footage_seconds=round(footage, 3),
        day_brief=brief, rules_used=rules_used, max_cut_seconds=max_cut,
    )


@router.get("/{project_id}/day-brief", response_model=DayBriefBody)
async def get_project_day_brief(request: Request, project_id: UUID) -> DayBriefBody:
    """TODO 23: the saved "오늘 있었던 일" note (empty when none)."""
    return DayBriefBody(text=load_day_brief(request.app.state.project_render_output_root, project_id))


# ---- TODO 26: chat editing of the longform plan, next to the video --------------------------------------------------

class ChatCutResponse(BaseModel):
    number: int
    candidate_id: UUID
    source_video_id: UUID
    source_filename: str
    start_seconds: float
    end_seconds: float
    timeline_start: float
    length: float
    speech: str
    caption: str | None = None


class ChatUnusedResponse(BaseModel):
    number: int
    candidate_id: UUID
    source_video_id: UUID
    source_filename: str
    start_seconds: float
    end_seconds: float
    speech: str


class ChatChoiceResponse(BaseModel):
    candidate_id: UUID
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    kind: str
    label: str


class ChatMessageResponse(BaseModel):
    id: str | None = None
    role: str
    text: str
    at_seconds: float | None = None
    done: list[str] = []
    skipped: list[str] = []
    engine: str | None = None
    error: str | None = None
    changed: list[str] = []
    undo: bool = False
    undone: bool = False  # TODO 27: taken back with 되돌리기 (not sent to the AI again)
    no_change: bool = False  # TODO 27: nothing in the plan changed
    choices: list[ChatChoiceResponse] = []  # TODO 27: "다른 장면으로" pictures
    for_cut: int | None = None
    picked: int | None = None


class ChatBrainResponse(BaseModel):
    key: str
    label: str


class ChatUsageResponse(BaseModel):
    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    usd: float


class ChatLastResponse(BaseModel):
    done: list[str]
    skipped: list[str]
    changed: list[UUID]
    engine: str


class RuleCandidateResponse(BaseModel):
    key: str
    text: str
    why: str


class ChatEditResponse(BaseModel):
    project_id: UUID
    cuts: list[ChatCutResponse]
    total_seconds: float
    unused: list[ChatUnusedResponse]
    messages: list[ChatMessageResponse]
    undo_count: int
    brains: list[ChatBrainResponse]
    default_brain: str | None
    usage: list[ChatUsageResponse]
    dropped: int = 0
    last: ChatLastResponse | None = None
    rule_candidates: list[RuleCandidateResponse] = []  # TODO 28: found in "내 선택 기록", shared by every project


class ChatEditRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    at_seconds: float | None = Field(default=None, ge=0)
    brain: str | None = Field(default=None, max_length=20)


def _chat_view(session: Session, output_root: Path, project_id: UUID,
               last: longform_chat.SendResult | None = None) -> ChatEditResponse:
    inputs = longform_chat.load_inputs(session, output_root, project_id)
    chat = longform_chat.load_chat(output_root, project_id)
    brains = edit_brain.available_brains()
    cuts = []
    for number, (begin, cut) in enumerate(zip(longform_chat.starts(inputs.cuts), inputs.cuts), start=1):
        scene = inputs.scenes[cut.candidate_id]
        cuts.append(ChatCutResponse(
            number=number, candidate_id=cut.candidate_id, source_video_id=scene.source_video_id,
            source_filename=scene.filename, start_seconds=cut.start, end_seconds=cut.end, timeline_start=begin,
            length=cut.length, caption=scene.caption,
            speech=longform_chat._speech(inputs.lines.get(scene.source_video_id, ()), cut.start, cut.end, 160)))
    unused = [ChatUnusedResponse(
        number=number, candidate_id=scene.candidate_id, source_video_id=scene.source_video_id,
        source_filename=scene.filename, start_seconds=scene.found_start, end_seconds=scene.found_end,
        speech=longform_chat._speech(inputs.lines.get(scene.source_video_id, ()), scene.found_start, scene.found_end, 120))
        for number, scene in enumerate(inputs.unused(), start=1)]
    messages = []
    for item in chat["messages"]:
        try:
            messages.append(ChatMessageResponse.model_validate(item))
        except Exception:  # an odd line in the file never breaks the screen
            continue
    usage = [ChatUsageResponse(key=key, calls=int(value.get("calls", 0)), input_tokens=int(value.get("input_tokens", 0)),
                               output_tokens=int(value.get("output_tokens", 0)), usd=float(value.get("usd", 0.0)))
             for key, value in chat["usage"].items() if isinstance(value, dict)]
    return ChatEditResponse(
        project_id=project_id, cuts=cuts, total_seconds=round(sum(cut.length for cut in inputs.cuts), 3),
        unused=unused, messages=messages, undo_count=len(chat["history"]),
        brains=[ChatBrainResponse(key=key, label=brain.label) for key, brain in brains.items()],
        default_brain=edit_brain.default_brain_key(brains), usage=usage, dropped=inputs.dropped,
        rule_candidates=[RuleCandidateResponse(key=item.key, text=item.text, why=item.why)
                         for item in _rule_candidates(output_root)],
        last=ChatLastResponse(done=list(last.done), skipped=list(last.skipped), changed=sorted(last.changed, key=str),
                              engine=last.engine) if last else None)


def _rule_candidates(output_root: Path) -> list[taste_log.Candidate]:
    texts = edit_rules.rule_texts(output_root)
    return taste_log.candidates(output_root, texts, edit_rules.max_cut_seconds(texts))


def _chat_http_error(error: longform_chat.ChatEditError) -> HTTPException:
    code = 409 if error.code in ("NO_EDIT_PLAN", "NOTHING_TO_UNDO", "UNDO_SCENES_GONE", "CHOICE_ALREADY_PICKED",
                                 "CHOICE_STALE") else \
        503 if error.code == "BRAIN_UNAVAILABLE" else 502 if error.code.startswith(("LLM_", "CLAUDE_")) else 422
    return HTTPException(status_code=code, detail={"code": error.code, "message": error.message})


async def _chat_work(request: Request, project_id: UUID, work) -> ChatEditResponse:
    factory = _session_factory(request)
    output_root = request.app.state.project_render_output_root

    def run():
        with factory() as session:
            last = work(session, output_root)
            return _chat_view(session, output_root, project_id, last)
    try:
        return await run_in_threadpool(run)
    except SceneProjectNotFoundError as error:
        raise _project_not_found() from error
    except longform_chat.ChatEditError as error:
        raise _chat_http_error(error) from error


@router.get("/{project_id}/chat-edit", response_model=ChatEditResponse)
async def get_project_chat_edit(request: Request, project_id: UUID) -> ChatEditResponse:
    """TODO 26: the saved plan as cuts on one timeline, unused scenes, the chat so far and the brains."""
    return await _chat_work(request, project_id, lambda session, root: None)


@router.post("/{project_id}/chat-edit", response_model=ChatEditResponse)
async def send_project_chat_edit(request: Request, project_id: UUID, payload: ChatEditRequest) -> ChatEditResponse:
    """TODO 26: one sentence ("[03:12] 이 장면 짧게") -> the plan is changed and saved (undo keeps the last 10)."""
    brains = edit_brain.available_brains()
    key = payload.brain if payload.brain in brains else edit_brain.default_brain_key(brains)
    brain = brains.get(key) if key else None
    return await _chat_work(request, project_id, lambda session, root: longform_chat.send_message(
        session, root, project_id, payload.message, payload.at_seconds, brain, edit_rules.rule_texts(root)))


class EditRuleResponse(BaseModel):
    id: str
    text: str


class EditRulesResponse(BaseModel):
    rules: list[EditRuleResponse]


class EditRuleRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def _rules_view(rules: list[dict]) -> EditRulesResponse:
    return EditRulesResponse(rules=[EditRuleResponse(id=rule["id"], text=rule["text"]) for rule in rules])


@router.get("/edit-rules", response_model=EditRulesResponse)
async def get_edit_rules(request: Request) -> EditRulesResponse:
    """TODO 27: "내 편집 규칙", shared by every project."""
    return _rules_view(edit_rules.load_rules(request.app.state.project_render_output_root))


@router.post("/edit-rules", response_model=EditRulesResponse)
async def add_edit_rule(request: Request, payload: EditRuleRequest) -> EditRulesResponse:
    """TODO 27: save one chat sentence as a rule (the [00:32] stamp is dropped, same text is kept once)."""
    try:
        return _rules_view(edit_rules.add_rule(request.app.state.project_render_output_root, payload.text))
    except edit_rules.EditRuleError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message}) from error


@router.delete("/edit-rules/{rule_id}", response_model=EditRulesResponse)
async def delete_edit_rule(request: Request, rule_id: str) -> EditRulesResponse:
    return _rules_view(edit_rules.delete_rule(request.app.state.project_render_output_root, rule_id))


class ChatPickRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=40)
    choice: int = Field(ge=-1, le=20)


@router.post("/{project_id}/chat-edit/pick", response_model=ChatEditResponse)
async def pick_project_chat_edit(request: Request, project_id: UUID, payload: ChatPickRequest) -> ChatEditResponse:
    """TODO 27: put the picked "다른 장면으로" picture in place of the cut (-1 keeps the cut)."""
    return await _chat_work(request, project_id, lambda session, root: longform_chat.pick_choice(
        session, root, project_id, payload.message_id, payload.choice))


@router.get("/{project_id}/sources/{source_id}/thumb", response_class=FileResponse)
async def get_project_source_thumb(request: Request, project_id: UUID, source_id: UUID,
                                   at: float = Query(ge=0, le=86400)) -> FileResponse:
    """TODO 27: a small picture (320 wide) of one moment of a source video, made once and reused."""
    storage = request.app.state.source_storage
    if not isinstance(storage, LocalSourceStorage):
        raise HTTPException(status_code=500, detail={"code": "SOURCE_STORAGE_UNAVAILABLE"})
    path = await run_in_threadpool(_source_media_path, _session_factory(request), storage, project_id, source_id)
    try:
        thumb = await run_in_threadpool(scene_thumbs.scene_thumb, request.app.state.project_render_output_root,
                                        project_id, source_id, path, round(at, 3))
    except scene_thumbs.ThumbError as error:
        raise HTTPException(status_code=500, detail={"code": "THUMB_FAILED"}) from error
    return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{project_id}/chat-edit/undo", response_model=ChatEditResponse)
async def undo_project_chat_edit(request: Request, project_id: UUID) -> ChatEditResponse:
    """TODO 26: put back the plan from before the last chat edit."""
    def work(session, root):
        longform_chat.undo(session, root, project_id)
        return None
    return await _chat_work(request, project_id, work)


class ChatRemakeClip(BaseModel):
    candidate_id: UUID
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class ChatRemakeRequest(BaseModel):
    clips: list[ChatRemakeClip] = Field(min_length=1, max_length=400)


@router.post("/{project_id}/chat-edit/remake", response_model=ChatEditResponse)
async def remake_project_chat_edit(request: Request, project_id: UUID, payload: ChatRemakeRequest) -> ChatEditResponse:
    """TODO 32: replace the plan with a new recommended one (undo puts the old plan back)."""
    clips = [(c.candidate_id, c.start_seconds, c.end_seconds) for c in payload.clips]

    def work(session, root):
        longform_chat.remake(session, root, project_id, clips)
        return None
    return await _chat_work(request, project_id, work)


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


# ---- TODO 25: my face (shared by every project) + hiding other people's faces --------------------------------------

_face_models = face_mosaic.FaceModels()


class MyFacePhoto(BaseModel):
    id: str
    filename: str
    url: str


class MyFaceResponse(BaseModel):
    photos: list[MyFacePhoto]
    model_available: bool
    threshold: float


def _face_dir(request: Request) -> Path:
    return face_mosaic.face_dir(request.app.state.project_render_output_root)


def _my_face_response(request: Request) -> MyFaceResponse:
    photos = face_mosaic.load_my_face(_face_dir(request)).photos
    return MyFaceResponse(photos=[MyFacePhoto(id=p["id"], filename=p.get("filename", ""),
                                              url=f"/projects/my-face/{p['id']}/image") for p in photos],
                          model_available=_face_models.available(), threshold=face_mosaic.SIM_ME)


def _face_http_error(error: face_mosaic.FaceMosaicError) -> HTTPException:
    return HTTPException(status_code=422 if error.code != "FACE_MODEL_MISSING" else 503,
                         detail={"code": error.code, "message": error.message or error.code})


@router.get("/my-face", response_model=MyFaceResponse)
async def get_my_face(request: Request) -> MyFaceResponse:
    return await run_in_threadpool(_my_face_response, request)


@router.post("/my-face", response_model=MyFaceResponse)
async def add_my_face_photo(request: Request, file: UploadFile = File(...)) -> MyFaceResponse:
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"code": "FACE_PHOTO_TOO_BIG", "message": "사진은 20MB까지 올릴 수 있습니다."})
    try:
        await run_in_threadpool(face_mosaic.add_photo, _face_dir(request), data, file.filename or "photo", _face_models)
    except face_mosaic.FaceMosaicError as error:
        raise _face_http_error(error) from error
    return await run_in_threadpool(_my_face_response, request)


@router.delete("/my-face/{photo_id}", response_model=MyFaceResponse)
async def remove_my_face_photo(request: Request, photo_id: str) -> MyFaceResponse:
    try:
        await run_in_threadpool(face_mosaic.remove_photo, _face_dir(request), photo_id)
    except face_mosaic.FaceMosaicError as error:
        raise HTTPException(status_code=404, detail={"code": error.code, "message": error.message}) from error
    return await run_in_threadpool(_my_face_response, request)


@router.get("/my-face/{photo_id}/image", response_class=FileResponse)
async def get_my_face_image(request: Request, photo_id: str) -> FileResponse:
    path = await run_in_threadpool(face_mosaic.face_image, _face_dir(request), photo_id)
    if path is None:
        raise HTTPException(status_code=404, detail={"code": "FACE_PHOTO_MISSING", "message": "No such photo."})
    return FileResponse(path, media_type="image/jpeg")


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
    # TODO 25: when other people's faces are already hidden on this render, the captions go on top of that video.
    hidden = face_mosaic.saved_video(face_mosaic.output_dir(request.app.state.project_render_output_root, project_id))
    if hidden is not None and hidden.render_id == render_id:
        video = hidden.path
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


class FaceVideoInfo(BaseModel):
    render_id: str
    duration_seconds: float
    file_size_bytes: int
    frames: int
    frames_hidden: int
    faces_hidden: int
    frames_with_me: int
    photo_count: int
    matches_render: bool
    url: str


class FaceVideoStatusResponse(BaseModel):
    project_id: UUID
    status: str
    done: int
    total: int
    error_code: str | None = None
    latest_render_id: str | None = None
    photo_count: int
    model_available: bool
    video: FaceVideoInfo | None = None


def _face_video_status(request: Request, project_id: UUID) -> FaceVideoStatusResponse:
    latest = _latest_render_files(request, project_id)
    job = face_mosaic.job_state(project_id)
    video = face_mosaic.saved_video(face_mosaic.output_dir(request.app.state.project_render_output_root, project_id))
    info = None
    if video is not None:
        stamp = int(video.path.stat().st_mtime)
        info = FaceVideoInfo(render_id=video.render_id, duration_seconds=video.duration_seconds,
                             file_size_bytes=video.file_size_bytes, photo_count=video.photo_count,
                             matches_render=latest is not None and latest[0] == video.render_id,
                             url=f"/projects/{project_id}/face-video/file?v={stamp}", **vars(video.stats))
    return FaceVideoStatusResponse(project_id=project_id, status=job.status, done=job.done, total=job.total,
                                   error_code=job.error_code, latest_render_id=latest[0] if latest else None,
                                   photo_count=len(face_mosaic.load_my_face(_face_dir(request)).photos),
                                   model_available=_face_models.available(), video=info)


@router.post("/{project_id}/face-video", response_model=FaceVideoStatusResponse, status_code=202)
async def start_project_face_video(request: Request, project_id: UUID) -> FaceVideoStatusResponse:
    """TODO 25: pixelate every face but mine on the last completed long-form render."""
    await _snapshot_or_404(request, project_id)
    latest = await run_in_threadpool(_latest_render_files, request, project_id)
    if latest is None:
        raise HTTPException(status_code=409, detail={"code": "FACE_RENDER_MISSING", "message": "Render the long-form video first."})
    my_face = await run_in_threadpool(face_mosaic.load_my_face, _face_dir(request))
    if my_face.prints is None:
        raise HTTPException(status_code=409, detail={"code": "FACE_NOT_REGISTERED", "message": "Register your face photos first."})
    if not _face_models.available():
        raise HTTPException(status_code=503, detail={"code": "FACE_MODEL_MISSING", "message": "Face models or OpenCV are missing."})
    render_id, video, _ = latest
    reason = face_mosaic.start_blurring(project_id, video, render_id, request.app.state.project_render_output_root,
                                        my_face, _face_models)
    if reason is not None:
        raise HTTPException(status_code=409, detail={"code": reason, "message": "Faces are already being hidden."})
    return await run_in_threadpool(_face_video_status, request, project_id)


@router.get("/{project_id}/face-video", response_model=FaceVideoStatusResponse)
async def get_project_face_video(request: Request, project_id: UUID) -> FaceVideoStatusResponse:
    await _snapshot_or_404(request, project_id)
    return await run_in_threadpool(_face_video_status, request, project_id)


@router.get("/{project_id}/face-video/file", response_class=FileResponse)
async def get_project_face_video_file(request: Request, project_id: UUID) -> FileResponse:
    video = face_mosaic.saved_video(face_mosaic.output_dir(request.app.state.project_render_output_root, project_id))
    if video is None:
        raise HTTPException(status_code=404, detail={"code": "FACE_VIDEO_MISSING", "message": "No face-hidden video yet."})
    return FileResponse(video.path, media_type="video/mp4", filename="vlog-faces.mp4", content_disposition_type="inline")

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


class RuleCandidateAnswer(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    accept: bool


@router.post("/{project_id}/chat-edit/rule-candidates", response_model=ChatEditResponse)
async def answer_rule_candidate(request: Request, project_id: UUID, payload: RuleCandidateAnswer) -> ChatEditResponse:
    """TODO 28: [규칙으로] saves the candidate as a "내 규칙"; [아니야] hides it. Either way it is not offered again."""
    def work(session, root):
        found = next((item for item in _rule_candidates(root) if item.key == payload.key), None)
        if found is None:
            raise longform_chat.ChatEditError("CANDIDATE_NOT_FOUND", "이 규칙 후보는 이미 없어요. 화면을 새로 고쳐 주세요.")
        if payload.accept:
            try:
                edit_rules.add_rule(root, found.text)
            except edit_rules.EditRuleError as error:
                raise longform_chat.ChatEditError(error.code, error.message) from error
        taste_log.answer(root, payload.key, payload.accept)
        return None
    return await _chat_work(request, project_id, work)


# --- TODO 29: my own edited video compared with the Cutory plan ------------------------------------------------------

MY_EDIT_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


class MyEditStatusResponse(BaseModel):
    project_id: UUID
    status: str
    step: str
    done: int
    total: int
    error_code: str | None = None
    has_video: bool
    result: dict | None = None


def _my_edit_status(request: Request, project_id: UUID) -> MyEditStatusResponse:
    root = request.app.state.project_render_output_root
    job = my_edit_compare.job_state(project_id)
    video = my_edit_compare.saved_video(my_edit_compare.output_dir(root, project_id))
    return MyEditStatusResponse(project_id=project_id, status=job.status, step=job.step, done=job.done,
                                total=job.total, error_code=job.error_code, has_video=video is not None,
                                result=my_edit_compare.load_result(root, project_id))


def _start_my_edit(request: Request, project_id: UUID, filename: str) -> None:
    storage = request.app.state.source_storage
    root = request.app.state.project_render_output_root
    with _session_factory(request)() as session:
        try:
            inputs = my_edit_compare.build_inputs(session, storage, root, project_id, filename)
        except SceneProjectNotFoundError as error:
            raise _project_not_found() from error
    reason = my_edit_compare.start(root, project_id, inputs)
    if reason is not None:
        raise HTTPException(status_code=409, detail={"code": reason, "message": "이미 비교하는 중이에요."})


def _save_my_edit(request: Request, project_id: UUID, upload: UploadFile) -> str:
    """Stream the upload next to the result, check it is a video, then replace the old one."""
    name = Path(upload.filename or "my-edit.mp4").name
    suffix = Path(name).suffix.lower()
    if suffix not in MY_EDIT_SUFFIXES:
        raise HTTPException(status_code=415, detail={"code": "MY_EDIT_NOT_VIDEO", "message": "영상 파일(mp4·mov 등)만 올릴 수 있어요."})
    folder = my_edit_compare.output_dir(request.app.state.project_render_output_root, project_id)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"upload{suffix}.tmp"
    with temporary.open("wb") as out:
        shutil.copyfileobj(upload.file, out, length=8 * 1024 * 1024)
    try:
        my_edit_compare.probe_duration(temporary)
    except my_edit_compare.MyEditError as error:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail={"code": error.code, "message": "영상으로 읽을 수 없는 파일이에요."}) from error
    for old in folder.glob("edit.*"):
        old.unlink(missing_ok=True)
    (folder / "result.json").unlink(missing_ok=True)
    temporary.replace(folder / f"edit{suffix}")
    (folder / "name.txt").write_text(name, encoding="utf-8")
    return name


@router.get("/{project_id}/my-edit", response_model=MyEditStatusResponse)
async def get_project_my_edit(request: Request, project_id: UUID) -> MyEditStatusResponse:
    """TODO 29: comparing progress and the last comparison of my own edit with the Cutory plan."""
    await _snapshot_or_404(request, project_id)
    return await run_in_threadpool(_my_edit_status, request, project_id)


@router.post("/{project_id}/my-edit", response_model=MyEditStatusResponse, status_code=202)
async def upload_project_my_edit(request: Request, project_id: UUID, file: UploadFile = File(...)) -> MyEditStatusResponse:
    """TODO 29: upload my own edited video; finding its cuts in the sources starts right away."""
    await _snapshot_or_404(request, project_id)
    if my_edit_compare.job_state(project_id).status == "RUNNING":
        raise HTTPException(status_code=409, detail={"code": "MY_EDIT_RUNNING", "message": "이미 비교하는 중이에요."})
    try:
        name = await run_in_threadpool(_save_my_edit, request, project_id, file)
    finally:
        await file.close()
    await run_in_threadpool(_start_my_edit, request, project_id, name)
    return await run_in_threadpool(_my_edit_status, request, project_id)


@router.post("/{project_id}/my-edit/compare", response_model=MyEditStatusResponse, status_code=202)
async def compare_project_my_edit(request: Request, project_id: UUID) -> MyEditStatusResponse:
    """TODO 29: compare the uploaded edit again (after the Cutory plan changed). Source pictures are reused."""
    await _snapshot_or_404(request, project_id)
    folder = my_edit_compare.output_dir(request.app.state.project_render_output_root, project_id)
    if my_edit_compare.saved_video(folder) is None:
        raise HTTPException(status_code=409, detail={"code": "MY_EDIT_MISSING", "message": "먼저 내 편집 영상을 올려 주세요."})
    try:
        name = (folder / "name.txt").read_text(encoding="utf-8").strip()
    except OSError:
        name = "my-edit"
    await run_in_threadpool(_start_my_edit, request, project_id, name)
    return await run_in_threadpool(_my_edit_status, request, project_id)


@router.get("/{project_id}/my-edit/thumb", response_class=FileResponse)
async def get_project_my_edit_thumb(request: Request, project_id: UUID, at: float = Query(ge=0, le=86400)) -> FileResponse:
    """TODO 29: a small picture of one moment of my edit (for the '원본에 없음' parts)."""
    root = request.app.state.project_render_output_root
    video = my_edit_compare.saved_video(my_edit_compare.output_dir(root, project_id))
    if video is None:
        raise HTTPException(status_code=404, detail={"code": "MY_EDIT_MISSING"})
    key = uuid5(project_id, f"my-edit:{video.stat().st_size}:{int(video.stat().st_mtime)}")
    try:
        thumb = await run_in_threadpool(scene_thumbs.scene_thumb, root, project_id, key, video, round(at, 3))
    except scene_thumbs.ThumbError as error:
        raise HTTPException(status_code=500, detail={"code": "THUMB_FAILED"}) from error
    return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
