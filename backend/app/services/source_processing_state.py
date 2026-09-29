from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models import (
    EditMemo,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)


STAGE_ORDER = (
    ProcessingStageKind.PROBE,
    ProcessingStageKind.AUDIO_EXTRACTION,
    ProcessingStageKind.STT,
    ProcessingStageKind.MEMO_DETECTION,
)


class ResumeReason(str, Enum):
    PENDING = "PENDING"
    FAILED = "FAILED"
    INVALID_RESULT = "INVALID_RESULT"
    EPHEMERAL_AUDIO_REQUIRED = "EPHEMERAL_AUDIO_REQUIRED"
    STALE_RUNNING_BLOCKED = "STALE_RUNNING_BLOCKED"


@dataclass(frozen=True)
class StageVersionExpectation:
    config_version: str | None = None
    tool_version: str | None = None
    result_version: str | None = None


@dataclass(frozen=True)
class SourceResumePlan:
    source_video_id: UUID
    reusable_stages: tuple[ProcessingStageKind, ...]
    execution_stages: tuple[ProcessingStageKind, ...]
    invalid_stages: tuple[ProcessingStageKind, ...]
    stale_stages: tuple[ProcessingStageKind, ...]
    reasons: tuple[tuple[ProcessingStageKind, ResumeReason], ...]

    @property
    def start_stage(self) -> ProcessingStageKind | None:
        return self.execution_stages[0] if self.execution_stages else None


class SourceStateError(RuntimeError):
    """Raised when persisted SourceVideo processing state is inconsistent."""


def determine_resume_plan(
    *,
    session: Session,
    source_video_id: UUID,
    version_expectations: Mapping[
        ProcessingStageKind, StageVersionExpectation
    ] | None = None,
) -> SourceResumePlan:
    source, stages = load_source_state(session, source_video_id)
    expectations = version_expectations or {}
    reusable: list[ProcessingStageKind] = []
    invalid: list[ProcessingStageKind] = []
    stale: list[ProcessingStageKind] = []
    reasons: list[tuple[ProcessingStageKind, ResumeReason]] = []
    first_execution_index: int | None = None

    for index, kind in enumerate(STAGE_ORDER):
        stage = stages[kind]
        if first_execution_index is not None:
            invalid.append(kind)
            continue
        if stage.status == ProcessingStageStatus.RUNNING:
            stale.append(kind)
            reasons.append((kind, ResumeReason.STALE_RUNNING_BLOCKED))
            first_execution_index = index
            invalid.append(kind)
            continue
        if stage.status == ProcessingStageStatus.PENDING:
            reasons.append((kind, ResumeReason.PENDING))
            first_execution_index = index
            invalid.append(kind)
            continue
        if stage.status == ProcessingStageStatus.FAILED:
            reasons.append((kind, ResumeReason.FAILED))
            first_execution_index = index
            invalid.append(kind)
            continue
        if stage.status != ProcessingStageStatus.COMPLETED or not stage_result_is_valid(
            source=source,
            stage=stage,
            expectation=expectations.get(kind),
        ):
            reasons.append((kind, ResumeReason.INVALID_RESULT))
            first_execution_index = index
            invalid.append(kind)
            continue
        reusable.append(kind)

    if first_execution_index is None:
        execution: tuple[ProcessingStageKind, ...] = ()
    else:
        execution_start = first_execution_index
        if execution_start == STAGE_ORDER.index(ProcessingStageKind.STT):
            execution_start = min(
                execution_start, STAGE_ORDER.index(ProcessingStageKind.AUDIO_EXTRACTION)
            )
            if ProcessingStageKind.AUDIO_EXTRACTION in reusable:
                reusable.remove(ProcessingStageKind.AUDIO_EXTRACTION)
                reasons.append(
                    (
                        ProcessingStageKind.AUDIO_EXTRACTION,
                        ResumeReason.EPHEMERAL_AUDIO_REQUIRED,
                    )
                )
        execution = STAGE_ORDER[execution_start:]
        reusable = [kind for kind in reusable if kind not in execution]

    return SourceResumePlan(
        source_video_id=source.id,
        reusable_stages=tuple(reusable),
        execution_stages=execution,
        invalid_stages=tuple(invalid),
        stale_stages=tuple(stale),
        reasons=tuple(reasons),
    )


def stage_result_is_valid(
    *,
    source: SourceVideo,
    stage: ProcessingStage,
    expectation: StageVersionExpectation | None = None,
) -> bool:
    if stage.status != ProcessingStageStatus.COMPLETED:
        return False
    if not source.fingerprint or stage.input_fingerprint != source.fingerprint:
        return False
    if expectation is not None and not _versions_match(stage, expectation):
        return False
    if stage.stage == ProcessingStageKind.PROBE:
        return (
            source.duration_seconds is not None
            and float(source.duration_seconds) >= 0
            and bool(source.video_codec)
            and bool(source.audio_codec)
            and bool(source.format_name)
        )
    if stage.stage == ProcessingStageKind.AUDIO_EXTRACTION:
        return True
    if stage.stage == ProcessingStageKind.STT:
        return _transcript_is_valid(source.transcript)
    if stage.stage == ProcessingStageKind.MEMO_DETECTION:
        return _transcript_is_valid(source.transcript) and all(
            memo.transcript_id == source.transcript.id for memo in source.edit_memos
        )
    return False


