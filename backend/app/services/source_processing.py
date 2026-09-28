from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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
from backend.app.services.stt_service import STTResult, transcribe_audio
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import SourceStorage


STAGE_ORDER = (
    ProcessingStageKind.PROBE,
    ProcessingStageKind.AUDIO_EXTRACTION,
    ProcessingStageKind.STT,
    ProcessingStageKind.MEMO_DETECTION,
)


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

    active_services = services or SourceProcessingServices()
    warnings: list[str] = []
    transcript_record: Transcript | None = None
    memo_count = 0

    try:
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

        detected_memos = _run_stage(
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
        memo_count = len(detected_memos)
    finally:
        try:
            workspace.cleanup_source(
                project_id=source.project_id,
                source_video_id=source.id,
            )
        except Exception:
            warnings.append("Could not remove the source temporary workspace.")

    return SourceProcessingResult(
        source_video_id=source.id,
        processing_status=source.processing_status,
        completed_stages=tuple(
            stage
            for stage in STAGE_ORDER
            if stages[stage].status == ProcessingStageStatus.COMPLETED
        ),
        transcript_id=None if transcript_record is None else transcript_record.id,
        memo_count=memo_count,
        warnings=tuple(warnings),
    )


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
    if stage.status != ProcessingStageStatus.PENDING:
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
