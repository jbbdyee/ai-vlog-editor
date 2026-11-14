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
from backend.app.services.reel_chat import EditResult
from backend.app.services.reel_draft import (HISTORY_KEY, PREVIOUS_KEY, ReelDraft, Shot, SourceInput,
                                             analysis_fingerprint, analyze_shots, build_draft, draft_from_json, shots_from_json, shots_to_json)


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


MAX_HISTORY = 10  # TODO 18: how many chat edits can be undone


def _history(data: dict) -> list[dict]:
    """[{"draft": ..., "change": "3번 장면 2.0초 → 3.0초"}], newest first. Older saves kept one previous draft."""
    history = data.get(HISTORY_KEY)
    if isinstance(history, list):
        return [entry for entry in history if isinstance(entry, dict) and entry.get("draft")]
    previous = data.get(PREVIOUS_KEY)
    return [{"draft": previous, "change": ""}] if previous else []


def edit_history(session: Session, project_id: UUID) -> list[dict]:
    record = session.get(ProjectReelDraft, project_id)
    return _history(record.draft) if record is not None else []


def can_undo(session: Session, project_id: UUID) -> bool:
    return bool(edit_history(session, project_id))


def unused_shots(session: Session, project_id: UUID) -> list[Shot]:
    """TODO 18: the cuts the draft does not use, in filmed order."""
    record = session.get(ProjectReelDraft, project_id)
    if record is None:
        return []
    used = {scene["shot_index"] for scene in record.draft.get("scenes", ())}
    return [shot for shot in shots_from_json(record.shots) if shot.index not in used]


# --- TODO 16: change the saved draft by talking to it ---

class ReelEditRefused(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _busy(project_id: UUID) -> str | None:
    with _lock:
        if project_id in _jobs and _jobs[project_id].status == "RUNNING":
            return "REEL_DRAFT_RUNNING"
    # TODO 18: a video being made read its draft when it started, so editing meanwhile is safe; the screen makes
    # the video again afterwards when the draft moved on.
    return None


def edit_reel_draft(factory: sessionmaker[Session], project_id: UUID, message: str, selected: int | None,
                    *, complete=...) -> EditResult:
    """Read the sentence, apply it and save; the draft before it is kept for one "되돌리기"."""
    from backend.app.services.llm_edit_interpreter import configured_engine
    from backend.app.services.reel_chat import NotUnderstood, apply_edits, understand

    if complete is ...:
        engine = configured_engine()
        complete = engine[2] if engine else None
    if (code := _busy(project_id)) is not None:
        raise ReelEditRefused(code)
    with factory() as session:
        draft = saved_draft(session, project_id)
        record = session.get(ProjectReelDraft, project_id)
        if draft is None:
            raise ReelEditRefused("REEL_DRAFT_MISSING")
        shots = shots_from_json(record.shots)
        history = _history(record.draft)
    if selected is not None and not 1 <= selected <= len(draft.scenes):
        selected = None
    try:
        edits, _ = understand(message, draft, selected, complete, shots)
    except NotUnderstood as error:
        raise ReelEditRefused("REEL_EDIT_NOT_UNDERSTOOD") from error
    earlier = [draft_from_json(entry["draft"]) for entry in history]
    result = apply_edits(draft, shots, edits, complete=complete, earlier=earlier)
    if result.done:
        entry = {"draft": draft.to_json(), "change": " · ".join(result.done)}
        with factory() as session:
            record = session.get(ProjectReelDraft, project_id)
            record.draft = {**result.draft.to_json(), HISTORY_KEY: [entry, *history][:MAX_HISTORY]}
            session.commit()
    return result


def undo_reel_draft(factory: sessionmaker[Session], project_id: UUID) -> str:
    """Go back one chat edit; returns what that edit had changed ("" for older saves)."""
    if (code := _busy(project_id)) is not None:
        raise ReelEditRefused(code)
    with factory() as session:
        if session.get(Project, project_id) is None:
            raise ReelProjectNotFound(str(project_id))
        record = session.get(ProjectReelDraft, project_id)
        history = _history(record.draft) if record is not None else []
        if not history:
            raise ReelEditRefused("REEL_UNDO_EMPTY")
        last, rest = history[0], history[1:]
        record.draft = {**last["draft"], HISTORY_KEY: rest}
        session.commit()
        return str(last.get("change") or "")


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


# --- TODO 12: make the vertical video from the saved draft (also in the background; it takes a minute or two) ---

_render_jobs: dict[UUID, ReelJob] = {}


def reel_output_dir(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "reel"


def render_job_state(project_id: UUID) -> ReelJob:
    with _lock:
        job = _render_jobs.get(project_id)
        return ReelJob(**vars(job)) if job else ReelJob()


def start_reel_render(project_id: UUID, factory: sessionmaker[Session], resolve: Callable[[str], Path],
                      output_root: Path, *, render=None, background: bool = True, text_style=None) -> str | None:
    """None when started, otherwise a reason code (no draft yet, a draft or a video is being made)."""
    from backend.app.services.reel_render import render_reel

    with factory() as session:
        if saved_draft(session, project_id) is None:
            return "REEL_DRAFT_MISSING"
    with _lock:
        if project_id in _jobs and _jobs[project_id].status == "RUNNING":
            return "REEL_DRAFT_RUNNING"
        if project_id in _render_jobs and _render_jobs[project_id].status == "RUNNING":
            return "REEL_VIDEO_RUNNING"
        _render_jobs[project_id] = ReelJob(status="RUNNING", step="영상 확인")
    work = lambda: _render(project_id, factory, resolve, output_root, render or render_reel, text_style)  # noqa: E731
    if background:
        threading.Thread(target=work, name=f"reel-video-{project_id}", daemon=True).start()
    else:
        work()
    return None


def _update_render(project_id: UUID, **changes) -> None:
    with _lock:
        for key, value in changes.items():
            setattr(_render_jobs[project_id], key, value)


def _render(project_id, factory, resolve, output_root, render, text_style=None) -> None:
    from backend.app.services.reel_render import ReelRenderError

    try:
        with factory() as session:
            draft = saved_draft(session, project_id)
            rows = session.scalars(select(SourceVideo).where(SourceVideo.project_id == project_id)).all()
            sources = {str(row.id): resolve(row.storage_reference) for row in rows}
        render(draft, sources, reel_output_dir(output_root, project_id), text_style=text_style,
               on_progress=lambda step, done, total: _update_render(project_id, step=step, done=done, total=total))
        _update_render(project_id, status="COMPLETED", step="완료")
    except ReelRenderError as error:
        import logging
        logging.getLogger(__name__).warning("reel video failed: %s", error)
        _update_render(project_id, status="FAILED", error_code=error.code)
    except Exception:  # noqa: BLE001 - the screen shows a safe code; details stay in the server log
        import logging
        logging.getLogger(__name__).exception("reel video failed")
        _update_render(project_id, status="FAILED", error_code="REEL_VIDEO_FAILED")
