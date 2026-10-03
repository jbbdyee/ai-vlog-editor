from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import (
    EventGroup,
    EventGroupMember,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneEvidence,
    SceneEvidenceModality,
    SceneRelation,
    SceneRelationType,
    SourceVideo,
    Transcript,
)


PAIR_FILTER_WORK_TYPE = "EVENT_PAIR_FILTER"
GROUPING_WORK_TYPE = "EVENT_GROUPING"
PAIR_FILTER_VERSION = "event-pair-filter-v0.1"
GROUPING_VERSION = "conservative-event-grouping-v0.1"
INTERVAL_PRECISION = 3

EXACT_SOURCE_INTERVAL = "EXACT_SOURCE_INTERVAL"
TRANSCRIPT_OVERLAP = "TRANSCRIPT_OVERLAP"
EVIDENCE_TYPE_OVERLAP = "EVIDENCE_TYPE_OVERLAP"
SOURCE_NEIGHBOR_HINT = "SOURCE_NEIGHBOR_HINT"
EXISTING_RELATION = "EXISTING_RELATION"

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class EventGroupingError(ValueError):
    """Raised when relation/grouping input violates product boundaries."""


@dataclass(frozen=True)
class PairFilterConfig:
    minimum_token_length: int = 2
    maximum_token_bucket_size: int = 64
    maximum_evidence_bucket_size: int = 64
    source_neighbor_distance: int = 1
    transcript_context_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.minimum_token_length < 1:
            raise ValueError("minimum_token_length must be positive.")
        if self.maximum_token_bucket_size < 2:
            raise ValueError("maximum_token_bucket_size must be at least 2.")
        if self.maximum_evidence_bucket_size < 2:
            raise ValueError("maximum_evidence_bucket_size must be at least 2.")
        if self.source_neighbor_distance < 0:
            raise ValueError("source_neighbor_distance cannot be negative.")
        if self.transcript_context_seconds < 0:
            raise ValueError("transcript_context_seconds cannot be negative.")


@dataclass(frozen=True)
class CandidateComparisonProjection:
    project_id: UUID
    candidate_id: UUID
    source_video_id: UUID
    start_seconds: float
    end_seconds: float
    discovery_method: str
    candidate_fingerprint: str
    source_fingerprint: str | None
    bounded_transcript: str | None
    transcript_tokens: tuple[str, ...]
    evidence_keys: tuple[str, ...]
    available_modalities: tuple[str, ...]
    source_order: int


@dataclass(frozen=True)
class PairComparisonRequest:
    project_id: UUID
    pair_id: str
    left_candidate_id: UUID
    right_candidate_id: UUID
    left_candidate_fingerprint: str
    right_candidate_fingerprint: str
    canonical_pair_key: str
    blocking_reasons: tuple[str, ...]
    available_modalities: tuple[str, ...]
    bounded_transcript_left: str | None
    bounded_transcript_right: str | None
    source_order_hint: int | None
    filter_version: str
    config_fingerprint: str


@dataclass(frozen=True)
class PairManifest:
    project_id: UUID
    candidate_snapshot_fingerprint: str
    filter_version: str
    config_fingerprint: str
    candidate_count: int
    possible_pair_count: int
    retained_pairs: tuple[PairComparisonRequest, ...]
    reason_counts: dict[str, int]
    result_fingerprint: str
    incremental_focus_count: int = 0

    @property
    def retained_pair_count(self) -> int:
        return len(self.retained_pairs)

    @property
    def reduction_rate(self) -> float:
        if self.possible_pair_count == 0:
            return 1.0
        return 1.0 - (self.retained_pair_count / self.possible_pair_count)


@dataclass(frozen=True)
class EventGroupingResult:
    project_id: UUID
    pair_work_item_id: UUID
    grouping_work_item_id: UUID
    candidate_count: int
    possible_pair_count: int
    retained_pair_count: int
    reduction_rate: float
    reason_counts: dict[str, int]
    relation_count: int
    duplicate_relations_added: int
    event_group_ids: tuple[UUID, ...]
    grouped_candidate_count: int
    unassigned_candidate_ids: tuple[UUID, ...]
    prevented_bridge_merge_count: int
    reused: bool
    llm_calls: int = 0
    vlm_calls: int = 0


