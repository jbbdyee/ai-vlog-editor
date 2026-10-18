"""Read-only, conservative diagnostics from durable autonomous work results."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import product
from math import isfinite
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    Project, SceneAnalysisAttempt, SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus, SourceVideo,
)
from backend.app.services.autonomous_discovery import (
    AUDIO_WORK, DEFAULT_CONFIG, PROMOTION_WORK, TRANSCRIPT_WORK, VISUAL_WORK, _decode_analysis,
)
from backend.app.services.scene_fingerprints import canonical_fingerprint
from backend.app.services.scene_processing_state import work_result_is_valid


class SceneDiagnosticsProjectNotFoundError(LookupError):
    pass


_MODALITY_WORKS = (TRANSCRIPT_WORK, AUDIO_WORK, VISUAL_WORK)
_MODALITIES = ("TRANSCRIPT", "AUDIO", "VISUAL", "QUALITY")
_SAFE_CODE = re.compile(r"[A-Z0-9_]{1,80}\Z")


@dataclass(frozen=True)
class EvidenceIntervalDiagnostic:
    modality: str
    evidence_type: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class SourceSceneDiagnostic:
    source_video_id: UUID
    status: str
    has_record: bool
    candidate_count: int | None
    abstain_reason: str | None
    evidence_counts: dict[str, int | None]
    evidence_type_counts: dict[str, int]
    evidence_intervals: tuple[EvidenceIntervalDiagnostic, ...]
    warnings: tuple[str, ...]


def list_project_scene_diagnostics(
    session: Session, project_id: UUID
) -> tuple[SourceSceneDiagnostic, ...]:
    if session.get(Project, project_id) is None:
        raise SceneDiagnosticsProjectNotFoundError
    sources = session.scalars(
        select(SourceVideo).where(SourceVideo.project_id == project_id).order_by(SourceVideo.created_at, SourceVideo.id)
    ).all()
    works = session.scalars(
        select(SceneAnalysisWorkItem).where(
            SceneAnalysisWorkItem.project_id == project_id,
            SceneAnalysisWorkItem.source_video_id.in_([source.id for source in sources]),
            SceneAnalysisWorkItem.work_type.in_((*_MODALITY_WORKS, PROMOTION_WORK)),
        )
    ).all() if sources else []
    by_source: dict[UUID, list[SceneAnalysisWorkItem]] = {}
    for work in works:
        by_source.setdefault(work.source_video_id, []).append(work)
    return tuple(_diagnose_source(session, source, by_source.get(source.id, [])) for source in sources)


def _diagnose_source(session: Session, source: SourceVideo, works: list[SceneAnalysisWorkItem]) -> SourceSceneDiagnostic:
    empty_counts = dict.fromkeys(_MODALITIES)
    if not works:
        return SourceSceneDiagnostic(source.id, "NOT_ANALYZED", False, None, "UNKNOWN", empty_counts, {}, (), ())

    promotions = sorted((w for w in works if w.work_type == PROMOTION_WORK), key=_work_order, reverse=True)
    promotion = promotions[0] if promotions else None
    modality_works = {kind: sorted((w for w in works if w.work_type == kind), key=_work_order, reverse=True)
                      for kind in _MODALITY_WORKS}
    selected = _matching_modalities(session, promotion, modality_works) if promotion else None
    if selected is None:
        # Without a matching promotion fingerprint, these records cannot be
        # attributed to the same analysis. Never report their absence as zero.
        status = "RUNNING" if any(w.status is SceneAnalysisWorkStatus.RUNNING for w in works) else "UNKNOWN"
        if promotion and promotion.status is SceneAnalysisWorkStatus.FAILED:
            status = "FAILED"
        elif not promotion and all(modality_works[kind] and modality_works[kind][0].status is SceneAnalysisWorkStatus.FAILED
                                   for kind in _MODALITY_WORKS):
            status = "FAILED"
        warnings = _failure_codes(session, [promotion] if promotion else [rows[0] for rows in modality_works.values() if rows])
        return SourceSceneDiagnostic(source.id, status, True, None, "UNKNOWN", empty_counts, {}, (), warnings)

    facts = []
    counts: dict[str, int | None] = {key: 0 for key in _MODALITIES}
    warnings = list(_failure_codes(session, selected))
    incomplete = False
    for work in selected:
        if work.status is SceneAnalysisWorkStatus.FAILED:
            counts[{TRANSCRIPT_WORK: "TRANSCRIPT", AUDIO_WORK: "AUDIO", VISUAL_WORK: "VISUAL"}[work.work_type]] = None
            continue
        analysis = _decode_analysis(work.result_reference) if work.status is SceneAnalysisWorkStatus.COMPLETED else None
        if analysis is None:
            incomplete = True
            counts[{TRANSCRIPT_WORK: "TRANSCRIPT", AUDIO_WORK: "AUDIO", VISUAL_WORK: "VISUAL"}[work.work_type]] = None
            continue
        for fact in analysis.evidences:
            interval = fact.interval
            if (interval.source_video_id != source.id or not isfinite(interval.start_seconds)
                or not isfinite(interval.end_seconds) or interval.start_seconds < 0
                or interval.start_seconds >= interval.end_seconds
                or source.duration_seconds is None or interval.end_seconds > float(source.duration_seconds)
                or _SAFE_CODE.fullmatch(fact.evidence_type) is None):
                incomplete = True
                continue
            counts[fact.modality.value] += 1
            facts.append(fact)
        warnings.extend(value for value in analysis.warnings
                        if isinstance(value, str) and _SAFE_CODE.fullmatch(value))

    type_counts = dict(sorted(Counter(f.evidence_type for f in facts).items()))
    intervals = tuple(EvidenceIntervalDiagnostic(f.modality.value, f.evidence_type,
                                                  f.interval.start_seconds, f.interval.end_seconds) for f in facts)
    if promotion.status is SceneAnalysisWorkStatus.RUNNING:
        status, candidate_count, reason = "RUNNING", None, "UNKNOWN"
    elif promotion.status is SceneAnalysisWorkStatus.FAILED:
        status, candidate_count, reason = "FAILED", None, "UNKNOWN"
    elif not work_result_is_valid(session, promotion):
        status, candidate_count, reason = "UNKNOWN", None, "UNKNOWN"
    else:
        candidate_count = session.query(SceneAnalysisWorkResultCandidate).filter_by(work_item_id=promotion.id).count()
        status = "COMPLETED" if candidate_count else "ABSTAINED"
        reason = None if candidate_count else _abstain_reason(facts, selected, incomplete)
    return SourceSceneDiagnostic(source.id, status, True, candidate_count, reason, counts,
                                 type_counts, intervals, tuple(sorted(set(warnings))))


def _matching_modalities(session: Session, promotion: SceneAnalysisWorkItem,
                         by_type: dict[str, list[SceneAnalysisWorkItem]]) -> tuple[SceneAnalysisWorkItem, ...] | None:
    choices = [rows[:20] for rows in by_type.values()]
    if any(not rows for rows in choices):
        return None
    fingerprints_by_work = {}
    for rows in choices:
        for work in rows:
            if work.result_fingerprint:
                fingerprints_by_work[work.id] = work.result_fingerprint
            else:
                code = _failure_codes(session, [work])
                fingerprints_by_work[work.id] = canonical_fingerprint(
                    {"work_type": work.work_type, "warning": code[0] if code else None}
                )
    for combination in product(*choices):
        fingerprints = {work.work_type: fingerprints_by_work[work.id] for work in combination}
        if canonical_fingerprint({"modality_results": fingerprints}) == promotion.input_fingerprint:
            return combination
    return None


def _failure_codes(session: Session, works: list[SceneAnalysisWorkItem]) -> tuple[str, ...]:
    codes = []
    for work in works:
        if work.status is not SceneAnalysisWorkStatus.FAILED:
            continue
        attempts = session.scalars(
            select(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id == work.id)
            .order_by(SceneAnalysisAttempt.attempt_number.desc())
        ).all()
        if attempts and attempts[0].safe_error_code and _SAFE_CODE.fullmatch(attempts[0].safe_error_code):
            codes.append(attempts[0].safe_error_code)
    return tuple(sorted(set(codes)))


def _abstain_reason(facts, selected, incomplete: bool) -> str:
    if incomplete or len(facts) > DEFAULT_CONFIG.maximum_manifest_intervals:
        return "UNKNOWN"
    if any(work.status is SceneAnalysisWorkStatus.FAILED for work in selected):
        return "PARTIAL_ANALYZER_FAILURE"
    if not facts:
        return "NO_EVIDENCE"
    signal_modalities = {fact.modality.value for fact in facts if fact.modality.value in {"TRANSCRIPT", "AUDIO", "VISUAL"}}
    if len(signal_modalities) <= 1:
        return "SINGLE_MODALITY"
    allowed_pairs = []
    for index, left in enumerate(facts):
        for right in facts[index + 1:]:
            types = {left.evidence_type, right.evidence_type}
            modalities = {left.modality.value, right.modality.value}
            if (("TRANSCRIPT_REACTION_CUE" in types and "AUDIO" in modalities)
                or {"TRANSCRIPT_STRUCTURE", "AUDIO_ACTIVITY"} <= types
                or {"AUDIO_ACTIVITY", "VISUAL_ACTIVITY"} <= types):
                allowed_pairs.append((left, right))
    if not allowed_pairs:
        return "UNSUPPORTED_COMBINATION"
    if all(max(a.interval.start_seconds, b.interval.start_seconds) >= min(a.interval.end_seconds, b.interval.end_seconds)
           for a, b in allowed_pairs):
        return "NO_TEMPORAL_OVERLAP"
    return "OTHER_RULE_ABSTAIN"


def _work_order(work: SceneAnalysisWorkItem):
    return work.created_at, str(work.id)
