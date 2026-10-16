"""add project scene edit plan

Revision ID: ca3e4f5a6b7c
Revises: a7e9c4d1f2b8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ca3e4f5a6b7c"
down_revision: Union[str, Sequence[str], None] = "a7e9c4d1f2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_scene_edit_plans",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "project_scene_edit_plan_items",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_scene_edit_plan_position_nonnegative"),
        sa.ForeignKeyConstraint(["project_id"], ["project_scene_edit_plans.project_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["scene_candidates.id"]),
        sa.PrimaryKeyConstraint("project_id", "position"),
        sa.UniqueConstraint("project_id", "candidate_id", name="uq_scene_edit_plan_candidate"),
    )
    op.create_index("ix_scene_edit_plan_items_candidate_id", "project_scene_edit_plan_items", ["candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_scene_edit_plan_items_candidate_id", table_name="project_scene_edit_plan_items")
    op.drop_table("project_scene_edit_plan_items")
    op.drop_table("project_scene_edit_plans")