def canonical_candidate_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise EventGroupingError("A candidate cannot be paired with itself.")
    return tuple(sorted((first, second), key=lambda value: value.hex))  # type: ignore[return-value]


def normalized_interval(start_seconds: float, end_seconds: float) -> tuple[float, float]:
    start = round(float(start_seconds), INTERVAL_PRECISION)
    end = round(float(end_seconds), INTERVAL_PRECISION)
    if start < 0 or end <= start:
        raise EventGroupingError("Candidate interval is invalid.")
    return start, end


def load_candidate_snapshot(
    session: Session,
    project_id: UUID,
    *,
    config: PairFilterConfig = PairFilterConfig(),
) -> tuple[CandidateComparisonProjection, ...]:
    candidates = session.scalars(
        select(SceneCandidate)
        .join(SourceVideo, SceneCandidate.source_video_id == SourceVideo.id)
        .where(SourceVideo.project_id == project_id)
        .options(
            selectinload(SceneCandidate.evidences).load_only(
                SceneEvidence.modality, SceneEvidence.evidence_type
            ),
            selectinload(SceneCandidate.source_video)
            .load_only(
                SourceVideo.id,
                SourceVideo.project_id,
                SourceVideo.fingerprint,
                SourceVideo.created_at,
            )
            .selectinload(SourceVideo.transcript)
            .load_only(Transcript.segments),
        )
        .order_by(SceneCandidate.created_at, SceneCandidate.id)
    ).all()
    sources = {candidate.source_video.id: candidate.source_video for candidate in candidates}
    source_ids = sorted(
        sources,
        key=lambda value: (sources[value].created_at, value.hex),
    )
    source_order = {source_id: index for index, source_id in enumerate(source_ids)}
    projections = [
        _project_candidate(candidate, source_order[candidate.source_video_id], config)
        for candidate in candidates
    ]
    return tuple(sorted(projections, key=lambda item: item.candidate_id.hex))


