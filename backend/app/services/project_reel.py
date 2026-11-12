"""TODO 10: run a reel draft in the background (describing every shot takes minutes) and keep the latest one."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Project, SourceVideo
from backend.app.models.reel import ProjectReelDraft
from backend.app.services.media_probe import probe_media
from backend.app.services.reel_draft import (ReelDraft, SourceInput, analysis_fingerprint, analyze_shots, build_draft,
                                             draft_from_json, shots_from_json, shots_to_json)


class ReelProjectNotFound(LookupError):
    pass


@dataclass
class ReelJob:
    status: str = "IDLE"  # IDLE | RUNNING | COMPLETED | FAILED
    step: str = ""
    done: int = 0
    total: int = 0
    error_code: str | None = None


@dataclass(frozen=True)
class ReelOptions:
    mode: str
    pace: str
    target_seconds: int


_jobs: dict[UUID, ReelJob] = {}
_lock = threading.Lock()


def load_sources(session: Session, project_id: UUID, resolve: Callable[[str], Path]) -> list[SourceInput]:
    if session.get(Project, project_id) is None:
        raise ReelProjectNotFound(str(project_id))
    rows = session.scalars(select(SourceVideo).where(SourceVideo.project_id == project_id)
                           .order_by(SourceVideo.created_at, SourceVideo.id)).all()
    sources = []
    for row in rows:
        path = resolve(row.storage_reference)
        if not path.is_file():
            continue
        duration = float(row.duration_seconds) if row.duration_seconds else probe_media(path).duration_seconds
        segments = row.transcript.segments if row.transcript is not None else ()
        sources.append(SourceInput(row.id, row.original_filename, path, duration, tuple(segments or ())))
    return sources


def job_state(project_id: UUID) -> ReelJob:
    with _lock:
        job = _jobs.get(project_id)
        return ReelJob(**vars(job)) if job else ReelJob()


def saved_draft(session: Session, project_id: UUID) -> ReelDraft | None:
    if session.get(Project, project_id) is None:
        raise ReelProjectNotFound(str(project_id))
    record = session.get(ProjectReelDraft, project_id)
    return draft_from_json(record.draft) if record is not None else None


def start_reel_draft(project_id: UUID, factory: sessionmaker[Session], resolve: Callable[[str], Path],
                     options: ReelOptions, *, analyze=None, build=None, background: bool = True) -> bool:
    """False when a draft for this project is already being made."""
    with _lock:
        if project_id in _jobs and _jobs[project_id].status == "RUNNING":
            return False
        _jobs[project_id] = ReelJob(status="RUNNING", step="영상 확인")
    work = lambda: _run(project_id, factory, resolve, options, analyze or analyze_shots, build or build_draft)  # noqa: E731
    if background:
        threading.Thread(target=work, name=f"reel-draft-{project_id}", daemon=True).start()
    else:
        work()
    return True


def _update(project_id: UUID, **changes) -> None:
    with _lock:
        for key, value in changes.items():
            setattr(_jobs[project_id], key, value)


def _run(project_id, factory, resolve, options, analyze, build) -> None:
    try:
        with factory() as session:
            sources = load_sources(session, project_id, resolve)
            record = session.get(ProjectReelDraft, project_id)
            cached = (shots_from_json(record.shots) if record is not None
                      and record.analysis_fingerprint == analysis_fingerprint(sources) else None)
        if not sources:
            _update(project_id, status="FAILED", error_code="NO_SOURCE_VIDEOS")
            return
        fingerprint = analysis_fingerprint(sources)
        if cached:
            shots = cached
        else:
            _update(project_id, step="장면 나누고 화면 설명하기")
            shots = analyze(sources, on_progress=lambda done, total: _update(project_id, done=done, total=total))
        if not shots:
            _update(project_id, status="FAILED", error_code="NO_SHOTS")
            return
        _update(project_id, step="AI가 릴스 초안 짜기")
        draft = build(shots, mode_key=options.mode, pace_key=options.pace, target_seconds=options.target_seconds)
        with factory() as session:
            record = session.get(ProjectReelDraft, project_id) or ProjectReelDraft(project_id=project_id)
            record.format, record.mode, record.pace = "short", draft.mode, options.pace
            record.target_seconds = options.target_seconds
            record.analysis_fingerprint, record.shots, record.draft = fingerprint, shots_to_json(shots), draft.to_json()
            session.add(record)
            session.commit()
        _update(project_id, status="COMPLETED", step="완료")
    except ReelProjectNotFound:
        _update(project_id, status="FAILED", error_code="PROJECT_NOT_FOUND")
    except Exception:  # noqa: BLE001 - the screen shows a safe code; details stay in the server log
        import logging
        logging.getLogger(__name__).exception("reel draft failed")
        _update(project_id, status="FAILED", error_code="REEL_DRAFT_FAILED")
