from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import base64
import binascii
import zlib
from typing import Callable, Iterable, Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneEvidence,
    SourceVideo,
)


MEMO_GUIDED_DISCOVERY = "MEMO_GUIDED_DISCOVERY"
SEMANTIC_MEMO_PROPOSAL_SELECTION = "SEMANTIC_MEMO_PROPOSAL_SELECTION"
TRANSCRIPT_EVIDENCE = "TRANSCRIPT_EVIDENCE"
AUDIO_EVIDENCE = "AUDIO_EVIDENCE"
VISUAL_EVIDENCE = "VISUAL_EVIDENCE"
AUTONOMOUS_PROMOTION = "AUTONOMOUS_PROMOTION"
EVENT_PAIR_FILTER = "EVENT_PAIR_FILTER"
EVENT_GROUPING = "EVENT_GROUPING"

CANDIDATE_WORK_TYPES = frozenset({MEMO_GUIDED_DISCOVERY, AUTONOMOUS_PROMOTION})
WORK_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    MEMO_GUIDED_DISCOVERY: (),
    SEMANTIC_MEMO_PROPOSAL_SELECTION: (MEMO_GUIDED_DISCOVERY,),
    TRANSCRIPT_EVIDENCE: (),
    AUDIO_EVIDENCE: (),
    VISUAL_EVIDENCE: (),
    AUTONOMOUS_PROMOTION: (
        TRANSCRIPT_EVIDENCE,
        AUDIO_EVIDENCE,
        VISUAL_EVIDENCE,
    ),
    EVENT_PAIR_FILTER: (MEMO_GUIDED_DISCOVERY, AUTONOMOUS_PROMOTION),
    EVENT_GROUPING: (EVENT_PAIR_FILTER,),
}


class SceneResumeReason(str, Enum):
    INPUT_CHANGED = "INPUT_CHANGED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    PRODUCER_CHANGED = "PRODUCER_CHANGED"
    RESULT_MISSING = "RESULT_MISSING"
    RESULT_INVALID = "RESULT_INVALID"
    UPSTREAM_INVALID = "UPSTREAM_INVALID"
    STALE_EXECUTION = "STALE_EXECUTION"
    CONCURRENT_EXECUTION = "CONCURRENT_EXECUTION"
    RETRY_REQUIRED = "RETRY_REQUIRED"
    INPUT_CHANGED_DURING_EXECUTION = "INPUT_CHANGED_DURING_EXECUTION"


@dataclass(frozen=True)
class SceneWorkSpec:
    project_id: UUID
    work_type: str
    input_fingerprint: str
    config_fingerprint: str | None
    producer: str
    producer_version: str
    source_video_id: UUID | None = None
    target_type: str | None = None
    target_id: UUID | None = None


@dataclass(frozen=True)
class SceneResumePlan:
    reusable_work_items: tuple[UUID, ...]
    execution_specs: tuple[SceneWorkSpec, ...]
    retryable_work_items: tuple[UUID, ...]
    invalid_work_items: tuple[UUID, ...]
    blocked_work_items: tuple[UUID, ...]
    stale_work_items: tuple[UUID, ...]
    downstream_invalidations: tuple[str, ...]
    reasons: tuple[tuple[str, SceneResumeReason], ...]

    @property
    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, reason in self.reasons:
            counts[reason.value] = counts.get(reason.value, 0) + 1
        return counts


class SceneWorkStateError(RuntimeError):
    """Safe Scene work execution state failure."""