def build_pair_manifest(
    projections: Sequence[CandidateComparisonProjection],
    *,
    config: PairFilterConfig = PairFilterConfig(),
    existing_relations: Iterable[tuple[UUID, UUID]] = (),
    focus_candidate_ids: Iterable[UUID] | None = None,
) -> PairManifest:
    if projections:
        project_id = projections[0].project_id
    else:
        raise EventGroupingError("Pair manifest requires a project candidate snapshot.")
    if any(item.project_id != project_id for item in projections):
        raise EventGroupingError("Cross-project candidate snapshots are not allowed.")

    ordered = tuple(sorted(projections, key=lambda item: item.candidate_id.hex))
    by_id = {item.candidate_id: item for item in ordered}
    if len(by_id) != len(ordered):
        raise EventGroupingError("Candidate snapshot contains duplicate IDs.")
    focus = frozenset(focus_candidate_ids or ())
    if not focus <= by_id.keys():
        raise EventGroupingError("Incremental focus contains an unknown candidate.")

    config_fingerprint = _fingerprint(asdict(config))
    snapshot_fingerprint = _fingerprint([_projection_identity(item) for item in ordered])
    reasons: dict[tuple[UUID, UUID], set[str]] = defaultdict(set)

    exact_buckets: dict[tuple[str, float, float], list[UUID]] = defaultdict(list)
    token_buckets: dict[str, list[UUID]] = defaultdict(list)
    evidence_buckets: dict[str, list[UUID]] = defaultdict(list)
    source_buckets: dict[int, list[UUID]] = defaultdict(list)
    for item in ordered:
        if item.source_fingerprint:
            exact_buckets[(item.source_fingerprint, item.start_seconds, item.end_seconds)].append(item.candidate_id)
        for token in item.transcript_tokens:
            token_buckets[token].append(item.candidate_id)
        for evidence_key in item.evidence_keys:
            evidence_buckets[evidence_key].append(item.candidate_id)
        source_buckets[item.source_order].append(item.candidate_id)

    for bucket in exact_buckets.values():
        _add_bucket_pairs(reasons, bucket, EXACT_SOURCE_INTERVAL, focus)
    for bucket in token_buckets.values():
        if len(bucket) <= config.maximum_token_bucket_size:
            _add_bucket_pairs(reasons, bucket, TRANSCRIPT_OVERLAP, focus)
    for bucket in evidence_buckets.values():
        if len(bucket) <= config.maximum_evidence_bucket_size:
            _add_bucket_pairs(reasons, bucket, EVIDENCE_TYPE_OVERLAP, focus)
    if config.source_neighbor_distance:
        source_orders = sorted(source_buckets)
        for index, left_order in enumerate(source_orders):
            for right_order in source_orders[index + 1 :]:
                if right_order - left_order > config.source_neighbor_distance:
                    break
                _add_cross_bucket_pairs(
                    reasons,
                    source_buckets[left_order],
                    source_buckets[right_order],
                    SOURCE_NEIGHBOR_HINT,
                    focus,
                )
    for first, second in existing_relations:
        if first not in by_id or second not in by_id:
            continue
        pair = canonical_candidate_pair(first, second)
        if not focus or pair[0] in focus or pair[1] in focus:
            if pair not in reasons:
                reasons[pair].add(EXISTING_RELATION)

    requests = []
    for left_id, right_id in sorted(reasons, key=lambda pair: (pair[0].hex, pair[1].hex)):
        left = by_id[left_id]
        right = by_id[right_id]
        key_payload = {
            "project_id": str(project_id),
            "left": str(left_id),
            "right": str(right_id),
            "filter_version": PAIR_FILTER_VERSION,
            "config": config_fingerprint,
        }
        pair_key = _fingerprint(key_payload)
        requests.append(
            PairComparisonRequest(
                project_id=project_id,
                pair_id=f"pair-{pair_key[:24]}",
                left_candidate_id=left_id,
                right_candidate_id=right_id,
                left_candidate_fingerprint=left.candidate_fingerprint,
                right_candidate_fingerprint=right.candidate_fingerprint,
                canonical_pair_key=pair_key,
                blocking_reasons=tuple(sorted(reasons[(left_id, right_id)])),
                available_modalities=tuple(sorted(set(left.available_modalities) | set(right.available_modalities))),
                bounded_transcript_left=left.bounded_transcript,
                bounded_transcript_right=right.bounded_transcript,
                source_order_hint=abs(left.source_order - right.source_order),
                filter_version=PAIR_FILTER_VERSION,
                config_fingerprint=config_fingerprint,
            )
        )

    candidate_count = len(ordered)
    if focus:
        existing_count = candidate_count - len(focus)
        possible = len(focus) * existing_count + len(focus) * (len(focus) - 1) // 2
    else:
        possible = candidate_count * (candidate_count - 1) // 2
    reason_counts = Counter(reason for item in requests for reason in item.blocking_reasons)
    result_fingerprint = _fingerprint(
        {
            "snapshot": snapshot_fingerprint,
            "filter_version": PAIR_FILTER_VERSION,
            "config": config_fingerprint,
            "focus": sorted(str(item) for item in focus),
            "pairs": [
                {"key": item.canonical_pair_key, "reasons": item.blocking_reasons}
                for item in requests
            ],
        }
    )
    return PairManifest(
        project_id=project_id,
        candidate_snapshot_fingerprint=snapshot_fingerprint,
        filter_version=PAIR_FILTER_VERSION,
        config_fingerprint=config_fingerprint,
        candidate_count=candidate_count,
        possible_pair_count=possible,
        retained_pairs=tuple(requests),
        reason_counts=dict(sorted(reason_counts.items())),
        result_fingerprint=result_fingerprint,
        incremental_focus_count=len(focus),
    )


