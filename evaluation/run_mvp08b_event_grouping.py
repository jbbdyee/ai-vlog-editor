"""Read-only MVP-08B local event-proposal experiment; no product persistence."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Iterable
from uuid import UUID


POSITIVE_TYPES = frozenset({
    "TRANSCRIPT_STRUCTURE", "TRANSCRIPT_REACTION_CUE",
    "AUDIO_ACTIVITY", "VISUAL_ACTIVITY",
})
VERSION = "mvp-08b-local-event-proposal-v0.1"


@dataclass(frozen=True)
class EvidenceRef:
    id: str
    modality: str
    evidence_type: str
    start_seconds: float
    end_seconds: float

    @property
    def identity(self) -> tuple[str, str, float, float]:
        # One source fact has a separate persisted SceneEvidence row per candidate.
        return (self.modality, self.evidence_type, self.start_seconds, self.end_seconds)


@dataclass(frozen=True)
class CandidateInput:
    id: str
    source_id: str
    start_seconds: float
    end_seconds: float
    promotion_rule: str
    promotion_evidence: tuple[EvidenceRef, EvidenceRef]
    linked_evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class EventProposal:
    id: str
    source_id: str
    start_seconds: float
    end_seconds: float
    candidate_ids: tuple[str, ...]
    candidate_intervals: tuple[tuple[float, float], ...]
    evidence_refs: tuple[EvidenceRef, ...]
    evidence_supported_intervals: tuple[tuple[float, float], ...]
    no_evidence_intervals: tuple[tuple[float, float], ...]
    corroborated_intervals: tuple[tuple[float, float], ...]
    no_corroboration_intervals: tuple[tuple[float, float], ...]


def _validate_interval(start: float, end: float, label: str) -> None:
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (start, end)):
        raise ValueError(f"{label} must have finite numeric boundaries")
    if start < 0 or start >= end:
        raise ValueError(f"{label} must have positive nonnegative duration")
    if round(start, 3) != start or round(end, 3) != end:
        raise ValueError(f"{label} must use millisecond-aligned boundaries")


def _merge_intervals(intervals: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    result: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return tuple(result)


def _gaps(start: float, end: float, intervals: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    cursor = start
    result = []
    for left, right in intervals:
        if left > cursor:
            result.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        result.append((cursor, end))
    return tuple(result)


def _validate(candidates: tuple[CandidateInput, ...]) -> None:
    ids: set[str] = set()
    sources: set[str] = set()
    for candidate in candidates:
        if not candidate.id or candidate.id in ids:
            raise ValueError("Candidate IDs must be nonempty and unique")
        ids.add(candidate.id)
        if not candidate.source_id or not candidate.promotion_rule:
            raise ValueError("Candidate source and promotion rule are required")
        sources.add(candidate.source_id)
        _validate_interval(candidate.start_seconds, candidate.end_seconds, "Candidate interval")
        if len(candidate.promotion_evidence) != 2:
            raise ValueError("Exactly two promotion evidence references are required")
        linked = {evidence.id for evidence in candidate.linked_evidence}
        if len(linked) != len(candidate.linked_evidence):
            raise ValueError("Linked evidence IDs must be unique per candidate")
        for evidence in candidate.linked_evidence:
            if not evidence.id or not evidence.evidence_type or not evidence.modality:
                raise ValueError("Evidence identity, modality and type are required")
            _validate_interval(evidence.start_seconds, evidence.end_seconds, "Evidence interval")
            if max(candidate.start_seconds, evidence.start_seconds) >= min(candidate.end_seconds, evidence.end_seconds):
                raise ValueError("Linked evidence must overlap its candidate")
        if any(evidence.id not in linked for evidence in candidate.promotion_evidence):
            raise ValueError("Promotion evidence must be linked to its candidate")
        left, right = candidate.promotion_evidence
        if (max(left.start_seconds, right.start_seconds), min(left.end_seconds, right.end_seconds)) != (
            candidate.start_seconds, candidate.end_seconds
        ):
            raise ValueError("Candidate must equal its promotion evidence intersection")
    if len(sources) > 1:
        raise ValueError("Candidates must belong to one source")


def _transcript_identities(candidates: Iterable[CandidateInput]) -> set[tuple[str, str, float, float]]:
    return {
        evidence.identity
        for candidate in candidates
        for evidence in candidate.linked_evidence
        if evidence.evidence_type == "TRANSCRIPT_STRUCTURE"
    }


def _can_join(group: list[CandidateInput], candidate: CandidateInput) -> bool:
    # An existing promoting fact must itself bridge the temporal gap. QUALITY is excluded.
    for member in group:
        gap = max(0.0, candidate.start_seconds - member.end_seconds)
        member_facts = {fact.identity: fact for fact in member.promotion_evidence if fact.evidence_type in POSITIVE_TYPES}
        shared = set(member_facts).intersection(fact.identity for fact in candidate.promotion_evidence)
        if not any(
            member_facts[key].start_seconds <= member.end_seconds
            and member_facts[key].end_seconds >= candidate.start_seconds
            for key in shared
        ):
            continue
        # Scale-free guard: an unsupported interval cannot outweigh the two local candidates.
        if gap > 0 and gap >= (member.end_seconds - member.start_seconds) + (candidate.end_seconds - candidate.start_seconds):
            continue
        if len(_transcript_identities((*group, candidate))) > 1:
            continue
        merged = _merge_intervals((item.start_seconds, item.end_seconds) for item in (*group, candidate))
        covered = sum(end - start for start, end in merged)
        envelope = max(item.end_seconds for item in (*group, candidate)) - min(item.start_seconds for item in (*group, candidate))
        if covered * 2 <= envelope:
            continue
        return True
    return False


def group_candidates(candidates: Iterable[CandidateInput]) -> tuple[EventProposal, ...]:
    """Produce deterministic local proposals without editing or ranking candidates."""
    original = tuple(candidates)
    _validate(original)
    if not original:
        return ()
    groups: list[list[CandidateInput]] = []
    for candidate in sorted(original, key=lambda item: (item.start_seconds, item.end_seconds, item.id)):
        eligible = [group for group in groups if _can_join(group, candidate)]
        if eligible:
            # Most recent compatible group; ambiguous ties are broken by sorted input order.
            max(eligible, key=lambda group: (max(item.end_seconds for item in group), group[0].id)).append(candidate)
        else:
            groups.append([candidate])
    result = []
    for group in groups:
        start = min(item.start_seconds for item in group)
        end = max(item.end_seconds for item in group)
        refs = tuple(sorted(
            (evidence for item in group for evidence in item.linked_evidence),
            key=lambda evidence: (evidence.start_seconds, evidence.end_seconds, evidence.evidence_type, evidence.id),
        ))
        supported = _merge_intervals(
            (max(start, evidence.start_seconds), min(end, evidence.end_seconds))
            for evidence in refs if evidence.evidence_type in POSITIVE_TYPES
        )
        corroborated = _merge_intervals((item.start_seconds, item.end_seconds) for item in group)
        ids = tuple(item.id for item in group)
        digest = sha256(json.dumps([VERSION, group[0].source_id, ids], separators=(",", ":")).encode()).hexdigest()[:16]
        result.append(EventProposal(
            id=f"offline-{digest}", source_id=group[0].source_id,
            start_seconds=start, end_seconds=end,
            candidate_ids=ids,
            candidate_intervals=tuple((item.start_seconds, item.end_seconds) for item in group),
            evidence_refs=refs,
            evidence_supported_intervals=supported,
            no_evidence_intervals=_gaps(start, end, supported),
            corroborated_intervals=corroborated,
            no_corroboration_intervals=_gaps(start, end, corroborated),
        ))
    return tuple(sorted(result, key=lambda item: (item.start_seconds, item.end_seconds, item.id)))


def _load_read_only(source_id: UUID) -> tuple[float, tuple[CandidateInput, ...], dict[str, object]]:
    """Replay product baseline from cached work and verify every stored candidate."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.app.config import DatabaseSettings, load_environment
    from backend.app.database import create_database_engine
    from backend.app.models import SceneAnalysisWorkItem, SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SourceVideo
    from backend.app.services.autonomous_discovery import (
        AUDIO_WORK, DEFAULT_CONFIG, PROMOTION_WORK, TRANSCRIPT_WORK, VISUAL_WORK,
        _decode_analysis, build_promotion_manifest,
    )

    load_environment()
    engine = create_database_engine(DatabaseSettings.from_environment())
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            with Session(bind=connection) as session:
                source = session.get(SourceVideo, source_id)
                if source is None or source.duration_seconds is None:
                    raise ValueError("Baseline source or duration is unavailable")
                works = session.scalars(select(SceneAnalysisWorkItem).where(
                    SceneAnalysisWorkItem.source_video_id == source_id,
                    SceneAnalysisWorkItem.work_type.in_((TRANSCRIPT_WORK, AUDIO_WORK, VISUAL_WORK, PROMOTION_WORK)),
                ).order_by(SceneAnalysisWorkItem.created_at, SceneAnalysisWorkItem.id)).all()
                latest = {work.work_type: work for work in works}
                facts = []
                for kind in (TRANSCRIPT_WORK, AUDIO_WORK, VISUAL_WORK):
                    work = latest.get(kind)
                    analysis = _decode_analysis(work.result_reference) if work else None
                    if analysis is None or work.status.value != "COMPLETED":
                        raise ValueError(f"Baseline modality work unavailable: {kind}")
                    facts.extend(analysis.evidences)
                promotion = latest.get(PROMOTION_WORK)
                if promotion is None or promotion.status.value != "COMPLETED":
                    raise ValueError("Baseline promotion work unavailable")
                proposals = build_promotion_manifest(facts, duration_seconds=float(source.duration_seconds), config=DEFAULT_CONFIG)
                stored = session.scalars(select(SceneCandidate).where(
                    SceneCandidate.source_video_id == source_id,
                    SceneCandidate.discovery_method == SceneDiscoveryMethod.AUTONOMOUS,
                ).order_by(SceneCandidate.start_seconds, SceneCandidate.end_seconds, SceneCandidate.id)).all()
                if [(float(item.start_seconds), float(item.end_seconds)) for item in stored] != [
                    (item.start_seconds, item.end_seconds) for item in proposals
                ]:
                    raise ValueError("Baseline replay does not match stored candidate intervals")
                inputs = []
                for candidate, proposal in zip(stored, proposals):
                    linked = session.scalars(select(SceneEvidence).where(
                        SceneEvidence.scene_candidate_id == candidate.id,
                        SceneEvidence.source_reference == f"autonomous-work:{promotion.id}",
                    ).order_by(SceneEvidence.id)).all()
                    refs = tuple(EvidenceRef(str(item.id), item.modality.value, item.evidence_type,
                                             float(item.start_seconds), float(item.end_seconds)) for item in linked)
                    promotion_refs = []
                    for index in proposal.evidence_indexes:
                        fact = facts[index]
                        matched = next((ref for ref in refs if ref.identity == (
                            fact.modality.value, fact.evidence_type,
                            round(fact.interval.start_seconds, 3), round(fact.interval.end_seconds, 3),
                        )), None)
                        if matched is None:
                            raise ValueError("Baseline promotion evidence is missing from the candidate")
                        promotion_refs.append(matched)
                    if any(item.payload.get("promotion_rule") != proposal.rule_id for item in linked):
                        raise ValueError("Baseline stored promotion rule differs from replay")
                    inputs.append(CandidateInput(
                        str(candidate.id), str(source_id), float(candidate.start_seconds), float(candidate.end_seconds),
                        proposal.rule_id, tuple(promotion_refs), refs,
                    ))
                _validate(tuple(inputs))
                metadata = {
                    "work_ids": {kind: str(work.id) for kind, work in latest.items()},
                    "work_versions": {kind: work.producer_version for kind, work in latest.items()},
                    "work_result_fingerprints": {kind: work.result_fingerprint for kind, work in latest.items()},
                    "evidence_counts": {kind: sum(fact.modality.value == kind for fact in facts)
                                        for kind in ("TRANSCRIPT", "AUDIO", "VISUAL", "QUALITY")},
                }
                return float(source.duration_seconds), tuple(inputs), metadata
    finally:
        engine.dispose()


