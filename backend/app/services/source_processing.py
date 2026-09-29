from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    EditMemo as EditMemoRecord,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.audio_extractor import ExtractedAudio, extract_audio
from backend.app.services.media_probe import MediaInfo, probe_media
from backend.app.services.memo_detector import EditMemo, detect_edit_memos
from backend.app.services.stt_service import (
    STTResult,
    TranscriptSegment,
    TranscriptWord,
    transcribe_audio,
)
from backend.app.services.source_processing_state import (
    STAGE_ORDER,
    SourceResumePlan,
    StageVersionExpectation,
    determine_resume_plan,
    invalidate_from_stage,
    load_source_state,
    stage_result_is_valid,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import FINGERPRINT_ALGORITHM, SourceStorage


class SourceProcessingError(RuntimeError):
    """Base error for one Product SourceVideo processing attempt."""

    def __init__(self, message: str, *, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self._warnings = warnings if warnings is not None else []

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)


class SourceVideoNotFoundError(SourceProcessingError):
    """Raised when the requested SourceVideo does not exist."""


class SourceProcessingStateError(SourceProcessingError):
    """Raised before processing when current Product state is not executable."""


class SourceProcessingPersistenceError(SourceProcessingError):
    """Raised when a durable stage transition or result cannot be committed."""


class SourceFingerprintMismatchError(SourceProcessingError):
    """Raised when an explicit original integrity check detects changed bytes."""


class SourceStageExecutionError(SourceProcessingError):
    """Raised after safely persisting a failed media stage."""

    def __init__(
        self,
        *,
        stage: ProcessingStageKind,
        safe_error_code: str,
        safe_message: str,
        warnings: list[str],
    ) -> None:
        super().__init__(safe_message, warnings=warnings)
        self.stage = stage
        self.safe_error_code = safe_error_code
        self.safe_message = safe_message


@dataclass(frozen=True)
class SourceProcessingServices:
    probe: Callable[[Path], MediaInfo] = probe_media
    extract: Callable[[Path, Path], ExtractedAudio] = extract_audio
    transcribe: Callable[..., STTResult] = transcribe_audio
    detect_memos: Callable[[STTResult], tuple[EditMemo, ...]] = detect_edit_memos


@dataclass(frozen=True)
class SourceProcessingResult:
    source_video_id: UUID
    processing_status: SourceVideoStatus
    completed_stages: tuple[ProcessingStageKind, ...]
    transcript_id: UUID | None
    memo_count: int
    warnings: tuple[str, ...]


def process_source(
    *,
    session: Session,
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    source_video_id: UUID,
    stt_model: Any | None = None,
    services: SourceProcessingServices | None = None,
) -> SourceProcessingResult:
    """Run and persist the four existing media stages for one new SourceVideo."""
    source = session.get(SourceVideo, source_video_id)
    if source is None:
        raise SourceVideoNotFoundError("The SourceVideo does not exist.")

    stage_rows = session.scalars(
        select(ProcessingStage).where(
            ProcessingStage.source_video_id == source_video_id
        )
    ).all()
    stages = {row.stage: row for row in stage_rows}
    _validate_initial_state(source, stages)

    return _execute_stages(
        session=session,
        storage=storage,
        workspace=workspace,
        source=source,
        stages=stages,
        execution_stages=STAGE_ORDER,
        stt_model=stt_model,
        services=services or SourceProcessingServices(),
    )


def resume_source(
    *,
    session: Session,
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    source_video_id: UUID,
    stt_model: Any | None = None,
    services: SourceProcessingServices | None = None,
    version_expectations: Mapping[
        ProcessingStageKind, StageVersionExpectation
    ] | None = None,
    verify_source_fingerprint: bool = False,
) -> SourceProcessingResult:
    """Reuse valid results and execute only the work required for one SourceVideo."""
    source, stages = load_source_state(session, source_video_id)
    if verify_source_fingerprint:
        if source.fingerprint_algorithm != FINGERPRINT_ALGORITHM:
            raise SourceFingerprintMismatchError(
                "Original source fingerprint algorithm is not verifiable."
            )
        actual_fingerprint = storage.fingerprint(source.storage_reference)
        if actual_fingerprint != source.fingerprint:
            raise SourceFingerprintMismatchError(
                "Original source fingerprint verification failed."
            )

    plan = determine_resume_plan(
        session=session,
        source_video_id=source_video_id,
        version_expectations=version_expectations,
    )
    if plan.stale_stages:
        raise SourceProcessingStateError(
            "RUNNING stages require explicit stale recovery before resume."
        )
    if not plan.execution_stages:
        if source.processing_status != SourceVideoStatus.COMPLETED:
            source.processing_status = SourceVideoStatus.COMPLETED
            session.commit()
        return _processing_result(session, source, stages, warnings=())

    source, stages = _prepare_resume_execution(
        session=session,
        source_video_id=source_video_id,
        plan=plan,
    )
    return _execute_stages(
        session=session,
        storage=storage,
        workspace=workspace,
        source=source,
        stages=stages,
        execution_stages=plan.execution_stages,
        stt_model=stt_model,
        services=services or SourceProcessingServices(),
    )


def retry_source_stage(
    *,
    session: Session,
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    source_video_id: UUID,
    stage_kind: ProcessingStageKind,
    stt_model: Any | None = None,
    services: SourceProcessingServices | None = None,
    max_attempts: int | None = None,
) -> SourceProcessingResult:
    """Explicitly retry one FAILED stage once; no automatic retry loop is used."""
    source, stages = load_source_state(session, source_video_id)
    stage = stages[stage_kind]
    if stage.status != ProcessingStageStatus.FAILED:
        raise SourceProcessingStateError("Only a FAILED stage can be retried.")
    if max_attempts is not None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive when provided.")
        if stage.attempt_count >= max_attempts:
            raise SourceProcessingStateError("The explicit retry limit was reached.")
    for upstream in STAGE_ORDER[: STAGE_ORDER.index(stage_kind)]:
        if upstream == ProcessingStageKind.AUDIO_EXTRACTION:
            continue
        if not stage_result_is_valid(source=source, stage=stages[upstream]):
            raise SourceProcessingStateError(
                "Retry requires valid completed upstream results."
            )
    invalidate_from_stage(
        session=session,
        source_video_id=source_video_id,
        from_stage=stage_kind,
    )
    return resume_source(
        session=session,
        storage=storage,
        workspace=workspace,
        source_video_id=source_video_id,
        stt_model=stt_model,
        services=services,
    )


def reprocess_source_from(
    *,
    session: Session,
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    source_video_id: UUID,
    from_stage: ProcessingStageKind,
    stt_model: Any | None = None,
    services: SourceProcessingServices | None = None,
) -> SourceProcessingResult:
    """Explicitly replace the current result from one stage downstream."""
    invalidate_from_stage(
        session=session,
        source_video_id=source_video_id,
        from_stage=from_stage,
    )
    return resume_source(
        session=session,
        storage=storage,
        workspace=workspace,
        source_video_id=source_video_id,
        stt_model=stt_model,
        services=services,
    )


def _execute_stages(
    *,
    session: Session,
    storage: SourceStorage,
    workspace: LocalProcessingWorkspace,
    source: SourceVideo,
    stages: dict[ProcessingStageKind, ProcessingStage],
    execution_stages: tuple[ProcessingStageKind, ...],
    stt_model: Any | None,
    services: SourceProcessingServices,
) -> SourceProcessingResult:
    active_services = services
    warnings: list[str] = []
    transcript_record: Transcript | None = source.transcript
    source_path: Path | None = None
    extracted_audio: ExtractedAudio | None = None
    transcript_result: STTResult | None = None

    try:
        if ProcessingStageKind.PROBE in execution_stages:
            source_path, _media_info = _run_stage(
                session=session,
                source=source,
                stage=stages[ProcessingStageKind.PROBE],
                warnings=warnings,
                operation=lambda: _resolve_and_probe(
                    storage, active_services, source.storage_reference
                ),
                persist_result=lambda result: _persist_probe_result(source, result[1]),
            )
        if ProcessingStageKind.AUDIO_EXTRACTION in execution_stages:
            source_path = source_path or storage.resolve(source.storage_reference)
            extracted_audio = _run_stage(
                session=session,
                source=source,
                stage=stages[ProcessingStageKind.AUDIO_EXTRACTION],
                warnings=warnings,
                operation=lambda: active_services.extract(
                    source_path,
                    workspace.audio_directory(
                        project_id=source.project_id,
                        source_video_id=source.id,
                    ),
                ),
            )
        if ProcessingStageKind.STT in execution_stages:
            if extracted_audio is None:
                raise SourceProcessingStateError(
                    "STT execution requires recreated temporary audio."
                )
            transcript_result = _run_stage(
                session=session,
                source=source,
                stage=stages[ProcessingStageKind.STT],
                warnings=warnings,
                operation=lambda: active_services.transcribe(
                    extracted_audio.audio_path,
                    model=stt_model,
                    word_timestamps=True,
                ),
                persist_result=lambda result: _new_transcript(source, result),
            )
            transcript_record = source.transcript
        if ProcessingStageKind.MEMO_DETECTION in execution_stages:
            if transcript_result is None:
                transcript_result = _stt_result_from_transcript(transcript_record)
            _run_stage(
                session=session,
                source=source,
                stage=stages[ProcessingStageKind.MEMO_DETECTION],
                warnings=warnings,
                operation=lambda: active_services.detect_memos(transcript_result),
                persist_result=lambda memos: _persist_memos(
                    session, source, transcript_record, memos
                ),
                complete_source=True,
            )
    finally:
        try:
            workspace.cleanup_source(
                project_id=source.project_id,
                source_video_id=source.id,
            )
        except Exception:
            warnings.append("Could not remove the source temporary workspace.")

    return _processing_result(session, source, stages, warnings=tuple(warnings))


def _validate_initial_state(
    source: SourceVideo,
    stages: dict[ProcessingStageKind, ProcessingStage],
) -> None:
    if source.processing_status != SourceVideoStatus.READY:
        raise SourceProcessingStateError("SourceVideo must be READY before processing.")
    if source.transcript is not None:
        raise SourceProcessingStateError(
            "SourceVideo already has a Transcript; reprocess is not supported."
        )
    if set(stages) != set(STAGE_ORDER):
        raise SourceProcessingStateError(
            "SourceVideo must have exactly the required processing stages."
        )
    if any(
        stages[stage].status != ProcessingStageStatus.PENDING
        for stage in STAGE_ORDER
    ):
        raise SourceProcessingStateError(
            "All SourceVideo processing stages must be PENDING."
        )


def _prepare_resume_execution(
    *,
    session: Session,
    source_video_id: UUID,
    plan: SourceResumePlan,
) -> tuple[SourceVideo, dict[ProcessingStageKind, ProcessingStage]]:
    if not plan.invalid_stages:
        raise SourceProcessingStateError("Resume plan has no invalid start stage.")
    invalidate_from_stage(
        session=session,
        source_video_id=source_video_id,
        from_stage=plan.invalid_stages[0],
    )
    source, stages = load_source_state(session, source_video_id)
    for kind in plan.execution_stages:
        stage = stages[kind]
        if stage.status == ProcessingStageStatus.COMPLETED:
            _reset_for_execution(stage)
    source.processing_status = SourceVideoStatus.READY
    session.commit()
    return source, stages


def _processing_result(
    session: Session,
    source: SourceVideo,
    stages: dict[ProcessingStageKind, ProcessingStage],
    *,
    warnings: tuple[str, ...],
) -> SourceProcessingResult:
    transcript = source.transcript
    memo_count = len(
        session.scalars(
            select(EditMemoRecord.id).where(
                EditMemoRecord.source_video_id == source.id
            )
        ).all()
    )
    return SourceProcessingResult(
        source_video_id=source.id,
        processing_status=source.processing_status,
        completed_stages=tuple(
            kind
            for kind in STAGE_ORDER
            if stages[kind].status == ProcessingStageStatus.COMPLETED
        ),
        transcript_id=None if transcript is None else transcript.id,
        memo_count=memo_count,
        warnings=warnings,
    )


def _reset_for_execution(stage: ProcessingStage) -> None:
    stage.status = ProcessingStageStatus.PENDING
    stage.safe_error_code = None
    stage.safe_error_message = None
    stage.input_fingerprint = None
    stage.config_version = None
    stage.tool_version = None
    stage.result_version = None
    stage.result_reference = None
    stage.result_fingerprint = None
    stage.started_at = None
    stage.completed_at = None


def _run_stage(
    *,
    session: Session,
    source: SourceVideo,
    stage: ProcessingStage,
    warnings: list[str],
    operation: Callable[[], Any],
    persist_result: Callable[[Any], None] | None = None,
    complete_source: bool = False,
) -> Any:
    _start_stage(session, source, stage, warnings)
    try:
        result = operation()
    except Exception as error:
        _fail_stage(session, source, stage, warnings)
        raise SourceStageExecutionError(
            stage=stage.stage,
            safe_error_code=f"{stage.stage.value}_FAILED",
            safe_message=f"{stage.stage.value} processing failed.",
            warnings=warnings,
        ) from error

    try:
        if persist_result is not None:
            persist_result(result)
        stage.status = ProcessingStageStatus.COMPLETED
        stage.completed_at = _utc_now()
        if complete_source:
            source.processing_status = SourceVideoStatus.COMPLETED
        session.commit()
    except Exception as error:
        session.rollback()
        _fail_stage(session, source, stage, warnings, code_suffix="PERSISTENCE_FAILED")
        raise SourceProcessingPersistenceError(
            f"Could not persist the {stage.stage.value} stage result.",
            warnings=warnings,
        ) from error
    return result


def _start_stage(
    session: Session,
    source: SourceVideo,
    stage: ProcessingStage,
    warnings: list[str],
) -> None:
    locked_stage = session.scalar(
        select(ProcessingStage)
        .where(ProcessingStage.id == stage.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_stage is None or locked_stage.status != ProcessingStageStatus.PENDING:
        raise SourceProcessingStateError(
            f"{stage.stage.value} must be PENDING before execution.", warnings=warnings
        )
    stage.status = ProcessingStageStatus.RUNNING
    stage.attempt_count += 1
    stage.started_at = _utc_now()
    stage.completed_at = None
    stage.safe_error_code = None
    stage.safe_error_message = None
    stage.input_fingerprint = source.fingerprint
    source.processing_status = SourceVideoStatus.PROCESSING
    try:
        session.commit()
    except Exception as error:
        session.rollback()
        raise SourceProcessingPersistenceError(
            f"Could not persist the {stage.stage.value} RUNNING state.",
            warnings=warnings,
        ) from error


def _fail_stage(
    session: Session,
    source: SourceVideo,
    stage: ProcessingStage,
    warnings: list[str],
    *,
    code_suffix: str = "FAILED",
) -> None:
    stage.status = ProcessingStageStatus.FAILED
    stage.completed_at = _utc_now()
    stage.safe_error_code = f"{stage.stage.value}_{code_suffix}"
    stage.safe_error_message = f"{stage.stage.value} processing failed."
    source.processing_status = SourceVideoStatus.FAILED
    try:
        session.commit()
    except Exception as error:
        session.rollback()
        raise SourceProcessingPersistenceError(
            f"Could not persist the {stage.stage.value} FAILED state.",
            warnings=warnings,
        ) from error


def _probe_and_validate(
    services: SourceProcessingServices, source_path: Path
) -> MediaInfo:
    media_info = services.probe(source_path)
    if not media_info.has_video_stream:
        raise ValueError("Source media has no video stream.")
    if not media_info.has_audio_stream:
        raise ValueError("Source media has no audio stream.")
    return media_info


def _resolve_and_probe(
    storage: SourceStorage,
    services: SourceProcessingServices,
    resource_reference: str,
) -> tuple[Path, MediaInfo]:
    source_path = storage.resolve(resource_reference)
    return source_path, _probe_and_validate(services, source_path)


def _persist_probe_result(source: SourceVideo, media_info: MediaInfo) -> None:
    source.duration_seconds = media_info.duration_seconds
    source.video_codec = media_info.video_codec
    source.audio_codec = media_info.audio_codec
    source.format_name = media_info.format_name


def _new_transcript(source: SourceVideo, result: STTResult) -> None:
    source.transcript = Transcript(
        text=result.text,
        language=result.language,
        language_probability=result.language_probability,
        segments=[
            {
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
                "words": [
                    {
                        "start_seconds": word.start_seconds,
                        "end_seconds": word.end_seconds,
                        "text": word.text,
                        "probability": word.probability,
                    }
                    for word in segment.words
                ],
            }
            for segment in result.segments
        ],
    )


def _stt_result_from_transcript(transcript: Transcript | None) -> STTResult:
    if transcript is None:
        raise SourceProcessingStateError("A valid Transcript is required.")
    try:
        segments = tuple(
            TranscriptSegment(
                start_seconds=float(segment["start_seconds"]),
                end_seconds=float(segment["end_seconds"]),
                text=str(segment["text"]),
                words=tuple(
                    TranscriptWord(
                        start_seconds=float(word["start_seconds"]),
                        end_seconds=float(word["end_seconds"]),
                        text=str(word["text"]),
                        probability=(
                            None
                            if word.get("probability") is None
                            else float(word["probability"])
                        ),
                    )
                    for word in segment["words"]
                ),
            )
            for segment in transcript.segments
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SourceProcessingStateError(
            "Stored Transcript cannot be reconstructed safely."
        ) from error
    return STTResult(
        text=transcript.text,
        segments=segments,
        language=transcript.language,
        language_probability=(
            None
            if transcript.language_probability is None
            else float(transcript.language_probability)
        ),
    )


def _persist_memos(
    session: Session,
    source: SourceVideo,
    transcript: Transcript | None,
    memos: tuple[EditMemo, ...],
) -> None:
    if transcript is None:
        raise SourceProcessingStateError("Transcript persistence is missing.")
    session.add_all(
        EditMemoRecord(
            source_video=source,
            transcript=transcript,
            start_seconds=memo.start_seconds,
            end_seconds=memo.end_seconds,
            transcript_text=memo.transcript_text,
            matched_trigger=memo.matched_trigger,
            matched_reference=memo.matched_reference,
            matched_action=memo.matched_action,
            trigger_match_type=memo.trigger_match_type,
            trigger_similarity=memo.trigger_similarity,
        )
        for memo in memos
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
