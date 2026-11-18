"""widen scene analysis work result_reference (TODO 32-2)

Talk-heavy videos produce many audio-activity spans (0797: 101) and their compressed result no longer fits in
1024 characters, so scene analysis failed for 16 of 35 videos of the 학원 하루 project. Existing values are kept.

Revision ID: b8d2f4a6c1e3
Revises: a7c3e9f1b2d4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8d2f4a6c1e3"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("scene_analysis_work_items", "result_reference",
                    existing_type=sa.String(length=1024), type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("scene_analysis_work_items", "result_reference",
                    existing_type=sa.Text(), type_=sa.String(length=1024), existing_nullable=True)
