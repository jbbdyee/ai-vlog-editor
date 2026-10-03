"""add scene work result candidate links

Revision ID: a7e9c4d1f2b8
Revises: f4c2a91d7b6e
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7e9c4d1f2b8"
down_revision: Union[str, Sequence[str], None] = "f4c2a91d7b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scene_analysis_work_result_candidates",
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("scene_candidate_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["work_item_id"], ["scene_analysis_work_items.id"]),
        sa.ForeignKeyConstraint(["scene_candidate_id"], ["scene_candidates.id"]),
        sa.PrimaryKeyConstraint("work_item_id", "scene_candidate_id"),
    )
    op.create_index(
        "ix_scene_work_result_candidates_candidate_id",
        "scene_analysis_work_result_candidates",
        ["scene_candidate_id"],
    )
    op.execute(
        sa.text(
            "INSERT INTO scene_analysis_work_result_candidates "
            "(work_item_id, scene_candidate_id) "
            "SELECT analysis_work_item_id, id FROM scene_candidates "
            "WHERE analysis_work_item_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scene_work_result_candidates_candidate_id",
        table_name="scene_analysis_work_result_candidates",
    )
    op.drop_table("scene_analysis_work_result_candidates")