def build_conservative_group_sets(
    candidate_ids: Iterable[UUID],
    same_event_pairs: Iterable[tuple[UUID, UUID]],
) -> tuple[tuple[tuple[UUID, ...], ...], int, tuple[UUID, ...]]:
    candidates = frozenset(candidate_ids)
    edges = {
        canonical_candidate_pair(first, second)
        for first, second in same_event_pairs
        if first in candidates and second in candidates and first != second
    }
    groups: list[set[UUID]] = []
    prevented_bridge_merges = 0
    for left, right in sorted(edges, key=lambda pair: (pair[0].hex, pair[1].hex)):
        left_groups = [group for group in groups if left in group]
        right_groups = [group for group in groups if right in group]
        if not left_groups and not right_groups:
            groups.append({left, right})
            continue
        if left_groups and right_groups:
            if left_groups[0] is not right_groups[0]:
                prevented_bridge_merges += 1
            continue
        group = (left_groups or right_groups)[0]
        outsider = right if left in group else left
        if all(canonical_candidate_pair(outsider, member) in edges for member in group):
            group.add(outsider)
        else:
            prevented_bridge_merges += 1

    # A candidate compatible with more than one already-formed group is not allowed
    # to pick a primary group merely because its UUID caused one group to be visited
    # first. Remove that ambiguous membership and keep the candidate unassigned.
    ambiguous_members = set()
    for candidate in candidates:
        compatible_groups = [
            group
            for group in groups
            if candidate not in group
            and group
            and all(canonical_candidate_pair(candidate, member) in edges for member in group)
        ]
        owning_groups = [group for group in groups if candidate in group]
        if owning_groups and compatible_groups:
            ambiguous_members.add(candidate)
    for candidate in ambiguous_members:
        for group in groups:
            group.discard(candidate)

    normalized_groups = tuple(
        sorted(
            (tuple(sorted(group, key=lambda value: value.hex)) for group in groups if len(group) >= 2),
            key=lambda group: tuple(value.hex for value in group),
        )
    )
    grouped = {candidate for group in normalized_groups for candidate in group}
    unassigned = tuple(sorted(candidates - grouped, key=lambda value: value.hex))
    return normalized_groups, prevented_bridge_merges, unassigned


