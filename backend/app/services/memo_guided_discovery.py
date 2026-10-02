from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import re
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    EditMemo,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
)


PARSER_VERSION = "memo-intent-v0.1"
PROPOSAL_VERSION = "memo-proposals-v0.1"
SELECTOR_VERSION = "deterministic-selector-v0.1"
WORK_TYPE = "MEMO_GUIDED_DISCOVERY"
TARGET_TYPE = "EDIT_MEMO"


class MemoAction(str, Enum):
    KEEP = "KEEP"
    UNKNOWN = "UNKNOWN"


class TemporalReference(str, Enum):
    JUST_NOW = "JUST_NOW"
    EARLIER = "EARLIER"
    UNKNOWN = "UNKNOWN"


class IntentParseStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class ProposalType(str, Enum):
    TRANSCRIPT_BLOCK = "TRANSCRIPT_BLOCK"
    FIXED_WINDOW = "FIXED_WINDOW"
    CONTEXT_EXPANDED = "CONTEXT_EXPANDED"
    ADJACENT_SEGMENT = "ADJACENT_SEGMENT"


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class MemoGuidedDiscoveryError(RuntimeError):
    """A safe application-level discovery failure."""


class SelectionValidationError(MemoGuidedDiscoveryError):
    """The selector returned data outside the supplied proposal manifest."""


@dataclass(frozen=True)
class MemoGuidedSearchConfig:
    just_now_lookback_seconds: float = 30.0
    earlier_lookback_seconds: float = 120.0
    fixed_window_seconds: tuple[float, ...] = (5.0, 10.0, 15.0, 30.0)
    transcript_gap_seconds: float = 2.0
    context_expansion_seconds: float = 2.0
    just_now_max_gap_seconds: float = 2.0
    proposal_budget: int = 12


DEFAULT_CONFIG = MemoGuidedSearchConfig()


@dataclass(frozen=True)
class MemoIntent:
    source_memo_id: UUID
    action: MemoAction
    temporal_reference: TemporalReference
    semantic_reference: str | None
    parse_status: IntentParseStatus
    parser: str = "structured-edit-memo-parser"
    parser_version: str = PARSER_VERSION


@dataclass(frozen=True)
class TemporalSearchRegion:
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    reference_type: TemporalReference
    producer: str = "memo-temporal-search"
    producer_version: str = PARSER_VERSION


@dataclass(frozen=True)
class SceneProposal:
    proposal_id: str
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    proposal_type: ProposalType
    producer: str
    producer_version: str
    evidence_refs: tuple[str, ...]
    metadata: dict[str, object]
    config_fingerprint: str


@dataclass(frozen=True)
class SemanticSelection:
    status: SelectionStatus
    selected_proposal_id: str | None
    confidence: float | None
    reason_code: str
    summary: str | None
    selector: str = "deterministic-rule-chain"
    selector_version: str = SELECTOR_VERSION


class SemanticSelector(Protocol):
    def select(
        self,
        intent: MemoIntent,
        search_region: TemporalSearchRegion,
        proposals: tuple[SceneProposal, ...],
        transcript_context: dict[str, str],
    ) -> SemanticSelection: ...


@dataclass(frozen=True)
class MemoGuidedDiscoveryResult:
    work_item_id: UUID
    attempt_id: UUID
    source_video_id: UUID
    memo_id: UUID
    selection_status: SelectionStatus
    reason_code: str
    proposal_count: int
    candidate_id: UUID | None
    reused_candidate: bool


