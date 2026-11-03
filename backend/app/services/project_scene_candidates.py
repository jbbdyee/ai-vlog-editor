from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Project, SceneCandidate, SceneEvidence, SourceVideo, Transcript
from backend.app.services.scene_processing_state import active_candidate_ids


class SceneProjectNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CandidateEvidenceSummary:
    modality: str
    evidence_type: str
    count: int


@dataclass(frozen=True)
class ActiveCandidateSummary:
    candidate_id: UUID
    source_video_id: UUID
    start_seconds: Decimal
    end_seconds: Decimal
    evidence: tuple[CandidateEvidenceSummary, ...]
    transcript_text: str | None = None
    visual_caption: str | None = None  # VLM (non-authoritative) description
    visual_tags: tuple[str, ...] = ()
    visual_categories: tuple[str, ...] = ()


def _speech_in(segments: object, start: float, end: float, limit: int = 160) -> str | None:
    """STT text of segments overlapping [start, end) -- the words a user hears in the scene."""
    if not isinstance(segments, list):
        return None
    parts = []
    for item in segments:
        try:
            s, e, text = float(item["start_seconds"]), float(item["end_seconds"]), str(item["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text and s < end and start < e:
            parts.append(text)
    joined = " ".join(parts)
    return (joined[: limit - 1] + "…" if len(joined) > limit else joined) or None


def list_active_project_candidates(
    session: Session, project_id: UUID
) -> tuple[ActiveCandidateSummary, ...]:
    if session.get(Project, project_id) is None:
        raise SceneProjectNotFoundError

    active_ids = active_candidate_ids(session, project_id)
    if not active_ids:
        return ()

    candidates = session.scalars(
        select(SceneCandidate)
        .join(SourceVideo, SourceVideo.id == SceneCandidate.source_video_id)
        .where(SourceVideo.project_id == project_id, SceneCandidate.id.in_(active_ids))
        .order_by(
            SceneCandidate.source_video_id,
            SceneCandidate.start_seconds,
            SceneCandidate.end_seconds,
            SceneCandidate.id,
        )
    ).all()
    evidence_rows = session.scalars(
        select(SceneEvidence)
        .where(SceneEvidence.scene_candidate_id.in_(candidate.id for candidate in candidates))
        .order_by(SceneEvidence.scene_candidate_id, SceneEvidence.modality, SceneEvidence.evidence_type)
    ).all()
    source_ids = {candidate.source_video_id for candidate in candidates}
    segments_by_source = dict(session.execute(
        select(Transcript.source_video_id, Transcript.segments).where(Transcript.source_video_id.in_(source_ids))
    ).all()) if source_ids else {}
    summaries: dict[UUID, dict[tuple[str, str], int]] = {}
    visuals: dict[UUID, dict] = {}
    for row in evidence_rows:
        if row.evidence_type == "VLM_SCENE_CAPTION" and isinstance(row.payload, dict):
            previous = visuals.get(row.scene_candidate_id)
            if previous is None or row.created_at >= previous[0]:  # newest caption (newer captioner version) wins
                visuals[row.scene_candidate_id] = (row.created_at, row.payload)
        key = (row.modality.value, row.evidence_type)
        counts = summaries.setdefault(row.scene_candidate_id, {})
        counts[key] = counts.get(key, 0) + 1
    return tuple(
        ActiveCandidateSummary(
            candidate_id=candidate.id,
            source_video_id=candidate.source_video_id,
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
            evidence=tuple(
                CandidateEvidenceSummary(modality, evidence_type, count)
                for (modality, evidence_type), count in sorted(
                    summaries.get(candidate.id, {}).items()
                )
            ),
            transcript_text=_speech_in(segments_by_source.get(candidate.source_video_id),
                                       float(candidate.start_seconds), float(candidate.end_seconds)),
            visual_caption=visuals.get(candidate.id, (None, {}))[1].get("caption"),
            visual_tags=tuple(visuals.get(candidate.id, (None, {}))[1].get("tags") or ()),
            visual_categories=tuple(visuals.get(candidate.id, (None, {}))[1].get("categories") or ()),
        )
        for candidate in candidates
    )