def process_event_grouping(
    session: Session,
    project_id: UUID,
    *,
    config: PairFilterConfig = PairFilterConfig(),
    focus_candidate_ids: Iterable[UUID] | None = None,
) -> EventGroupingResult:
    projections = load_candidate_snapshot(session, project_id, config=config)
    if not projections:
        raise EventGroupingError("Project has no SceneCandidate to group.")
    existing_relation_pairs = session.execute(
        select(
            SceneRelation.source_scene_candidate_id,
            SceneRelation.target_scene_candidate_id,
        ).join(
            SceneCandidate,
            SceneRelation.source_scene_candidate_id == SceneCandidate.id,
        ).join(SourceVideo, SceneCandidate.source_video_id == SourceVideo.id)
        .where(SourceVideo.project_id == project_id)
    ).all()
    manifest = build_pair_manifest(
        projections,
        config=config,
        existing_relations=existing_relation_pairs,
        focus_candidate_ids=focus_candidate_ids,
    )
    grouping_input = _fingerprint(
        {
            "snapshot": manifest.candidate_snapshot_fingerprint,
            "pair_manifest": manifest.result_fingerprint,
            "grouping_version": GROUPING_VERSION,
        }
    )
    grouping_config = _fingerprint(
        {"grouping_version": GROUPING_VERSION, "single_current_membership": True}
    )
    cached_grouping = session.scalar(
        select(SceneAnalysisWorkItem)
        .where(
            SceneAnalysisWorkItem.project_id == project_id,
            SceneAnalysisWorkItem.work_type == GROUPING_WORK_TYPE,
            SceneAnalysisWorkItem.status == SceneAnalysisWorkStatus.COMPLETED,
            SceneAnalysisWorkItem.input_fingerprint == grouping_input,
            SceneAnalysisWorkItem.config_fingerprint == grouping_config,
        )
        .order_by(SceneAnalysisWorkItem.created_at.desc())
    )
    if cached_grouping is not None:
        cached_pair = session.scalar(
            select(SceneAnalysisWorkItem)
            .where(
                SceneAnalysisWorkItem.project_id == project_id,
                SceneAnalysisWorkItem.work_type == PAIR_FILTER_WORK_TYPE,
                SceneAnalysisWorkItem.result_fingerprint == manifest.result_fingerprint,
                SceneAnalysisWorkItem.status == SceneAnalysisWorkStatus.COMPLETED,
            )
            .order_by(SceneAnalysisWorkItem.created_at.desc())
        )
        if cached_pair is None:
            raise EventGroupingError("Cached grouping is missing its pair-filter lineage.")
        return _result_from_database(
            session, project_id, manifest, cached_pair, cached_grouping, 0, True
        )

    pair_work, pair_attempt = _start_work(
        session,
        project_id,
        PAIR_FILTER_WORK_TYPE,
        manifest.candidate_snapshot_fingerprint,
        manifest.config_fingerprint,
        PAIR_FILTER_VERSION,
    )
    pair_summary = _manifest_summary(manifest)
    pair_work.result_reference = _bounded_json(pair_summary)
    pair_work.result_fingerprint = manifest.result_fingerprint
    _complete_work(pair_work, pair_attempt)
    session.commit()

    duplicate_added = 0
    projection_by_id = {item.candidate_id: item for item in projections}
    for request in manifest.retained_pairs:
        if EXACT_SOURCE_INTERVAL not in request.blocking_reasons:
            continue
        left = projection_by_id[request.left_candidate_id]
        right = projection_by_id[request.right_candidate_id]
        if not _is_exact_duplicate(left, right):
            continue
        _, created = persist_relation(
            session,
            project_id,
            left.candidate_id,
            right.candidate_id,
            SceneRelationType.DUPLICATE,
            producer="deterministic-event-grouping",
            producer_version=GROUPING_VERSION,
            source_reference=f"scene-work-item:{pair_work.id}",
        )
        duplicate_added += int(created)
    session.commit()

    grouping_work, grouping_attempt = _start_work(
        session,
        project_id,
        GROUPING_WORK_TYPE,
        grouping_input,
        grouping_config,
        GROUPING_VERSION,
    )
    session.commit()
    try:
        same_event_pairs = session.execute(
            select(
                SceneRelation.source_scene_candidate_id,
                SceneRelation.target_scene_candidate_id,
            )
            .join(
                SceneCandidate,
                SceneRelation.source_scene_candidate_id == SceneCandidate.id,
            )
            .join(SourceVideo, SceneCandidate.source_video_id == SourceVideo.id)
            .where(
                SourceVideo.project_id == project_id,
                SceneRelation.relation_type == SceneRelationType.SAME_EVENT,
            )
        ).all()
        group_sets, prevented, _ = build_conservative_group_sets(
            projection_by_id, same_event_pairs
        )
        group_ids = _reconcile_groups(
            session,
            project_id,
            group_sets,
            input_fingerprint=grouping_input,
        )
        grouped = {candidate_id for group in group_sets for candidate_id in group}
        unassigned = tuple(
            sorted(set(projection_by_id) - grouped, key=lambda value: value.hex)
        )
        grouping_summary = {
            "group_count": len(group_ids),
            "grouped_candidate_count": len(grouped),
            "unassigned_count": len(unassigned),
            "prevented_bridge_merge_count": prevented,
        }
        grouping_work.result_reference = _bounded_json(grouping_summary)
        grouping_work.result_fingerprint = _fingerprint(
            {
                "groups": [[str(item) for item in group] for group in group_sets],
                "unassigned": [str(item) for item in unassigned],
                "prevented": prevented,
            }
        )
        _complete_work(grouping_work, grouping_attempt)
        session.commit()
    except Exception as error:
        session.rollback()
        failed_work = session.get(SceneAnalysisWorkItem, grouping_work.id)
        failed_attempt = session.get(SceneAnalysisAttempt, grouping_attempt.id)
        if failed_work is not None and failed_attempt is not None:
            _fail_work(failed_work, failed_attempt, "EVENT_GROUPING_FAILED")
            session.commit()
        raise EventGroupingError("Event grouping persistence failed.") from error

    return _result_from_database(
        session, project_id, manifest, pair_work, grouping_work, duplicate_added, False
    )


