from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base
from backend.app.models.product import Project, SourceVideo, TimestampMixin, _enum_type


class SceneDiscoveryMethod(str, Enum):
    MEMO_GUIDED = "MEMO_GUIDED"
    AUTONOMOUS = "AUTONOMOUS"


class SceneEvidenceModality(str, Enum):
    MEMO = "MEMO"
    TRANSCRIPT = "TRANSCRIPT"
    AUDIO = "AUDIO"
    VISUAL = "VISUAL"
    SHOT = "SHOT"
    QUALITY = "QUALITY"
    MULTIMODAL = "MULTIMODAL"


class SceneRelationType(str, Enum):
    SAME_EVENT = "SAME_EVENT"
    CONTINUATION = "CONTINUATION"
    REACTION_TO = "REACTION_TO"
    DUPLICATE = "DUPLICATE"


class SceneAnalysisWorkStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SceneAnalysisAttemptStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SceneAnalysisWorkItem(TimestampMixin, Base):
    __tablename__ = "scene_analysis_work_items"
    __table_args__ = (
        CheckConstraint("length(trim(work_type)) > 0", name="ck_scene_work_items_work_type_nonempty"),
        CheckConstraint(
            "(target_type IS NULL AND target_id IS NULL) OR "
            "(target_type IS NOT NULL AND target_id IS NOT NULL)",
            name="ck_scene_work_items_target_pair",
        ),
        Index("ix_scene_work_items_project_id", "project_id"),
        Index("ix_scene_work_items_source_work_type", "source_video_id", "work_type"),
        Index("ix_scene_work_items_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    source_video_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_videos.id"), nullable=True
    )
    work_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[SceneAnalysisWorkStatus] = mapped_column(
        _enum_type(SceneAnalysisWorkStatus, "scene_analysis_work_status", 32),
        nullable=False,
        default=SceneAnalysisWorkStatus.PENDING,
    )
    input_fingerprint: Mapped[str] = mapped_column(String(512), nullable=False)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    config_fingerprint: Mapped[str | None] = mapped_column(String(512))
    result_reference: Mapped[str | None] = mapped_column(String(1024))
    result_fingerprint: Mapped[str | None] = mapped_column(String(512))

    project: Mapped[Project] = relationship(back_populates="scene_analysis_work_items")
    source_video: Mapped[SourceVideo | None] = relationship(
        back_populates="scene_analysis_work_items"
    )
    attempts: Mapped[list[SceneAnalysisAttempt]] = relationship(
        back_populates="work_item", passive_deletes=True
    )
    scene_candidates: Mapped[list[SceneCandidate]] = relationship(
        back_populates="analysis_work_item", passive_deletes=True
    )


