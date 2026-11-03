"""add SHA-256 content digests to Project render outputs (QA-03)

Revision ID: e3a1c9d27b45
Revises: b8c01e2a4f60

Existing rows keep NULL digests: no backfill, no status change. The application
treats a NULL digest as UNVERIFIED and does not serve that file. Downgrade drops
the three columns and therefore destroys recorded digest evidence; do not run it
on a database with real render history without a backup and explicit approval.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e3a1c9d27b45"
down_revision: Union[str, Sequence[str], None] = "b8c01e2a4f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("base_sha256", "srt_sha256", "hard_sha256")


def _check(column: str) -> str:
    # Same text as backend.app.models.render.sha256_format_check; duplicated so the
    # migration stays frozen if the model helper changes later.
    return f"{column} IS NULL OR (length({column}) = 64 AND ltrim({column}, '0123456789abcdef') = '')"


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("project_render_runs", sa.Column(column, sa.String(64), nullable=True))
    for column in _COLUMNS:
        op.create_check_constraint(f"ck_project_render_runs_{column}", "project_render_runs", _check(column))


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_constraint(f"ck_project_render_runs_{column}", "project_render_runs", type_="check")
    for column in reversed(_COLUMNS):
        op.drop_column("project_render_runs", column)
