from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
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


class ProjectStatus(str, Enum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


class EpisodeSplitPolicy(str, Enum):
    SINGLE = "SINGLE"
    AUTO_SPLIT = "AUTO_SPLIT"
    USER_CONFIRM_SPLIT = "USER_CONFIRM_SPLIT"


class SourceVideoStatus(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingStageKind(str, Enum):
    PROBE = "PROBE"
    AUDIO_EXTRACTION = "AUDIO_EXTRACTION"
    STT = "STT"
    MEMO_DETECTION = "MEMO_DETECTION"


class ProcessingStageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


def _enum_type(enum_class: type[Enum], name: str, length: int) -> SQLAlchemyEnum:
    return SQLAlchemyEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "target_duration_seconds IS NULL OR target_duration_seconds > 0",
            name="ck_projects_target_duration_positive",
        ),
        Index("ix_projects_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        _enum_type(ProjectStatus, "project_status", 32),
        nullable=False,
        default=ProjectStatus.CREATED,
    )
    target_duration_seconds: Mapped[float | None] = mapped_column(
        Numeric(12, 3), nullable=True
    )
    split_policy: Mapped[EpisodeSplitPolicy] = mapped_column(
        _enum_type(EpisodeSplitPolicy, "episode_split_policy", 32), nullable=False
    )
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_videos: Mapped[list[SourceVideo]] = relationship(
        back_populates="project", passive_deletes=True
    )


class SourceVideo(TimestampMixin, Base):
    __tablename__ = "source_videos"
    __table_args__ = (
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_source_videos_duration_nonnegative",
        ),
        CheckConstraint(
            "width IS NULL OR width > 0", name="ck_source_videos_width_positive"
        ),
        CheckConstraint(
            "height IS NULL OR height > 0", name="ck_source_videos_height_positive"
        ),
        CheckConstraint(
            "fps IS NULL OR fps > 0", name="ck_source_videos_fps_positive"
        ),
        CheckConstraint(
            "(fingerprint IS NULL AND fingerprint_algorithm IS NULL) OR "
            "(fingerprint IS NOT NULL AND fingerprint_algorithm IS NOT NULL)",
            name="ck_source_videos_fingerprint_pair",
        ),
        Index("ix_source_videos_project_id", "project_id"),
        Index("ix_source_videos_processing_status", "processing_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fingerprint_algorithm: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3))
    video_codec: Mapped[str | None] = mapped_column(String(64))
    audio_codec: Mapped[str | None] = mapped_column(String(64))
    format_name: Mapped[str | None] = mapped_column(String(128))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Numeric(12, 6))
    processing_status: Mapped[SourceVideoStatus] = mapped_column(
        _enum_type(SourceVideoStatus, "source_video_status", 32),
        nullable=False,
        default=SourceVideoStatus.REGISTERED,
    )

    project: Mapped[Project] = relationship(back_populates="source_videos")
    processing_stages: Mapped[list[ProcessingStage]] = relationship(
        back_populates="source_video", passive_deletes=True
    )
    transcript: Mapped[Transcript | None] = relationship(
        back_populates="source_video", uselist=False, passive_deletes=True
    )
    edit_memos: Mapped[list[EditMemo]] = relationship(
        back_populates="source_video",
        foreign_keys="EditMemo.source_video_id",
        passive_deletes=True,
    )


class ProcessingStage(TimestampMixin, Base):
    __tablename__ = "processing_stages"
    __table_args__ = (
        UniqueConstraint(
            "source_video_id", "stage", name="uq_processing_stages_source_stage"
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_processing_stages_attempt_nonnegative"
        ),
        Index("ix_processing_stages_source_video_id", "source_video_id"),
        Index("ix_processing_stages_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_video_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_videos.id"), nullable=False
    )
    stage: Mapped[ProcessingStageKind] = mapped_column(
        _enum_type(ProcessingStageKind, "processing_stage_kind", 32), nullable=False
    )
    status: Mapped[ProcessingStageStatus] = mapped_column(
        _enum_type(ProcessingStageStatus, "processing_stage_status", 32),
        nullable=False,
        default=ProcessingStageStatus.PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(String(512))
    input_fingerprint: Mapped[str | None] = mapped_column(String(512))
    config_version: Mapped[str | None] = mapped_column(String(128))
    tool_version: Mapped[str | None] = mapped_column(String(128))
    result_version: Mapped[str | None] = mapped_column(String(128))
    result_reference: Mapped[str | None] = mapped_column(String(1024))
    result_fingerprint: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_video: Mapped[SourceVideo] = relationship(
        back_populates="processing_stages"
    )


class Transcript(TimestampMixin, Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("source_video_id", name="uq_transcripts_source_video_id"),
        CheckConstraint(
            "language_probability IS NULL OR "
            "(language_probability >= 0 AND language_probability <= 1)",
            name="ck_transcripts_language_probability_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_video_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_videos.id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    language_probability: Mapped[float | None] = mapped_column(Numeric(6, 5))
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    source_video: Mapped[SourceVideo] = relationship(back_populates="transcript")
    edit_memos: Mapped[list[EditMemo]] = relationship(
        back_populates="transcript", passive_deletes=True
    )


class EditMemo(Base):
    __tablename__ = "edit_memos"
    __table_args__ = (
        CheckConstraint(
            "start_seconds >= 0", name="ck_edit_memos_start_nonnegative"
        ),
        CheckConstraint(
            "end_seconds >= start_seconds", name="ck_edit_memos_time_order"
        ),
        CheckConstraint(
            "trigger_similarity >= 0 AND trigger_similarity <= 1",
            name="ck_edit_memos_trigger_similarity_range",
        ),
        Index("ix_edit_memos_source_video_id", "source_video_id"),
        Index("ix_edit_memos_transcript_id", "transcript_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_video_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_videos.id"), nullable=False
    )
    transcript_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcripts.id"), nullable=False
    )
    start_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    end_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    matched_trigger: Mapped[str] = mapped_column(String(255), nullable=False)
    matched_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    matched_action: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_match_type: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_similarity: Mapped[float] = mapped_column(
        Numeric(6, 5), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_video: Mapped[SourceVideo] = relationship(
        back_populates="edit_memos", foreign_keys=[source_video_id]
    )
    transcript: Mapped[Transcript] = relationship(back_populates="edit_memos")
