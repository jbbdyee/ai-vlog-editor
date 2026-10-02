"""add scene intelligence data foundation

Revision ID: f4c2a91d7b6e
Revises: db81de89b2b5
Create Date: 2026-10-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c2a91d7b6e"
down_revision: Union[str, Sequence[str], None] = "db81de89b2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scene_analysis_work_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_video_id", sa.Uuid(), nullable=True),
        sa.Column("work_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="scene_analysis_work_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.String(length=512), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("producer_version", sa.String(length=128), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=512), nullable=True),
        sa.Column("result_reference", sa.String(length=1024), nullable=True),
        sa.Column("result_fingerprint", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(target_type IS NULL AND target_id IS NULL) OR "
            "(target_type IS NOT NULL AND target_id IS NOT NULL)",
            name="ck_scene_work_items_target_pair",
        ),
        sa.CheckConstraint(
            "length(trim(work_type)) > 0",
            name="ck_scene_work_items_work_type_nonempty",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_video_id"], ["source_videos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scene_work_items_project_id",
        "scene_analysis_work_items",
        ["project_id"],
    )
    op.create_index(
        "ix_scene_work_items_source_work_type",
        "scene_analysis_work_items",
        ["source_video_id", "work_type"],
    )
    op.create_index(
        "ix_scene_work_items_status", "scene_analysis_work_items", ["status"]
    )

    op.create_table(
        "event_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("producer_version", sa.String(length=128), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=512), nullable=True),
        sa.Column("result_fingerprint", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_groups_project_id", "event_groups", ["project_id"])

    op.create_table(
        "scene_analysis_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="scene_analysis_attempt_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_error_message", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name="ck_scene_attempts_number_positive"
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_scene_attempts_time_order",
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["scene_analysis_work_items.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_item_id",
            "attempt_number",
            name="uq_scene_attempts_work_item_number",
        ),
    )
    op.create_index(
        "ix_scene_attempts_work_item_id", "scene_analysis_attempts", ["work_item_id"]
    )

    op.create_table(
        "scene_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_video_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_work_item_id", sa.Uuid(), nullable=True),
        sa.Column("start_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column(
            "discovery_method",
            sa.Enum(
                "MEMO_GUIDED",
                "AUTONOMOUS",
                name="scene_discovery_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=512), nullable=False),
        sa.Column("result_fingerprint", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_scene_candidates_confidence_range",
        ),
        sa.CheckConstraint(
            "start_seconds >= 0", name="ck_scene_candidates_start_nonnegative"
        ),
        sa.CheckConstraint(
            "end_seconds > start_seconds", name="ck_scene_candidates_time_order"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_work_item_id"], ["scene_analysis_work_items.id"]
        ),
        sa.ForeignKeyConstraint(["source_video_id"], ["source_videos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scene_candidates_source_discovery",
        "scene_candidates",
        ["source_video_id", "discovery_method"],
    )
    op.create_index(
        "ix_scene_candidates_source_interval",
        "scene_candidates",
        ["source_video_id", "start_seconds", "end_seconds"],
    )
    op.create_index(
        "ix_scene_candidates_source_video_id", "scene_candidates", ["source_video_id"]
    )

    op.create_table(
        "event_group_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_group_id", sa.Uuid(), nullable=False),
        sa.Column("scene_candidate_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_group_id"], ["event_groups.id"]),
        sa.ForeignKeyConstraint(["scene_candidate_id"], ["scene_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_group_id",
            "scene_candidate_id",
            name="uq_event_group_members_group_candidate",
        ),
    )
    op.create_index(
        "ix_event_group_members_candidate_id",
        "event_group_members",
        ["scene_candidate_id"],
    )

    op.create_table(
        "scene_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scene_candidate_id", sa.Uuid(), nullable=False),
        sa.Column(
            "modality",
            sa.Enum(
                "MEMO",
                "TRANSCRIPT",
                "AUDIO",
                "VISUAL",
                "SHOT",
                "QUALITY",
                "MULTIMODAL",
                name="scene_evidence_modality",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("start_seconds", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("end_seconds", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_schema_version", sa.String(length=32), nullable=False),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("producer_version", sa.String(length=128), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=512), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=512), nullable=True),
        sa.Column("result_fingerprint", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_scene_evidences_confidence_range",
        ),
        sa.CheckConstraint(
            "(start_seconds IS NULL AND end_seconds IS NULL) OR "
            "(start_seconds IS NOT NULL AND end_seconds IS NOT NULL)",
            name="ck_scene_evidences_interval_pair",
        ),
        sa.CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0",
            name="ck_scene_evidences_start_nonnegative",
        ),
        sa.CheckConstraint(
            "start_seconds IS NULL OR end_seconds > start_seconds",
            name="ck_scene_evidences_time_order",
        ),
        sa.CheckConstraint(
            "length(trim(evidence_type)) > 0",
            name="ck_scene_evidences_type_nonempty",
        ),
        sa.ForeignKeyConstraint(["scene_candidate_id"], ["scene_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scene_evidences_candidate_id", "scene_evidences", ["scene_candidate_id"]
    )
    op.create_index(
        "ix_scene_evidences_modality_type",
        "scene_evidences",
        ["modality", "evidence_type"],
    )

    op.create_table(
        "scene_relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_scene_candidate_id", sa.Uuid(), nullable=False),
        sa.Column("target_scene_candidate_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relation_type",
            sa.Enum(
                "SAME_EVENT",
                "CONTINUATION",
                "REACTION_TO",
                "DUPLICATE",
                name="scene_relation_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("producer", sa.String(length=128), nullable=False),
        sa.Column("producer_version", sa.String(length=128), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_scene_relations_confidence_range",
        ),
        sa.CheckConstraint(
            "source_scene_candidate_id <> target_scene_candidate_id",
            name="ck_scene_relations_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["source_scene_candidate_id"], ["scene_candidates.id"]
        ),
        sa.ForeignKeyConstraint(
            ["target_scene_candidate_id"], ["scene_candidates.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_scene_candidate_id",
            "target_scene_candidate_id",
            "relation_type",
            name="uq_scene_relations_source_target_type",
        ),
    )
    op.create_index(
        "ix_scene_relations_source_id",
        "scene_relations",
        ["source_scene_candidate_id"],
    )
    op.create_index(
        "ix_scene_relations_target_id",
        "scene_relations",
        ["target_scene_candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scene_relations_target_id", table_name="scene_relations")
    op.drop_index("ix_scene_relations_source_id", table_name="scene_relations")
    op.drop_table("scene_relations")
    op.drop_index("ix_scene_evidences_modality_type", table_name="scene_evidences")
    op.drop_index("ix_scene_evidences_candidate_id", table_name="scene_evidences")
    op.drop_table("scene_evidences")
    op.drop_index(
        "ix_event_group_members_candidate_id", table_name="event_group_members"
    )
    op.drop_table("event_group_members")
    op.drop_index("ix_scene_candidates_source_video_id", table_name="scene_candidates")
    op.drop_index("ix_scene_candidates_source_interval", table_name="scene_candidates")
    op.drop_index("ix_scene_candidates_source_discovery", table_name="scene_candidates")
    op.drop_table("scene_candidates")
    op.drop_index(
        "ix_scene_attempts_work_item_id", table_name="scene_analysis_attempts"
    )
    op.drop_table("scene_analysis_attempts")
    op.drop_index("ix_event_groups_project_id", table_name="event_groups")
    op.drop_table("event_groups")
    op.drop_index("ix_scene_work_items_status", table_name="scene_analysis_work_items")
    op.drop_index(
        "ix_scene_work_items_source_work_type",
        table_name="scene_analysis_work_items",
    )
    op.drop_index(
        "ix_scene_work_items_project_id", table_name="scene_analysis_work_items"
    )
    op.drop_table("scene_analysis_work_items")