def _coverage(intervals: Iterable[tuple[float, float]], reference: tuple[float, float]) -> dict[str, float]:
    start, end = reference
    _validate_interval(start, end, "Reference interval")
    covered = sum(max(0, min(right, end) - max(left, start)) for left, right in _merge_intervals(intervals))
    return {"overlap_seconds": round(covered, 3), "coverage_fraction": round(covered / (end - start), 6)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-interval", nargs=2, type=float, metavar=("START", "END"))
    args = parser.parse_args()
    allowed = Path(__file__).resolve().parent / "tmp"
    output = args.output.resolve()
    if not output.is_relative_to(allowed.resolve()):
        parser.error("Output must be inside evaluation/tmp")
    if output.exists():
        parser.error("Output already exists; choose a fresh file")
    duration, candidates, metadata = _load_read_only(args.source_id)
    groups = group_candidates(candidates)
    if groups != group_candidates(tuple(reversed(candidates))):
        raise RuntimeError("Grouping is not deterministic under input reordering")
    report: dict[str, object] = {
        "status": "exploratory_offline_only", "version": VERSION,
        "source_id": str(args.source_id), "source_duration_seconds": duration,
        "baseline_replay": "PASS", "metadata": metadata,
        "baseline_candidates": [asdict(item) for item in candidates],
        "event_proposals": [asdict(item) for item in groups],
    }
    if args.reference_interval is not None:
        reference = tuple(args.reference_interval)
        report["posthoc_reference_only"] = {
            "interval": reference,
            "baseline_candidate_union": _coverage(
                ((item.start_seconds, item.end_seconds) for item in candidates), reference
            ),
            "group_envelope_union": _coverage(
                ((item.start_seconds, item.end_seconds) for item in groups), reference
            ),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"Baseline replay PASS: {len(candidates)} candidates; C: {len(groups)} proposals")
    print(f"Wrote isolated report: {output}")


if __name__ == "__main__":
    main()
