"""add widened clip range to scene edit plan items

Revision ID: f1d8a3b5c7e9
Revises: e3a1c9d27b45
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1d8a3b5c7e9"
down_revision: Union[str, Sequence[str], None] = "e3a1c9d27b45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New nullable columns only: existing plans keep NULL and render their original candidate range.
    op.add_column("project_scene_edit_plan_items", sa.Column("clip_start_seconds", sa.Numeric(12, 3), nullable=True))
    op.add_column("project_scene_edit_plan_items", sa.Column("clip_end_seconds", sa.Numeric(12, 3), nullable=True))
    op.create_check_constraint(
        "ck_scene_edit_plan_clip_range", "project_scene_edit_plan_items",
        "(clip_start_seconds IS NULL AND clip_end_seconds IS NULL) OR "
        "(clip_start_seconds >= 0 AND clip_end_seconds > clip_start_seconds)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_scene_edit_plan_clip_range", "project_scene_edit_plan_items", type_="check")
    op.drop_column("project_scene_edit_plan_items", "clip_end_seconds")
    op.drop_column("project_scene_edit_plan_items", "clip_start_seconds")
