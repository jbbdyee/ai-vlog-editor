"""add durable Project render run records

Revision ID: b8c01e2a4f60
Revises: ca3e4f5a6b7c
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c01e2a4f60"
down_revision: Union[str, Sequence[str], None] = "ca3e4f5a6b7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_render_runs",
        sa.Column("render_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False),
        sa.Column("plan_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("base_relpath", sa.String(255)),
        sa.Column("base_size_bytes", sa.BigInteger()),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("video_codec", sa.String(64)),
        sa.Column("audio_codec", sa.String(64)),
        sa.Column("srt_relpath", sa.String(255)),
        sa.Column("srt_size_bytes", sa.BigInteger()),
        sa.Column("hard_relpath", sa.String(255)),
        sa.Column("hard_size_bytes", sa.BigInteger()),
        sa.Column("safe_error_code", sa.String(64)),
        sa.Column("subtitle_error_code", sa.String(64)),
        sa.Column("hard_subtitle_error_code", sa.String(64)),
        sa.Column("owner_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("interrupted_reason", sa.String(64)),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'RECONCILIATION_REQUIRED')",
            name="ck_project_render_runs_status",
        ),
    )
    op.create_index("ix_project_render_runs_project_created", "project_render_runs", ["project_id", "created_at", "render_id"])
    op.create_index("uq_project_render_runs_active_project", "project_render_runs", ["project_id"], unique=True,
                    postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING')"))


def downgrade() -> None:
    op.drop_index("uq_project_render_runs_active_project", table_name="project_render_runs")
    op.drop_index("ix_project_render_runs_project_created", table_name="project_render_runs")
    op.drop_table("project_render_runs")
