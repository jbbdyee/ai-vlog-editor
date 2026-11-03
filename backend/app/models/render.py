"""Persistent execution and verified output metadata for one Project render."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, JSON, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


def sha256_format_check(column: str) -> str:
    """NULL or exactly 64 lowercase hex characters; portable to PostgreSQL and SQLite."""
    return (f"{column} IS NULL OR (length({column}) = 64 "
            f"AND ltrim({column}, '0123456789abcdef') = '')")


class ProjectRenderRun(Base):
    __tablename__ = "project_render_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'RECONCILIATION_REQUIRED')",
            name="ck_project_render_runs_status",
        ),
        CheckConstraint(sha256_format_check("base_sha256"), name="ck_project_render_runs_base_sha256"),
        CheckConstraint(sha256_format_check("srt_sha256"), name="ck_project_render_runs_srt_sha256"),
        CheckConstraint(sha256_format_check("hard_sha256"), name="ck_project_render_runs_hard_sha256"),
        Index("ix_project_render_runs_project_created", "project_id", "created_at", "render_id"),
        Index(
            "uq_project_render_runs_active_project", "project_id", unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
            sqlite_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    render_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_snapshot: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_relpath: Mapped[str | None] = mapped_column(String(255))
    base_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))
    srt_relpath: Mapped[str | None] = mapped_column(String(255))
    srt_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    hard_relpath: Mapped[str | None] = mapped_column(String(255))
    hard_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # QA-03 content digests. NULL on rows completed before revision e3a1c9d27b45;
    # such rows stay COMPLETED but are never served (UNVERIFIED).
    base_sha256: Mapped[str | None] = mapped_column(String(64))
    srt_sha256: Mapped[str | None] = mapped_column(String(64))
    hard_sha256: Mapped[str | None] = mapped_column(String(64))
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    subtitle_error_code: Mapped[str | None] = mapped_column(String(64))
    hard_subtitle_error_code: Mapped[str | None] = mapped_column(String(64))
    owner_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interrupted_reason: Mapped[str | None] = mapped_column(String(64))