def persist_relation(
    session: Session,
    project_id: UUID,
    first_candidate_id: UUID,
    second_candidate_id: UUID,
    relation_type: SceneRelationType,
    *,
    producer: str,
    producer_version: str,
    source_reference: str | None = None,
) -> tuple[SceneRelation, bool]:
    first = session.get(SceneCandidate, first_candidate_id)
    second = session.get(SceneCandidate, second_candidate_id)
    if first is None or second is None:
        raise EventGroupingError("Relation candidate does not exist.")
    if first.source_video.project_id != project_id or second.source_video.project_id != project_id:
        raise EventGroupingError("Cross-project SceneRelation is not allowed.")
    if relation_type in {SceneRelationType.SAME_EVENT, SceneRelationType.DUPLICATE}:
        source_id, target_id = canonical_candidate_pair(first.id, second.id)
    else:
        if first.id == second.id:
            raise EventGroupingError("A candidate cannot relate to itself.")
        source_id, target_id = first.id, second.id
    if relation_type is SceneRelationType.DUPLICATE:
        projection_order = {first.source_video_id: 0, second.source_video_id: 1}
        left = _project_candidate(first, projection_order[first.source_video_id], PairFilterConfig())
        right = _project_candidate(second, projection_order[second.source_video_id], PairFilterConfig())
        if not _is_exact_duplicate(left, right):
            raise EventGroupingError("DUPLICATE requires the same source fingerprint and exact interval.")
    existing = session.scalar(
        select(SceneRelation).where(
            SceneRelation.source_scene_candidate_id == source_id,
            SceneRelation.target_scene_candidate_id == target_id,
            SceneRelation.relation_type == relation_type,
        )
    )
    if existing is not None:
        return existing, False
    relation = SceneRelation(
        source_scene_candidate_id=source_id,
        target_scene_candidate_id=target_id,
        relation_type=relation_type,
        confidence=None,
        producer=producer,
        producer_version=producer_version,
        source_reference=source_reference,
    )
    session.add(relation)
    session.flush()
    return relation, True


def _project_candidate(
    candidate: SceneCandidate,
    source_order: int,
    config: PairFilterConfig,
) -> CandidateComparisonProjection:
    source = candidate.source_video
    start, end = normalized_interval(candidate.start_seconds, candidate.end_seconds)
    excerpt = _bounded_transcript(source, start, end, config.transcript_context_seconds)
    tokens = tuple(
        sorted(
            {
                token
                for token in _tokenize(excerpt or "")
                if len(token) >= config.minimum_token_length
            }
        )
    )
    evidence_keys = tuple(
        sorted({f"{item.modality.value}:{item.evidence_type}" for item in candidate.evidences})
    )
    modalities = tuple(sorted({item.modality.value for item in candidate.evidences}))
    fingerprint = candidate.result_fingerprint or _fingerprint(
        {
            "candidate": str(candidate.id),
            "input": candidate.input_fingerprint,
            "interval": [start, end],
        }
    )
    return CandidateComparisonProjection(
        project_id=source.project_id,
        candidate_id=candidate.id,
        source_video_id=source.id,
        start_seconds=start,
        end_seconds=end,
        discovery_method=candidate.discovery_method.value,
        candidate_fingerprint=fingerprint,
        source_fingerprint=source.fingerprint,
        bounded_transcript=excerpt,
        transcript_tokens=tokens,
        evidence_keys=evidence_keys,
        available_modalities=modalities,
        source_order=source_order,
    )


def _bounded_transcript(
    source: SourceVideo,
    start: float,
    end: float,
    context_seconds: float,
) -> str | None:
    if source.transcript is None:
        return None
    parts = []
    lower = max(0.0, start - context_seconds)
    upper = end + context_seconds
    for segment in source.transcript.segments:
        segment_start = _segment_number(segment, "start_seconds", "start")
        segment_end = _segment_number(segment, "end_seconds", "end")
        text = segment.get("text")
        if segment_start is None or segment_end is None or not isinstance(text, str):
            continue
        if segment_end > lower and segment_start < upper:
            normalized = " ".join(text.split())
            if normalized:
                parts.append(normalized)
    if not parts:
        return None
    return " ".join(parts)[:1000]


