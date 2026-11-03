"""DB-owned render execution; files alone never grant download access."""

from __future__ import annotations

from concurrent.futures import Executor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, Thread
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Project, ProjectRenderRun
from backend.app.services.project_render_execution import RenderRunSnapshot, RenderRunStatus
from backend.app.services.project_rendering import (
    ProjectRenderError, ProjectRenderResult, _load_segments, plan_snapshot,
)
from backend.app.services.render_integrity import OutputIntegrityError, record_output_digest, same_file


LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 5
ACTIVE = ("QUEUED", "RUNNING")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def relative_output(project_id: UUID, render_id: UUID, filename: str) -> str:
    return f"projects/{project_id.hex}/renders/{render_id.hex}/{filename}"


def verified_output(root: Path, project_id: UUID, render_id: UUID, filename: str,
                    recorded: str | None, size: int | None) -> Path | None:
    """Reconstruct the only allowed path and reject symlinks at every level."""
    expected_rel = relative_output(project_id, render_id, filename)
    if recorded != expected_rel or size is None or size <= 0:
        return None
    try:
        root = Path(root).resolve(strict=True)
        path = root
        for part in expected_rel.split("/"):
            path = path / part
            if path.is_symlink():
                return None
        actual = path.resolve(strict=True)
        if not actual.is_relative_to(root) or not actual.is_file() or actual.stat().st_size != size:
            return None
        return actual
    except (OSError, RuntimeError, ValueError):
        return None


def _result(row: ProjectRenderRun, root: Path) -> ProjectRenderResult:
    base = Path(root) / relative_output(row.project_id, row.render_id, "final.mp4")
    return ProjectRenderResult(
        project_id=row.project_id, render_id=row.render_id, output_path=base,
        candidate_ids=tuple(UUID(item["candidate_id"]) for item in row.plan_snapshot),
        duration_seconds=row.duration_seconds or 0, video_codec=row.video_codec,
        audio_codec=row.audio_codec, file_size_bytes=row.base_size_bytes or 0,
        subtitle_path=(Path(root) / row.srt_relpath) if row.srt_relpath else None,
        subtitle_error_code=row.subtitle_error_code,
        hard_subtitle_path=(Path(root) / row.hard_relpath) if row.hard_relpath else None,
        hard_subtitle_error_code=row.hard_subtitle_error_code,
        hard_subtitle_size_bytes=row.hard_size_bytes,
        file_sha256=row.base_sha256,
        subtitle_size_bytes=row.srt_size_bytes,
        subtitle_sha256=row.srt_sha256,
        hard_subtitle_sha256=row.hard_sha256,
    )


def _optional_digest(path: Path, size: int) -> tuple[str, tuple] | None:
    try:
        return record_output_digest(path, size)
    except (OSError, OutputIntegrityError):
        return None