def invalidate_from_stage(
    *,
    session: Session,
    source_video_id: UUID,
    from_stage: ProcessingStageKind,
) -> None:
    source, stages = load_source_state(session, source_video_id)
    if any(stage.status == ProcessingStageStatus.RUNNING for stage in stages.values()):
        raise SourceStateError(
            "RUNNING stages must be explicitly recovered before invalidation."
        )

    start_index = STAGE_ORDER.index(from_stage)
    affected = STAGE_ORDER[start_index:]
    if from_stage == ProcessingStageKind.PROBE:
        source.duration_seconds = None
        source.video_codec = None
        source.audio_codec = None
        source.format_name = None
        source.width = None
        source.height = None
        source.fps = None
    if start_index <= STAGE_ORDER.index(ProcessingStageKind.STT):
        session.execute(
            delete(EditMemo).where(EditMemo.source_video_id == source.id)
        )
        session.execute(delete(Transcript).where(Transcript.source_video_id == source.id))
    elif from_stage == ProcessingStageKind.MEMO_DETECTION:
        session.execute(
            delete(EditMemo).where(EditMemo.source_video_id == source.id)
        )

    for kind in affected:
        _reset_stage(stages[kind])
    source.processing_status = SourceVideoStatus.READY
    session.commit()
    session.expire(source)


def recover_stale_running_stage(
    *,
    session: Session,
    source_video_id: UUID,
    stage_kind: ProcessingStageKind,
    stale_before: datetime,
) -> None:
    source, stages = load_source_state(session, source_video_id)
    stage = stages[stage_kind]
    if stage.status != ProcessingStageStatus.RUNNING:
        raise SourceStateError("Only a RUNNING stage can be recovered as stale.")
    if stage.started_at is None:
        raise SourceStateError("RUNNING stage has no started_at timestamp.")
    if _aware(stage.started_at) > _aware(stale_before):
        raise SourceStateError("RUNNING stage is newer than the stale cutoff.")

    stage.status = ProcessingStageStatus.FAILED
    stage.safe_error_code = "STALE_EXECUTION_RECOVERED"
    stage.safe_error_message = "Stale execution was recovered for explicit retry."
    stage.completed_at = datetime.now(timezone.utc)
    source.processing_status = SourceVideoStatus.FAILED
    session.commit()


def load_source_state(
    session: Session, source_video_id: UUID
) -> tuple[SourceVideo, dict[ProcessingStageKind, ProcessingStage]]:
    source = session.get(SourceVideo, source_video_id)
    if source is None:
        raise SourceStateError("The SourceVideo does not exist.")
    session.expire(source, ["transcript", "edit_memos"])
    rows = session.scalars(
        select(ProcessingStage).where(
            ProcessingStage.source_video_id == source_video_id
        )
    ).all()
    stages = {row.stage: row for row in rows}
    if set(stages) != set(STAGE_ORDER):
        raise SourceStateError("SourceVideo processing stages are incomplete.")
    return source, stages


def _versions_match(
    stage: ProcessingStage, expectation: StageVersionExpectation
) -> bool:
    return all(
        expected is None or actual == expected
        for actual, expected in (
            (stage.config_version, expectation.config_version),
            (stage.tool_version, expectation.tool_version),
            (stage.result_version, expectation.result_version),
        )
    )


def _transcript_is_valid(transcript: Transcript | None) -> bool:
    if transcript is None or not isinstance(transcript.text, str):
        return False
    if not isinstance(transcript.language, str) or not transcript.language:
        return False
    if not isinstance(transcript.segments, list):
        return False
    return all(_segment_is_valid(segment) for segment in transcript.segments)


def _segment_is_valid(segment: Any) -> bool:
    if not isinstance(segment, dict):
        return False
    try:
        start = float(segment["start_seconds"])
        end = float(segment["end_seconds"])
    except (KeyError, TypeError, ValueError):
        return False
    words = segment.get("words")
    return (
        start >= 0
        and end >= start
        and isinstance(segment.get("text"), str)
        and isinstance(words, list)
        and all(_word_is_valid(word) for word in words)
    )


def _word_is_valid(word: Any) -> bool:
    if not isinstance(word, dict):
        return False
    try:
        start = float(word["start_seconds"])
        end = float(word["end_seconds"])
    except (KeyError, TypeError, ValueError):
        return False
    return start >= 0 and end >= start and isinstance(word.get("text"), str)


def _reset_stage(stage: ProcessingStage) -> None:
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
