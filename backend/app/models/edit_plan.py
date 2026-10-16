"""User-owned ordered scene selection, separate from AI SceneCandidate evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base
from backend.app.models.product import TimestampMixin


class ProjectSceneEditPlan(TimestampMixin, Base):
    __tablename__ = "project_scene_edit_plans"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    items: Mapped[list[ProjectSceneEditPlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="ProjectSceneEditPlanItem.position"
    )


class ProjectSceneEditPlanItem(Base):
    __tablename__ = "project_scene_edit_plan_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_scene_edit_plan_position_nonnegative"),
        UniqueConstraint("project_id", "candidate_id", name="uq_scene_edit_plan_candidate"),
        Index("ix_scene_edit_plan_items_candidate_id", "candidate_id"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_scene_edit_plans.project_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("scene_candidates.id"), nullable=False)

    plan: Mapped[ProjectSceneEditPlan] = relationship(back_populates="items")