class PersistentProjectRenderRunRegistry:
    """One DB row per attempt; the executor holds no authoritative state."""

    persistent = True

    def __init__(self, executor: Executor, factory: sessionmaker[Session], output_root: Path) -> None:
        self._executor = executor
        self._factory = factory
        self._output_root = Path(output_root)

    def _interrupt_expired(self, session: Session, project_id: UUID) -> None:
        now = utcnow()
        expired = session.scalars(select(ProjectRenderRun).where(
            ProjectRenderRun.project_id == project_id,
            ProjectRenderRun.status.in_(ACTIVE),
            ProjectRenderRun.lease_expires_at < now - timedelta(seconds=LEASE_SECONDS),
        ).with_for_update()).all()
        for row in expired:
            # A different live API process may own this job. PostgreSQL advisory
            # locks are connection-scoped and released when its process exits.
            if session.get_bind().dialect.name == "postgresql":
                key = self._lock_key(project_id)
                available = session.execute(select(func.pg_try_advisory_lock(key))).scalar_one()
                if not available:
                    continue
                session.execute(select(func.pg_advisory_unlock(key)))
            partial = (self._output_root / relative_output(project_id, row.render_id, "final.mp4")).is_file()
            row.status = "RECONCILIATION_REQUIRED" if partial else "INTERRUPTED"
            row.finished_at = now
            row.owner_token = None
            row.safe_error_code = "RENDER_RECOVERY_REQUIRED" if partial else "RENDER_WORKER_INTERRUPTED"
            row.interrupted_reason = "LEASE_EXPIRED_OWNER_GONE"

    @staticmethod
    def _lock_key(project_id: UUID) -> int:
        return int.from_bytes(sha256(project_id.bytes).digest()[:8], "big", signed=True)

    def start(self, project_id: UUID,
              operation: Callable[[UUID, tuple[dict, ...]], ProjectRenderResult]) -> UUID | None:
        render_id, token = uuid4(), uuid4()
        with self._factory.begin() as session:
            project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if project is None:
                raise ProjectRenderError("PROJECT_NOT_FOUND", "Project was not found.")
            self._interrupt_expired(session, project_id)
            if session.scalar(select(ProjectRenderRun.render_id).where(
                    ProjectRenderRun.project_id == project_id, ProjectRenderRun.status.in_(ACTIVE))) is not None:
                return None
            selection = plan_snapshot(_load_segments(session, project_id))
            canonical = json.dumps(selection, sort_keys=True, separators=(",", ":"))
            now = utcnow()
            session.add(ProjectRenderRun(
                render_id=render_id, project_id=project_id, status="QUEUED",
                plan_snapshot=list(selection), plan_fingerprint=sha256(canonical.encode()).hexdigest(),
                created_at=now,
                owner_token=token, heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            ))
        stop = Event()
        lock_connection = None
        if self._factory.kw["bind"].dialect.name == "postgresql":
            lock_connection = self._factory.kw["bind"].connect()
            try:
                lock_connection.execute(select(func.pg_advisory_lock(self._lock_key(project_id))))
            except Exception:
                lock_connection.close()
                with self._factory.begin() as session:
                    session.execute(update(ProjectRenderRun).where(ProjectRenderRun.render_id == render_id)
                                    .values(status="FAILED", finished_at=utcnow(), owner_token=None,
                                            safe_error_code="RENDER_START_FAILED"))
                raise

        def heartbeat() -> None:
            while not stop.wait(HEARTBEAT_SECONDS):
                try:
                    with self._factory.begin() as session:
                        now = utcnow()
                        count = session.execute(update(ProjectRenderRun).where(
                            ProjectRenderRun.render_id == render_id,
                            ProjectRenderRun.owner_token == token,
                            ProjectRenderRun.status.in_(ACTIVE),
                        ).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))).rowcount
                    if not count:
                        break
                except Exception:
                    # A transient DB outage must not publish a success; finalization is fenced.
                    continue

        def run() -> None:
            try:
                with self._factory.begin() as session:
                    count = session.execute(update(ProjectRenderRun).where(
                        ProjectRenderRun.render_id == render_id,
                        ProjectRenderRun.owner_token == token,
                        ProjectRenderRun.status == "QUEUED",
                    ).values(status="RUNNING", started_at=utcnow())).rowcount
                if not count:
                    return
                result = operation(render_id, selection)
                if result.project_id != project_id or result.render_id != render_id:
                    raise ProjectRenderError("RENDER_PROJECT_MISMATCH", "Render result identity did not match.")
                base = verified_output(self._output_root, project_id, render_id, "final.mp4",
                                       relative_output(project_id, render_id, "final.mp4"), result.file_size_bytes)
                if base is None:
                    raise ProjectRenderError("OUTPUT_INVALID", "Final MP4 could not be verified.")
                # QA-03: no COMPLETED row without a digest of the exact verified base file.
                try:
                    base_sha, base_identity = record_output_digest(base, result.file_size_bytes)
                except (OSError, OutputIntegrityError) as error:
                    raise ProjectRenderError("OUTPUT_INTEGRITY_FAILED",
                                             "Final MP4 digest could not be recorded.") from error
                srt_rel = relative_output(project_id, render_id, "final.srt") if result.subtitle_path else None
                srt_size = srt_sha = srt_identity = srt_path = None
                subtitle_error = result.subtitle_error_code
                if srt_rel:
                    try:
                        srt_size = result.subtitle_path.stat().st_size
                        srt_path = (verified_output(self._output_root, project_id, render_id,
                                                    "final.srt", srt_rel, srt_size)
                                    if result.subtitle_path.resolve() == (self._output_root / srt_rel).resolve()
                                    else None)
                    except OSError:
                        srt_path = None
                    recorded = _optional_digest(srt_path, srt_size) if srt_path is not None else None
                    if recorded is None:
                        srt_rel, srt_size, srt_path = None, None, None
                        subtitle_error = "SUBTITLE_OUTPUT_INVALID"
                    else:
                        srt_sha, srt_identity = recorded
                hard_rel = relative_output(project_id, render_id, "final-subtitled.mp4") if result.hard_subtitle_path else None
                hard_size = hard_sha = hard_identity = hard_path = None
                hard_error = result.hard_subtitle_error_code
                if hard_rel:
                    try:
                        hard_size = result.hard_subtitle_path.stat().st_size
                        hard_path = (verified_output(self._output_root, project_id, render_id,
                                                     "final-subtitled.mp4", hard_rel, hard_size)
                                     if result.hard_subtitle_path.resolve() == (self._output_root / hard_rel).resolve()
                                     else None)
                    except OSError:
                        hard_path = None
                    recorded = _optional_digest(hard_path, hard_size) if hard_path is not None else None
                    if recorded is None:
                        hard_rel, hard_size, hard_path = None, None, None
                        hard_error = "SUBTITLE_OUTPUT_INVALID"
                    else:
                        hard_sha, hard_identity = recorded
                # Narrow the hash→commit window: identity must still match just before publishing.
                if not same_file(base, base_identity):
                    raise ProjectRenderError("OUTPUT_INTEGRITY_FAILED", "Final MP4 changed before completion.")
                if srt_path is not None and not same_file(srt_path, srt_identity):
                    srt_rel = srt_size = srt_sha = None
                    subtitle_error = "SUBTITLE_OUTPUT_INVALID"
                if hard_path is not None and not same_file(hard_path, hard_identity):
                    hard_rel = hard_size = hard_sha = None
                    hard_error = "SUBTITLE_OUTPUT_INVALID"
                with self._factory.begin() as session:
                    count = session.execute(update(ProjectRenderRun).where(
                        ProjectRenderRun.render_id == render_id,
                        ProjectRenderRun.owner_token == token,
                        ProjectRenderRun.status == "RUNNING",
                    ).values(status="COMPLETED", finished_at=utcnow(), owner_token=None,
                             base_relpath=relative_output(project_id, render_id, "final.mp4"),
                             base_size_bytes=result.file_size_bytes, duration_seconds=result.duration_seconds,
                             video_codec=result.video_codec, audio_codec=result.audio_codec,
                             base_sha256=base_sha,
                             srt_relpath=srt_rel, srt_size_bytes=srt_size, srt_sha256=srt_sha,
                             hard_relpath=hard_rel, hard_size_bytes=hard_size, hard_sha256=hard_sha,
                             subtitle_error_code=subtitle_error,
                             hard_subtitle_error_code=hard_error)).rowcount
                    if not count:
                        raise RuntimeError("Render ownership was lost before completion.")
            except Exception as error:
                code = error.code if isinstance(error, ProjectRenderError) else "PROJECT_RENDER_FAILED"
                partial = (self._output_root / relative_output(project_id, render_id, "final.mp4")).is_file()
                try:
                    with self._factory.begin() as session:
                        session.execute(update(ProjectRenderRun).where(
                            ProjectRenderRun.render_id == render_id,
                            ProjectRenderRun.owner_token == token,
                            ProjectRenderRun.status.in_(ACTIVE),
                        ).values(status="RECONCILIATION_REQUIRED" if partial else "FAILED",
                                 finished_at=utcnow(), owner_token=None,
                                 safe_error_code="RENDER_RECOVERY_REQUIRED" if partial else code))
                except Exception:
                    # Leave active row for lease-based interruption; never claim completion.
                    pass
            finally:
                stop.set()
                if lock_connection is not None:
                    try:
                        lock_connection.execute(select(func.pg_advisory_unlock(self._lock_key(project_id))))
                    finally:
                        lock_connection.close()

        Thread(target=heartbeat, name=f"render-lease-{render_id.hex[:8]}", daemon=True).start()
        try:
            self._executor.submit(run)
        except Exception:
            stop.set()
            if lock_connection is not None:
                try:
                    lock_connection.execute(select(func.pg_advisory_unlock(self._lock_key(project_id))))
                finally:
                    lock_connection.close()
            try:
                with self._factory.begin() as session:
                    session.execute(update(ProjectRenderRun).where(
                        ProjectRenderRun.render_id == render_id,
                        ProjectRenderRun.owner_token == token,
                        ProjectRenderRun.status == "QUEUED",
                    ).values(status="FAILED", finished_at=utcnow(), owner_token=None,
                             safe_error_code="RENDER_START_FAILED"))
            except Exception:
                pass
            raise
        return render_id

    def snapshot(self, project_id: UUID) -> RenderRunSnapshot:
        with self._factory.begin() as session:
            self._interrupt_expired(session, project_id)
            row = session.scalar(select(ProjectRenderRun).where(ProjectRenderRun.project_id == project_id)
                                 .order_by(ProjectRenderRun.created_at.desc(), ProjectRenderRun.render_id.desc()).limit(1))
            if row is None:
                return RenderRunSnapshot(RenderRunStatus.NOT_STARTED)
            return RenderRunSnapshot(RenderRunStatus(row.status),
                                     _result(row, self._output_root) if row.status == "COMPLETED" else None,
                                     row.safe_error_code, row.render_id)

    def is_active(self, project_id: UUID) -> bool:
        return self.snapshot(project_id).status in {RenderRunStatus.QUEUED, RenderRunStatus.RUNNING}

    def completed_result(self, project_id: UUID, render_id: UUID) -> ProjectRenderResult | None:
        with self._factory() as session:
            row = session.get(ProjectRenderRun, render_id)
            if row is None or row.project_id != project_id or row.status != "COMPLETED":
                return None
            return _result(row, self._output_root)

    def run_status(self, project_id: UUID, render_id: UUID) -> RenderRunStatus | None:
        with self._factory() as session:
            row = session.get(ProjectRenderRun, render_id)
            return RenderRunStatus(row.status) if row is not None and row.project_id == project_id else None

    def history(self, project_id: UUID, limit: int = 20, before: UUID | None = None) -> tuple[list[RenderRunSnapshot], UUID | None]:
        with self._factory.begin() as session:
            self._interrupt_expired(session, project_id)
            query = select(ProjectRenderRun).where(ProjectRenderRun.project_id == project_id)
            if before is not None:
                cursor = session.get(ProjectRenderRun, before)
                if cursor is None or cursor.project_id != project_id:
                    return [], None
                query = query.where(or_(ProjectRenderRun.created_at < cursor.created_at,
                                        and_(ProjectRenderRun.created_at == cursor.created_at,
                                             ProjectRenderRun.render_id < cursor.render_id)))
            rows = session.scalars(query.order_by(ProjectRenderRun.created_at.desc(),
                                                   ProjectRenderRun.render_id.desc()).limit(limit + 1)).all()
            more = len(rows) > limit
            rows = rows[:limit]
            return ([RenderRunSnapshot(RenderRunStatus(row.status),
                                       _result(row, self._output_root) if row.status == "COMPLETED" else None,
                                       row.safe_error_code, row.render_id) for row in rows],
                    rows[-1].render_id if more else None)