def parse_memo_intent(memo: EditMemo) -> MemoIntent:
    if not isinstance(memo, EditMemo) or memo.id is None:
        raise MemoGuidedDiscoveryError("Edit memo is malformed.")
    action_value = (memo.matched_action or "").strip()
    reference_value = (memo.matched_reference or "").strip()
    action = MemoAction.KEEP if action_value in {"살려줘", "살려", "keep"} else MemoAction.UNKNOWN
    if reference_value in {"방금", "지금", "바로 전"}:
        reference = TemporalReference.JUST_NOW
    elif reference_value in {"아까", "이전에", "전에"}:
        reference = TemporalReference.EARLIER
    else:
        reference = TemporalReference.UNKNOWN
    status = (
        IntentParseStatus.SUPPORTED
        if action is MemoAction.KEEP and reference is not TemporalReference.UNKNOWN
        else IntentParseStatus.UNSUPPORTED
    )
    return MemoIntent(
        source_memo_id=memo.id,
        action=action,
        temporal_reference=reference,
        semantic_reference=None,
        parse_status=status,
    )


def build_search_region(
    *,
    source_video_id: UUID,
    memo_start_seconds: float,
    duration_seconds: float,
    reference: TemporalReference,
    config: MemoGuidedSearchConfig = DEFAULT_CONFIG,
) -> TemporalSearchRegion:
    duration = _positive(duration_seconds, "Source duration")
    memo_start = _number(memo_start_seconds, "Memo start")
    if memo_start <= 0 or memo_start > duration:
        raise MemoGuidedDiscoveryError("Memo start is outside the source duration.")
    if reference is TemporalReference.JUST_NOW:
        lookback = config.just_now_lookback_seconds
    elif reference is TemporalReference.EARLIER:
        lookback = config.earlier_lookback_seconds
    else:
        raise MemoGuidedDiscoveryError("Unknown temporal reference has no search region.")
    return TemporalSearchRegion(
        source_video_id=source_video_id,
        start_seconds=max(0.0, memo_start - _positive(lookback, "Lookback")),
        end_seconds=min(duration, memo_start),
        reference_type=reference,
    )


def generate_scene_proposals(
    *,
    source_video_id: UUID,
    transcript_segments: list[dict[str, object]],
    search_region: TemporalSearchRegion,
    duration_seconds: float,
    config: MemoGuidedSearchConfig = DEFAULT_CONFIG,
) -> tuple[SceneProposal, ...]:
    config_fingerprint = _fingerprint(asdict(config))
    segments = _validated_segments(transcript_segments, duration_seconds)
    in_region = [
        item
        for item in segments
        if item[2] <= search_region.end_seconds and item[2] > search_region.start_seconds
    ]
    drafts: list[tuple[ProposalType, float, float, tuple[str, ...], dict[str, object]]] = []
    blocks = _build_blocks(in_region, config.transcript_gap_seconds)
    for block in blocks:
        start, end, segment_ids = block
        drafts.append((ProposalType.TRANSCRIPT_BLOCK, start, end, segment_ids, {}))
        drafts.append(
            (
                ProposalType.CONTEXT_EXPANDED,
                max(search_region.start_seconds, start - config.context_expansion_seconds),
                min(search_region.end_seconds, end + config.context_expansion_seconds),
                segment_ids,
                {},
            )
        )
    for window in config.fixed_window_seconds:
        drafts.append(
            (
                ProposalType.FIXED_WINDOW,
                max(search_region.start_seconds, search_region.end_seconds - window),
                search_region.end_seconds,
                (),
                {"window_seconds": window},
            )
        )
    if in_region:
        segment_id, start, end, _ = in_region[-1]
        drafts.append((ProposalType.ADJACENT_SEGMENT, start, end, (segment_id,), {}))

    priority = {kind: index for index, kind in enumerate(ProposalType)}
    drafts.sort(key=lambda item: (priority[item[0]], item[1], item[2], item[3]))
    proposals: list[SceneProposal] = []
    seen: set[tuple[float, float]] = set()
    for kind, start, end, refs, metadata in drafts:
        start = max(0.0, search_region.start_seconds, float(start))
        end = min(float(duration_seconds), search_region.end_seconds, float(end))
        key = (round(start, 6), round(end, 6))
        if start >= end or key in seen:
            continue
        seen.add(key)
        identity = {
            "source_video_id": str(source_video_id),
            "type": kind.value,
            "start": key[0],
            "end": key[1],
            "refs": refs,
            "config": config_fingerprint,
        }
        proposals.append(
            SceneProposal(
                proposal_id=f"proposal-{_fingerprint(identity)[:20]}",
                source_video_id=source_video_id,
                start_seconds=start,
                end_seconds=end,
                proposal_type=kind,
                producer="memo-proposal-generator",
                producer_version=PROPOSAL_VERSION,
                evidence_refs=refs,
                metadata=metadata,
                config_fingerprint=config_fingerprint,
            )
        )
        if len(proposals) >= config.proposal_budget:
            break
    return tuple(proposals)