class SceneAnalysisAttempt(Base):
    __tablename__ = "scene_analysis_attempts"
    __table_args__ = (
        UniqueConstraint(
            "work_item_id", "attempt_number", name="uq_scene_attempts_work_item_number"
        ),
        CheckConstraint("attempt_number >= 1", name="ck_scene_attempts_number_positive"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_scene_attempts_time_order",
        ),
        Index("ix_scene_attempts_work_item_id", "work_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    work_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("scene_analysis_work_items.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SceneAnalysisAttemptStatus] = mapped_column(
        _enum_type(SceneAnalysisAttemptStatus, "scene_analysis_attempt_status", 32),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    work_item: Mapped[SceneAnalysisWorkItem] = relationship(back_populates="attempts")


class SceneCandidate(TimestampMixin, Base):
    __tablename__ = "scene_candidates"
    __table_args__ = (
        CheckConstraint("start_seconds >= 0", name="ck_scene_candidates_start_nonnegative"),
        CheckConstraint("end_seconds > start_seconds", name="ck_scene_candidates_time_order"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_scene_candidates_confidence_range",
        ),
        Index("ix_scene_candidates_source_video_id", "source_video_id"),
        Index(
            "ix_scene_candidates_source_discovery",
            "source_video_id",
            "discovery_method",
        ),
        Index(
            "ix_scene_candidates_source_interval",
            "source_video_id",
            "start_seconds",
            "end_seconds",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_video_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_videos.id"), nullable=False
    )
    analysis_work_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scene_analysis_work_items.id"), nullable=True
    )
    start_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    end_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    discovery_method: Mapped[SceneDiscoveryMethod] = mapped_column(
        _enum_type(SceneDiscoveryMethod, "scene_discovery_method", 32), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 5))
    input_fingerprint: Mapped[str] = mapped_column(String(512), nullable=False)
    result_fingerprint: Mapped[str | None] = mapped_column(String(512))

    source_video: Mapped[SourceVideo] = relationship(back_populates="scene_candidates")
    analysis_work_item: Mapped[SceneAnalysisWorkItem | None] = relationship(
        back_populates="scene_candidates"
    )
    evidences: Mapped[list[SceneEvidence]] = relationship(
        back_populates="scene_candidate", passive_deletes=True
    )
    outgoing_relations: Mapped[list[SceneRelation]] = relationship(
        foreign_keys="SceneRelation.source_scene_candidate_id",
        back_populates="source_scene_candidate",
        passive_deletes=True,
    )
    incoming_relations: Mapped[list[SceneRelation]] = relationship(
        foreign_keys="SceneRelation.target_scene_candidate_id",
        back_populates="target_scene_candidate",
        passive_deletes=True,
    )
    event_group_memberships: Mapped[list[EventGroupMember]] = relationship(
        back_populates="scene_candidate", passive_deletes=True
    )


class SceneEvidence(Base):
    __tablename__ = "scene_evidences"
    __table_args__ = (
        CheckConstraint(
            "(start_seconds IS NULL AND end_seconds IS NULL) OR "
            "(start_seconds IS NOT NULL AND end_seconds IS NOT NULL)",
            name="ck_scene_evidences_interval_pair",
        ),
        CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0",
            name="ck_scene_evidences_start_nonnegative",
        ),
        CheckConstraint(
            "start_seconds IS NULL OR end_seconds > start_seconds",
            name="ck_scene_evidences_time_order",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_scene_evidences_confidence_range",
        ),
        CheckConstraint(
            "length(trim(evidence_type)) > 0",
            name="ck_scene_evidences_type_nonempty",
        ),
        Index("ix_scene_evidences_candidate_id", "scene_candidate_id"),
        Index("ix_scene_evidences_modality_type", "modality", "evidence_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scene_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("scene_candidates.id"), nullable=False
    )
    modality: Mapped[SceneEvidenceModality] = mapped_column(
        _enum_type(SceneEvidenceModality, "scene_evidence_modality", 32),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    start_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 5))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    payload_schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1"
    )
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(1024))
    input_fingerprint: Mapped[str | None] = mapped_column(String(512))
    config_fingerprint: Mapped[str | None] = mapped_column(String(512))
    result_fingerprint: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scene_candidate: Mapped[SceneCandidate] = relationship(back_populates="evidences")


class SceneRelation(Base):
    __tablename__ = "scene_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_scene_candidate_id",
            "target_scene_candidate_id",
            "relation_type",
            name="uq_scene_relations_source_target_type",
        ),
        CheckConstraint(
            "source_scene_candidate_id <> target_scene_candidate_id",
            name="ck_scene_relations_not_self",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_scene_relations_confidence_range",
        ),
        Index("ix_scene_relations_source_id", "source_scene_candidate_id"),
        Index("ix_scene_relations_target_id", "target_scene_candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_scene_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("scene_candidates.id"), nullable=False
    )
    target_scene_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("scene_candidates.id"), nullable=False
    )
    relation_type: Mapped[SceneRelationType] = mapped_column(
        _enum_type(SceneRelationType, "scene_relation_type", 32), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 5))
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_scene_candidate: Mapped[SceneCandidate] = relationship(
        foreign_keys=[source_scene_candidate_id], back_populates="outgoing_relations"
    )
    target_scene_candidate: Mapped[SceneCandidate] = relationship(
        foreign_keys=[target_scene_candidate_id], back_populates="incoming_relations"
    )


class EventGroup(TimestampMixin, Base):
    __tablename__ = "event_groups"
    __table_args__ = (Index("ix_event_groups_project_id", "project_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    producer: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    input_fingerprint: Mapped[str | None] = mapped_column(String(512))
    result_fingerprint: Mapped[str | None] = mapped_column(String(512))

    project: Mapped[Project] = relationship(back_populates="event_groups")
    members: Mapped[list[EventGroupMember]] = relationship(
        back_populates="event_group", passive_deletes=True
    )


class EventGroupMember(Base):
    __tablename__ = "event_group_members"
    __table_args__ = (
        UniqueConstraint(
            "event_group_id",
            "scene_candidate_id",
            name="uq_event_group_members_group_candidate",
        ),
        Index("ix_event_group_members_candidate_id", "scene_candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_groups.id"), nullable=False
    )
    scene_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("scene_candidates.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event_group: Mapped[EventGroup] = relationship(back_populates="members")
    scene_candidate: Mapped[SceneCandidate] = relationship(
        back_populates="event_group_memberships"
    )
