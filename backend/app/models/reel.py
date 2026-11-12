"""TODO 10: the latest short-form reel draft per Project, plus the slow shot analysis it was built from."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base
from backend.app.models.product import TimestampMixin


class ProjectReelDraft(TimestampMixin, Base):
    __tablename__ = "project_reel_drafts"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    pace: Mapped[str] = mapped_column(String(16), nullable=False)
    target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # Shots (time ranges + screen description + speech) are reused while the videos stay the same.
    analysis_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    shots: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    draft: Mapped[dict] = mapped_column(JSON, nullable=False)