def _segment_number(segment: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        value = segment.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _tokenize(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_PATTERN.findall(value))


def _add_bucket_pairs(
    reasons: dict[tuple[UUID, UUID], set[str]],
    candidate_ids: Sequence[UUID],
    reason: str,
    focus: frozenset[UUID],
) -> None:
    ordered = sorted(set(candidate_ids), key=lambda value: value.hex)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if focus and first not in focus and second not in focus:
                continue
            reasons[(first, second)].add(reason)


def _add_cross_bucket_pairs(
    reasons: dict[tuple[UUID, UUID], set[str]],
    left_ids: Sequence[UUID],
    right_ids: Sequence[UUID],
    reason: str,
    focus: frozenset[UUID],
) -> None:
    for first in left_ids:
        for second in right_ids:
            pair = canonical_candidate_pair(first, second)
            if focus and pair[0] not in focus and pair[1] not in focus:
                continue
            reasons[pair].add(reason)


def _projection_identity(item: CandidateComparisonProjection) -> dict[str, object]:
    return {
        "candidate_id": str(item.candidate_id),
        "source_video_id": str(item.source_video_id),
        "interval": [item.start_seconds, item.end_seconds],
        "candidate_fingerprint": item.candidate_fingerprint,
        "source_fingerprint": item.source_fingerprint,
        "tokens": item.transcript_tokens,
        "evidence": item.evidence_keys,
    }


def _is_exact_duplicate(
    left: CandidateComparisonProjection,
    right: CandidateComparisonProjection,
) -> bool:
    return bool(
        left.project_id == right.project_id
        and left.source_fingerprint
        and left.source_fingerprint == right.source_fingerprint
        and (left.start_seconds, left.end_seconds)
        == (right.start_seconds, right.end_seconds)
    )


def _start_work(
    session: Session,
    project_id: UUID,
    work_type: str,
    input_fingerprint: str,
    config_fingerprint: str,
    producer_version: str,
) -> tuple[SceneAnalysisWorkItem, SceneAnalysisAttempt]:
    work = SceneAnalysisWorkItem(
        project_id=project_id,
        source_video_id=None,
        work_type=work_type,
        target_type="PROJECT",
        target_id=project_id,
        status=SceneAnalysisWorkStatus.RUNNING,
        input_fingerprint=input_fingerprint,
        producer="deterministic-event-grouping",
        producer_version=producer_version,
        config_fingerprint=config_fingerprint,
    )
    session.add(work)
    session.flush()
    attempt = SceneAnalysisAttempt(
        work_item_id=work.id,
        attempt_number=1,
        status=SceneAnalysisAttemptStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    session.add(attempt)
    session.flush()
    return work, attempt


def _complete_work(
    work: SceneAnalysisWorkItem, attempt: SceneAnalysisAttempt
) -> None:
    now = datetime.now(timezone.utc)
    work.status = SceneAnalysisWorkStatus.COMPLETED
    attempt.status = SceneAnalysisAttemptStatus.COMPLETED
    attempt.completed_at = now


def _fail_work(
    work: SceneAnalysisWorkItem,
    attempt: SceneAnalysisAttempt,
    error_code: str,
) -> None:
    work.status = SceneAnalysisWorkStatus.FAILED
    attempt.status = SceneAnalysisAttemptStatus.FAILED
    attempt.completed_at = datetime.now(timezone.utc)
    attempt.safe_error_code = error_code
    attempt.safe_error_message = "Event grouping could not be persisted."


def _reconcile_groups(
    session: Session,
    project_id: UUID,
    desired_groups: Sequence[Sequence[UUID]],
    *,
    input_fingerprint: str,
) -> tuple[UUID, ...]:
    current_groups = session.scalars(
        select(EventGroup)
        .where(
            EventGroup.project_id == project_id,
            EventGroup.producer == "deterministic-event-grouping",
            EventGroup.producer_version == GROUPING_VERSION,
        )
        .options(selectinload(EventGroup.members))
    ).all()
    current_by_members = {
        frozenset(member.scene_candidate_id for member in group.members): group
        for group in current_groups
    }
    desired_sets = [frozenset(group) for group in desired_groups if len(group) >= 2]
    desired_candidate_ids = {candidate_id for group in desired_sets for candidate_id in group}

    external_memberships = session.execute(
        select(EventGroupMember.scene_candidate_id, EventGroup.id)
        .join(EventGroup, EventGroupMember.event_group_id == EventGroup.id)
        .where(
            EventGroup.project_id == project_id,
            EventGroupMember.scene_candidate_id.in_(desired_candidate_ids or {UUID(int=0)}),
            or_(
                EventGroup.producer != "deterministic-event-grouping",
                EventGroup.producer_version != GROUPING_VERSION,
            ),
        )
    ).all()
    if external_memberships:
        raise EventGroupingError("A candidate already belongs to another current EventGroup.")

    for members, group in current_by_members.items():
        if members not in desired_sets:
            session.execute(
                delete(EventGroupMember).where(EventGroupMember.event_group_id == group.id)
            )
            session.delete(group)

    group_ids = []
    for members in desired_sets:
        group = current_by_members.get(members)
        if group is None:
            group = EventGroup(
                project_id=project_id,
                label=None,
                summary=None,
                producer="deterministic-event-grouping",
                producer_version=GROUPING_VERSION,
                input_fingerprint=input_fingerprint,
                result_fingerprint=_fingerprint(sorted(str(item) for item in members)),
            )
            session.add(group)
            session.flush()
            session.add_all(
                EventGroupMember(event_group_id=group.id, scene_candidate_id=candidate_id)
                for candidate_id in sorted(members, key=lambda value: value.hex)
            )
        else:
            group.input_fingerprint = input_fingerprint
            group.result_fingerprint = _fingerprint(sorted(str(item) for item in members))
        group_ids.append(group.id)
    session.flush()
    return tuple(sorted(group_ids, key=lambda value: value.hex))


def _result_from_database(
    session: Session,
    project_id: UUID,
    manifest: PairManifest,
    pair_work: SceneAnalysisWorkItem,
    grouping_work: SceneAnalysisWorkItem,
    duplicate_added: int,
    reused: bool,
) -> EventGroupingResult:
    groups = session.scalars(
        select(EventGroup)
        .where(
            EventGroup.project_id == project_id,
            EventGroup.producer == "deterministic-event-grouping",
            EventGroup.producer_version == GROUPING_VERSION,
        )
        .options(selectinload(EventGroup.members))
        .order_by(EventGroup.id)
    ).all()
    grouped = {member.scene_candidate_id for group in groups for member in group.members}
    all_candidates = {
        item.candidate_id
        for item in load_candidate_snapshot(session, project_id)
    }
    summary = _decode_reference(grouping_work.result_reference)
    relation_ids = session.scalars(
        select(SceneRelation.id)
        .join(
            SceneCandidate,
            SceneRelation.source_scene_candidate_id == SceneCandidate.id,
        )
        .join(SourceVideo, SceneCandidate.source_video_id == SourceVideo.id)
        .where(SourceVideo.project_id == project_id)
    ).all()
    return EventGroupingResult(
        project_id=project_id,
        pair_work_item_id=pair_work.id,
        grouping_work_item_id=grouping_work.id,
        candidate_count=manifest.candidate_count,
        possible_pair_count=manifest.possible_pair_count,
        retained_pair_count=manifest.retained_pair_count,
        reduction_rate=manifest.reduction_rate,
        reason_counts=manifest.reason_counts,
        relation_count=len(relation_ids),
        duplicate_relations_added=duplicate_added,
        event_group_ids=tuple(group.id for group in groups),
        grouped_candidate_count=len(grouped),
        unassigned_candidate_ids=tuple(sorted(all_candidates - grouped, key=lambda value: value.hex)),
        prevented_bridge_merge_count=int(summary.get("prevented_bridge_merge_count", 0)),
        reused=reused,
    )


def _manifest_summary(manifest: PairManifest) -> dict[str, object]:
    return {
        "candidate_count": manifest.candidate_count,
        "possible_pair_count": manifest.possible_pair_count,
        "retained_pair_count": manifest.retained_pair_count,
        "reduction_rate": round(manifest.reduction_rate, 8),
        "reason_counts": manifest.reason_counts,
        "incremental_focus_count": manifest.incremental_focus_count,
    }


def _bounded_json(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 1000:
        raise EventGroupingError("Work result summary exceeds the bounded reference size.")
    return encoded


def _decode_reference(value: str | None) -> dict[str, object]:
    if value is None:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()
