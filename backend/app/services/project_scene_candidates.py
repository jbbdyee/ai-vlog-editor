from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Project, SceneCandidate, SceneEvidence, SourceVideo
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
    summaries: dict[UUID, dict[tuple[str, str], int]] = {}
    for row in evidence_rows:
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
        )
        for candidate in candidates
    )