class DeterministicSemanticSelector:
    def __init__(self, *, just_now_max_gap_seconds: float = 2.0) -> None:
        self.just_now_max_gap_seconds = just_now_max_gap_seconds

    def select(
        self,
        intent: MemoIntent,
        search_region: TemporalSearchRegion,
        proposals: tuple[SceneProposal, ...],
        transcript_context: dict[str, str],
    ) -> SemanticSelection:
        if intent.parse_status is IntentParseStatus.UNSUPPORTED:
            return _selection(SelectionStatus.INSUFFICIENT_EVIDENCE, "UNSUPPORTED_INTENT")
        transcript = tuple(
            proposal for proposal in proposals if proposal.proposal_type is ProposalType.TRANSCRIPT_BLOCK
        )
        if not transcript:
            return _selection(SelectionStatus.INSUFFICIENT_EVIDENCE, "NO_TRANSCRIPT_PROPOSAL")
        if intent.semantic_reference:
            needle = _tokens(intent.semantic_reference)
            matches = [
                proposal
                for proposal in transcript
                if needle and needle <= _tokens(" ".join(transcript_context.get(ref, "") for ref in proposal.evidence_refs))
            ]
            if not matches:
                return _selection(SelectionStatus.NO_MATCH, "LEXICAL_REFERENCE_NO_MATCH")
            if len(matches) > 1:
                return _selection(SelectionStatus.AMBIGUOUS, "LEXICAL_REFERENCE_TIE")
            return _selected(matches[0], "UNIQUE_LEXICAL_MATCH")
        if intent.temporal_reference is TemporalReference.EARLIER:
            return _selection(SelectionStatus.INSUFFICIENT_EVIDENCE, "EARLIER_NEEDS_REFERENCE")
        compatible = [
            proposal
            for proposal in transcript
            if 0 <= search_region.end_seconds - proposal.end_seconds <= self.just_now_max_gap_seconds
        ]
        if not compatible:
            return _selection(SelectionStatus.NO_MATCH, "NO_JUST_NOW_TRANSCRIPT")
        if len(compatible) > 1:
            return _selection(SelectionStatus.AMBIGUOUS, "MULTIPLE_JUST_NOW_BLOCKS")
        return _selected(compatible[0], "UNIQUE_JUST_NOW_BLOCK")


def validate_selection(
    *,
    selection: SemanticSelection,
    proposals: tuple[SceneProposal, ...],
    source_video_id: UUID,
    search_region: TemporalSearchRegion,
    duration_seconds: float,
    config_fingerprint: str,
) -> SceneProposal | None:
    if selection.status is not SelectionStatus.SELECTED:
        if selection.selected_proposal_id is not None:
            raise SelectionValidationError("An abstention cannot select a proposal.")
        return None
    proposal = next((item for item in proposals if item.proposal_id == selection.selected_proposal_id), None)
    if proposal is None:
        raise SelectionValidationError("Selected proposal is not in the manifest.")
    if proposal.source_video_id != source_video_id or search_region.source_video_id != source_video_id:
        raise SelectionValidationError("Selected proposal belongs to another source.")
    if not (search_region.start_seconds <= proposal.start_seconds < proposal.end_seconds <= search_region.end_seconds):
        raise SelectionValidationError("Selected proposal is outside the search region.")
    if proposal.end_seconds > duration_seconds:
        raise SelectionValidationError("Selected proposal exceeds source duration.")
    if proposal.config_fingerprint != config_fingerprint:
        raise SelectionValidationError("Selected proposal has a stale config fingerprint.")
    return proposal