def work_result_is_valid(session: Session, work: SceneAnalysisWorkItem) -> bool:
    if work.status is not SceneAnalysisWorkStatus.COMPLETED:
        return False
    if not work.result_fingerprint or not work.result_reference:
        return False
    if work.work_type == MEMO_GUIDED_DISCOVERY:
        if work.result_reference.startswith("abstain:"):
            return work.result_reference.split(":", 1)[1] in {
                "AMBIGUOUS", "NO_MATCH", "INSUFFICIENT_EVIDENCE", "UNSUPPORTED"
            }
        if not work.result_reference.startswith("candidate:"):
            return False
        links = _result_candidate_ids(session, work.id)
        return len(links) == 1 and _candidate_result_is_complete(session, links[0])
    if work.work_type == AUTONOMOUS_PROMOTION:
        links = _result_candidate_ids(session, work.id)
        expected = _count_reference(work.result_reference, "autonomous:candidates:")
        return expected is not None and expected == len(links) and all(
            _candidate_result_is_complete(session, candidate_id) for candidate_id in links
        )
    if work.work_type in {TRANSCRIPT_EVIDENCE, AUDIO_EVIDENCE, VISUAL_EVIDENCE}:
        if _count_reference(work.result_reference, "evidence-count:") is not None:
            return True
        try:
            if work.result_reference.startswith("zlib:"):
                payload = json.loads(
                    zlib.decompress(
                        base64.b64decode(work.result_reference[5:])
                    ).decode("utf-8")
                )
            else:
                payload = json.loads(work.result_reference)
        except (TypeError, ValueError, zlib.error, binascii.Error):
            return False
        return payload.get("schema") == "autonomous-modality-result-v0.1" and isinstance(
            payload.get("evidences"), list
        )
    if work.work_type == SEMANTIC_MEMO_PROPOSAL_SELECTION:
        try:
            payload = json.loads(work.result_reference)
        except (TypeError, ValueError):
            return False
        return payload.get("semantic_status") in {
            "SELECTED", "AMBIGUOUS", "NO_MATCH", "INSUFFICIENT_EVIDENCE"
        }
    if work.work_type in {EVENT_PAIR_FILTER, EVENT_GROUPING}:
        try:
            return isinstance(json.loads(work.result_reference), dict)
        except (TypeError, ValueError):
            return False
    return True


def determine_scene_resume_plan(
    session: Session,
    specs: Iterable[SceneWorkSpec],
    *,
    stale_before: datetime | None = None,
) -> SceneResumePlan:
    reusable: list[UUID] = []
    execute: list[SceneWorkSpec] = []
    retryable: list[UUID] = []
    invalid: list[UUID] = []
    blocked: list[UUID] = []
    stale: list[UUID] = []
    downstream: set[str] = set()
    reasons: list[tuple[str, SceneResumeReason]] = []
    for spec in specs:
        rows = session.scalars(_work_query(spec)).all()
        exact = next((row for row in rows if _matches_spec(row, spec)), None)
        if exact is None:
            execute.append(spec)
            if rows:
                reason = _mismatch_reason(rows[0], spec)
                invalid.append(rows[0].id)
                reasons.append((spec.work_type, reason))
                downstream.update(_downstream(spec.work_type))
            continue
        if exact.status is SceneAnalysisWorkStatus.COMPLETED:
            if work_result_is_valid(session, exact):
                reusable.append(exact.id)
            else:
                invalid.append(exact.id)
                execute.append(spec)
                reasons.append((spec.work_type, SceneResumeReason.RESULT_INVALID))
                downstream.update(_downstream(spec.work_type))
        elif exact.status is SceneAnalysisWorkStatus.RUNNING:
            latest = _latest_attempt(session, exact.id)
            if stale_before is not None and latest and _aware(latest.started_at) <= _aware(stale_before):
                stale.append(exact.id)
                reasons.append((spec.work_type, SceneResumeReason.STALE_EXECUTION))
            else:
                blocked.append(exact.id)
                reasons.append((spec.work_type, SceneResumeReason.CONCURRENT_EXECUTION))
        elif exact.status is SceneAnalysisWorkStatus.FAILED:
            retryable.append(exact.id)
            reasons.append((spec.work_type, SceneResumeReason.RETRY_REQUIRED))
        else:
            execute.append(spec)
    return SceneResumePlan(
        tuple(reusable), tuple(execute), tuple(retryable), tuple(invalid),
        tuple(blocked), tuple(stale), tuple(sorted(downstream)), tuple(reasons)
    )


