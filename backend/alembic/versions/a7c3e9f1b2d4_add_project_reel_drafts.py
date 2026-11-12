"""add short-form reel drafts

Revision ID: a7c3e9f1b2d4
Revises: f1d8a3b5c7e9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, Sequence[str], None] = "f1d8a3b5c7e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New table only: nothing existing changes.
    op.create_table(
        "project_reel_drafts",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("pace", sa.String(16), nullable=False),
        sa.Column("target_seconds", sa.Integer(), nullable=False),
        sa.Column("analysis_fingerprint", sa.String(64), nullable=False),
        sa.Column("shots", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("project_reel_drafts")