def process_memo_guided_discovery(
    session: Session,
    memo_id: UUID,
    *,
    config: MemoGuidedSearchConfig = DEFAULT_CONFIG,
    selector: SemanticSelector | None = None,
) -> MemoGuidedDiscoveryResult:
    memo = session.get(EditMemo, memo_id)
    if memo is None:
        raise MemoGuidedDiscoveryError("Edit memo was not found.")
    source = session.get(SourceVideo, memo.source_video_id)
    if source is None or source.duration_seconds is None or source.transcript is None:
        raise MemoGuidedDiscoveryError("Source metadata or transcript is unavailable.")
    existing = session.scalar(
        select(SceneAnalysisWorkItem).where(
            SceneAnalysisWorkItem.work_type == WORK_TYPE,
            SceneAnalysisWorkItem.target_type == TARGET_TYPE,
            SceneAnalysisWorkItem.target_id == memo.id,
        )
    )
    if existing is not None:
        if existing.status is not SceneAnalysisWorkStatus.COMPLETED:
            raise MemoGuidedDiscoveryError("Memo discovery already has a non-completed work item.")
        candidate = session.scalar(
            select(SceneCandidate).where(SceneCandidate.analysis_work_item_id == existing.id)
        )
        attempt = session.scalar(
            select(SceneAnalysisAttempt)
            .where(SceneAnalysisAttempt.work_item_id == existing.id)
            .order_by(SceneAnalysisAttempt.attempt_number.desc())
        )
        status_text = (existing.result_reference or "abstain:INSUFFICIENT_EVIDENCE").split(":")[-1]
        status = SelectionStatus.SELECTED if candidate else SelectionStatus(status_text)
        return MemoGuidedDiscoveryResult(
            existing.id, attempt.id, source.id, memo.id, status, "IDEMPOTENT_REUSE", 0,
            candidate.id if candidate else None, candidate is not None,
        )

    config_fingerprint = _fingerprint(asdict(config))
    input_fingerprint = _fingerprint(
        {
            "source": source.fingerprint,
            "transcript_result": _fingerprint(source.transcript.segments),
            "memo": str(memo.id),
            "memo_detector": {
                "trigger_match_type": memo.trigger_match_type,
                "matched_reference": memo.matched_reference,
                "matched_action": memo.matched_action,
            },
        }
    )
    work_item = SceneAnalysisWorkItem(
        project_id=source.project_id,
        source_video_id=source.id,
        work_type=WORK_TYPE,
        target_type=TARGET_TYPE,
        target_id=memo.id,
        status=SceneAnalysisWorkStatus.RUNNING,
        input_fingerprint=input_fingerprint,
        producer="memo-guided-discovery",
        producer_version=PROPOSAL_VERSION,
        config_fingerprint=config_fingerprint,
    )
    attempt = SceneAnalysisAttempt(
        work_item=work_item,
        attempt_number=1,
        status=SceneAnalysisAttemptStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    session.add_all([work_item, attempt])
    session.commit()
    try:
        intent = parse_memo_intent(memo)
        proposals: tuple[SceneProposal, ...] = ()
        if intent.parse_status is IntentParseStatus.UNSUPPORTED:
            selection = _selection(SelectionStatus.INSUFFICIENT_EVIDENCE, "UNSUPPORTED_INTENT")
            region = None
        else:
            region = build_search_region(
                source_video_id=source.id,
                memo_start_seconds=float(memo.start_seconds),
                duration_seconds=float(source.duration_seconds),
                reference=intent.temporal_reference,
                config=config,
            )
            proposals = generate_scene_proposals(
                source_video_id=source.id,
                transcript_segments=source.transcript.segments,
                search_region=region,
                duration_seconds=float(source.duration_seconds),
                config=config,
            )
            transcript_context = _segment_context(source.transcript.segments)
            active_selector = selector or DeterministicSemanticSelector(
                just_now_max_gap_seconds=config.just_now_max_gap_seconds
            )
            selection = active_selector.select(intent, region, proposals, transcript_context)
        chosen = None
        if region is not None:
            chosen = validate_selection(
                selection=selection,
                proposals=proposals,
                source_video_id=source.id,
                search_region=region,
                duration_seconds=float(source.duration_seconds),
                config_fingerprint=config_fingerprint,
            )
        candidate, reused = _promote_candidate(
            session, source, memo, work_item, intent, region, selection, chosen,
            input_fingerprint, config_fingerprint,
        )
        now = datetime.now(timezone.utc)
        work_item.status = SceneAnalysisWorkStatus.COMPLETED
        work_item.result_reference = (
            f"candidate:{candidate.id}" if candidate else f"abstain:{selection.status.value}"
        )
        work_item.result_fingerprint = _fingerprint(
            {"selection": selection.status.value, "candidate": str(candidate.id) if candidate else None}
        )
        attempt.status = SceneAnalysisAttemptStatus.COMPLETED
        attempt.completed_at = now
        session.commit()
        return MemoGuidedDiscoveryResult(
            work_item.id, attempt.id, source.id, memo.id, selection.status,
            selection.reason_code, len(proposals), candidate.id if candidate else None, reused,
        )
    except Exception as exc:
        session.rollback()
        work_item = session.get(SceneAnalysisWorkItem, work_item.id)
        attempt = session.get(SceneAnalysisAttempt, attempt.id)
        work_item.status = SceneAnalysisWorkStatus.FAILED
        attempt.status = SceneAnalysisAttemptStatus.FAILED
        attempt.completed_at = datetime.now(timezone.utc)
        attempt.safe_error_code = "MEMO_DISCOVERY_FAILED"
        attempt.safe_error_message = "Memo-guided discovery failed validation or execution."
        session.commit()
        if isinstance(exc, MemoGuidedDiscoveryError):
            raise
        raise MemoGuidedDiscoveryError("Memo-guided discovery failed.") from exc


def _promote_candidate(
    session: Session,
    source: SourceVideo,
    memo: EditMemo,
    work_item: SceneAnalysisWorkItem,
    intent: MemoIntent,
    region: TemporalSearchRegion | None,
    selection: SemanticSelection,
    proposal: SceneProposal | None,
    input_fingerprint: str,
    config_fingerprint: str,
) -> tuple[SceneCandidate | None, bool]:
    if proposal is None:
        return None, False
    candidate = session.scalar(
        select(SceneCandidate).where(
            SceneCandidate.source_video_id == source.id,
            SceneCandidate.discovery_method == SceneDiscoveryMethod.MEMO_GUIDED,
            SceneCandidate.start_seconds == proposal.start_seconds,
            SceneCandidate.end_seconds == proposal.end_seconds,
        )
    )
    reused = candidate is not None
    if candidate is None:
        candidate = SceneCandidate(
            source_video_id=source.id,
            analysis_work_item_id=work_item.id,
            start_seconds=proposal.start_seconds,
            end_seconds=proposal.end_seconds,
            discovery_method=SceneDiscoveryMethod.MEMO_GUIDED,
            confidence=None,
            input_fingerprint=input_fingerprint,
            result_fingerprint=_fingerprint({"proposal": proposal.proposal_id}),
        )
        session.add(candidate)
        session.flush()
    existing_types = set(
        session.scalars(
            select(SceneEvidence.evidence_type).where(
                SceneEvidence.scene_candidate_id == candidate.id,
                SceneEvidence.source_reference == f"edit-memo:{memo.id}",
            )
        )
    )
    evidence_specs = (
        (SceneEvidenceModality.MEMO, "USER_MEMO", {"memo_id": str(memo.id), "action": intent.action.value}),
        (SceneEvidenceModality.MEMO, "TEMPORAL_REFERENCE", {"reference": intent.temporal_reference.value, "region": [region.start_seconds, region.end_seconds]}),
        (SceneEvidenceModality.TRANSCRIPT, "TRANSCRIPT_MATCH", {"proposal_id": proposal.proposal_id, "segment_ids": list(proposal.evidence_refs)}),
        (SceneEvidenceModality.TRANSCRIPT, "SEMANTIC_SELECTION", {"selector": selection.selector, "selector_version": selection.selector_version, "reason_code": selection.reason_code}),
    )
    for modality, evidence_type, payload in evidence_specs:
        if evidence_type in existing_types:
            continue
        session.add(
            SceneEvidence(
                scene_candidate_id=candidate.id,
                modality=modality,
                evidence_type=evidence_type,
                start_seconds=proposal.start_seconds,
                end_seconds=proposal.end_seconds,
                confidence=None,
                payload=payload,
                payload_schema_version="1",
                producer="memo-guided-discovery",
                producer_version=PROPOSAL_VERSION,
                source_reference=f"edit-memo:{memo.id}",
                input_fingerprint=input_fingerprint,
                config_fingerprint=config_fingerprint,
                result_fingerprint=_fingerprint(payload),
            )
        )
    return candidate, reused


def _validated_segments(segments: object, duration: float) -> list[tuple[str, float, float, str]]:
    if not isinstance(segments, list):
        raise MemoGuidedDiscoveryError("Transcript segments are malformed.")
    result: list[tuple[str, float, float, str]] = []
    previous_end = 0.0
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise MemoGuidedDiscoveryError("Transcript segment is malformed.")
        start = _number(segment.get("start_seconds"), "Segment start")
        end = _number(segment.get("end_seconds"), "Segment end")
        text = segment.get("text")
        if start < previous_end or start < 0 or start >= end or end > duration or not isinstance(text, str) or not text.strip():
            raise MemoGuidedDiscoveryError("Transcript segment invariant failed.")
        result.append((f"segment-{index:04d}", start, end, text.strip()))
        previous_end = end
    return result


def _build_blocks(
    segments: list[tuple[str, float, float, str]], gap: float
) -> list[tuple[float, float, tuple[str, ...]]]:
    blocks: list[list[tuple[str, float, float, str]]] = []
    for segment in segments:
        if not blocks or segment[1] - blocks[-1][-1][2] > gap:
            blocks.append([segment])
        else:
            blocks[-1].append(segment)
    return [(group[0][1], group[-1][2], tuple(item[0] for item in group)) for group in blocks]


def _segment_context(segments: list[dict[str, object]]) -> dict[str, str]:
    return {
        f"segment-{index:04d}": str(segment.get("text", ""))[:240]
        for index, segment in enumerate(segments, start=1)
        if isinstance(segment, dict)
    }


def _selection(status: SelectionStatus, reason: str) -> SemanticSelection:
    return SemanticSelection(status, None, None, reason, None)


def _selected(proposal: SceneProposal, reason: str) -> SemanticSelection:
    return SemanticSelection(SelectionStatus.SELECTED, proposal.proposal_id, None, reason, None)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[0-9A-Za-z가-힣]+", value.casefold()) if len(token) > 1}


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _positive(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise MemoGuidedDiscoveryError(f"{label} must be positive.")
    return number


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoGuidedDiscoveryError(f"{label} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise MemoGuidedDiscoveryError(f"{label} must be finite.")
    return number