def recover_stale_scene_work(
    session: Session, work_item_id: UUID, *, stale_before: datetime
) -> None:
    work = session.scalar(
        select(SceneAnalysisWorkItem)
        .where(SceneAnalysisWorkItem.id == work_item_id)
        .with_for_update()
    )
    if work is None or work.status is not SceneAnalysisWorkStatus.RUNNING:
        raise SceneWorkStateError("Only a RUNNING Scene work item can be recovered.")
    attempt = _latest_attempt(session, work.id, for_update=True)
    if attempt is None or attempt.status is not SceneAnalysisAttemptStatus.RUNNING:
        raise SceneWorkStateError("RUNNING Scene work is missing its RUNNING attempt.")
    if _aware(attempt.started_at) > _aware(stale_before):
        raise SceneWorkStateError("Scene work is newer than the stale cutoff.")
    now = datetime.now(timezone.utc)
    work.status = SceneAnalysisWorkStatus.FAILED
    attempt.status = SceneAnalysisAttemptStatus.FAILED
    attempt.completed_at = now
    attempt.safe_error_code = "STALE_EXECUTION_RECOVERED"
    attempt.safe_error_message = "Stale Scene execution was recovered for explicit retry."
    session.commit()


def start_scene_work_retry(
    session: Session, work_item_id: UUID
) -> SceneAnalysisAttempt:
    work = session.scalar(
        select(SceneAnalysisWorkItem)
        .where(SceneAnalysisWorkItem.id == work_item_id)
        .with_for_update()
    )
    if work is None or work.status is not SceneAnalysisWorkStatus.FAILED:
        raise SceneWorkStateError("Only a FAILED Scene work item can be retried.")
    number = session.scalar(
        select(func.coalesce(func.max(SceneAnalysisAttempt.attempt_number), 0)).where(
            SceneAnalysisAttempt.work_item_id == work.id
        )
    )
    attempt = SceneAnalysisAttempt(
        work_item_id=work.id,
        attempt_number=int(number or 0) + 1,
        status=SceneAnalysisAttemptStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    work.status = SceneAnalysisWorkStatus.RUNNING
    session.add(attempt)
    session.commit()
    return attempt


def lock_scene_parent(session: Session, spec: SceneWorkSpec) -> Project | SourceVideo:
    model = SourceVideo if spec.source_video_id is not None else Project
    identity = spec.source_video_id if spec.source_video_id is not None else spec.target_id
    if identity is None:
        raise SceneWorkStateError("Scene work has no lockable parent identity.")
    row = session.scalar(select(model).where(model.id == identity).with_for_update())
    if row is None:
        raise SceneWorkStateError("Scene work parent does not exist.")
    return row


def claim_scene_work(
    session: Session, spec: SceneWorkSpec
) -> tuple[SceneAnalysisWorkItem, SceneAnalysisAttempt, bool]:
    """Claim one exact work specification under its Source/Project parent lock."""
    lock_scene_parent(session, spec)
    existing = session.scalar(
        _work_query(spec)
        .where(
            SceneAnalysisWorkItem.input_fingerprint == spec.input_fingerprint,
            SceneAnalysisWorkItem.config_fingerprint == spec.config_fingerprint,
            SceneAnalysisWorkItem.producer == spec.producer,
            SceneAnalysisWorkItem.producer_version == spec.producer_version,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.status is SceneAnalysisWorkStatus.COMPLETED and work_result_is_valid(
            session, existing
        ):
            attempt = _latest_attempt(session, existing.id)
            if attempt is None:
                raise SceneWorkStateError("Completed Scene work is missing its attempt.")
            session.commit()
            return existing, attempt, False
        if existing.status is SceneAnalysisWorkStatus.RUNNING:
            session.rollback()
            raise SceneWorkStateError(SceneResumeReason.CONCURRENT_EXECUTION.value)
        if existing.status is SceneAnalysisWorkStatus.FAILED:
            session.rollback()
            raise SceneWorkStateError(SceneResumeReason.RETRY_REQUIRED.value)
    work = SceneAnalysisWorkItem(
        project_id=spec.project_id,
        source_video_id=spec.source_video_id,
        work_type=spec.work_type,
        target_type=spec.target_type,
        target_id=spec.target_id,
        status=SceneAnalysisWorkStatus.RUNNING,
        input_fingerprint=spec.input_fingerprint,
        config_fingerprint=spec.config_fingerprint,
        producer=spec.producer,
        producer_version=spec.producer_version,
    )
    attempt = SceneAnalysisAttempt(
        work_item=work,
        attempt_number=1,
        status=SceneAnalysisAttemptStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    session.add_all([work, attempt])
    session.commit()
    return work, attempt, True


def active_candidate_ids(session: Session, project_id: UUID) -> tuple[UUID, ...]:
    works = session.scalars(
        select(SceneAnalysisWorkItem)
        .where(
            SceneAnalysisWorkItem.project_id == project_id,
            SceneAnalysisWorkItem.status == SceneAnalysisWorkStatus.COMPLETED,
            SceneAnalysisWorkItem.work_type.in_(CANDIDATE_WORK_TYPES),
        )
        .order_by(SceneAnalysisWorkItem.created_at.desc(), SceneAnalysisWorkItem.id.desc())
    ).all()
    latest_keys: set[tuple[object, ...]] = set()
    active: set[UUID] = set()
    for work in works:
        key = (work.work_type, work.source_video_id, work.target_type, work.target_id)
        if key in latest_keys:
            continue
        latest_keys.add(key)
        if work_result_is_valid(session, work):
            active.update(_result_candidate_ids(session, work.id))
    return tuple(sorted(active, key=lambda value: value.hex))


def snapshot_still_matches(expected: str, current_factory: Callable[[], str]) -> None:
    if current_factory() != expected:
        raise SceneWorkStateError(SceneResumeReason.INPUT_CHANGED_DURING_EXECUTION.value)


def _work_query(spec: SceneWorkSpec):
    query = select(SceneAnalysisWorkItem).where(
        SceneAnalysisWorkItem.project_id == spec.project_id,
        SceneAnalysisWorkItem.work_type == spec.work_type,
        SceneAnalysisWorkItem.source_video_id.is_(spec.source_video_id)
        if spec.source_video_id is None
        else SceneAnalysisWorkItem.source_video_id == spec.source_video_id,
        SceneAnalysisWorkItem.target_type.is_(spec.target_type)
        if spec.target_type is None
        else SceneAnalysisWorkItem.target_type == spec.target_type,
        SceneAnalysisWorkItem.target_id.is_(spec.target_id)
        if spec.target_id is None
        else SceneAnalysisWorkItem.target_id == spec.target_id,
    )
    return query.order_by(SceneAnalysisWorkItem.created_at.desc())


def _matches_spec(work: SceneAnalysisWorkItem, spec: SceneWorkSpec) -> bool:
    return (
        work.input_fingerprint == spec.input_fingerprint
        and work.config_fingerprint == spec.config_fingerprint
        and work.producer == spec.producer
        and work.producer_version == spec.producer_version
    )


def _mismatch_reason(work: SceneAnalysisWorkItem, spec: SceneWorkSpec) -> SceneResumeReason:
    if work.input_fingerprint != spec.input_fingerprint:
        return SceneResumeReason.INPUT_CHANGED
    if work.config_fingerprint != spec.config_fingerprint:
        return SceneResumeReason.CONFIG_CHANGED
    return SceneResumeReason.PRODUCER_CHANGED


def _downstream(work_type: str) -> set[str]:
    result: set[str] = set()
    frontier = [work_type]
    while frontier:
        parent = frontier.pop()
        for child, dependencies in WORK_DEPENDENCIES.items():
            if parent in dependencies and child not in result:
                result.add(child)
                frontier.append(child)
    return result


def _result_candidate_ids(session: Session, work_id: UUID) -> tuple[UUID, ...]:
    return tuple(
        session.scalars(
            select(SceneAnalysisWorkResultCandidate.scene_candidate_id)
            .where(SceneAnalysisWorkResultCandidate.work_item_id == work_id)
            .order_by(SceneAnalysisWorkResultCandidate.scene_candidate_id)
        )
    )


def _candidate_result_is_complete(session: Session, candidate_id: UUID) -> bool:
    candidate = session.get(SceneCandidate, candidate_id)
    if candidate is None:
        return False
    return session.scalar(
        select(func.count(SceneEvidence.id)).where(
            SceneEvidence.scene_candidate_id == candidate_id
        )
    ) > 0


def _count_reference(value: str, prefix: str) -> int | None:
    if not value.startswith(prefix):
        return None
    try:
        return int(value[len(prefix):])
    except ValueError:
        return None


def _latest_attempt(
    session: Session, work_id: UUID, *, for_update: bool = False
) -> SceneAnalysisAttempt | None:
    query = (
        select(SceneAnalysisAttempt)
        .where(SceneAnalysisAttempt.work_item_id == work_id)
        .order_by(SceneAnalysisAttempt.attempt_number.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
