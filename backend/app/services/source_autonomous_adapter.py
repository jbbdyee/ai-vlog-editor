"""Run the existing deterministic discovery for one v1-completed source.

This is deliberately not wired into Project processing or an HTTP route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.audio_extractor import ExtractedAudio, extract_audio
from backend.app.services.autonomous_discovery import (
    AUDIO_WORK,
    PROMOTION_WORK,
    TRANSCRIPT_WORK,
    VISUAL_WORK,
    AutonomousDiscoveryResult,
    ModalityAnalysis,
    analyze_audio_wav,
    analyze_visual_video,
    process_autonomous_discovery,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import SourceStorage


class SourceAutonomousStatus(str, Enum):
    COMPLETED = "COMPLETED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class SourceAutonomousResult:
    source_video_id: UUID
    status: SourceAutonomousStatus
    discovery: AutonomousDiscoveryResult | None = None
    safe_error_code: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceAutonomousServices:
    extract: Callable[[Path, Path], ExtractedAudio] = extract_audio
    analyze_audio: Callable[..., ModalityAnalysis] = analyze_audio_wav
    analyze_visual: Callable[..., ModalityAnalysis] = analyze_visual_video
    discover: Callable[..., AutonomousDiscoveryResult] = process_autonomous_discovery


_SCENE_WORK_TYPES = frozenset(
    {TRANSCRIPT_WORK, AUDIO_WORK, VISUAL_WORK, PROMOTION_WORK}
)
_V1_STAGES = frozenset(ProcessingStageKind)


def process_source_autonomous(
    *,
    session: Session,
    storage: SourceStorage,
    scene_workspace: LocalProcessingWorkspace,
    source_video_id: UUID,
    services: SourceAutonomousServices | None = None,
) -> SourceAutonomousResult:
    """Use a distinct temporary workspace; never alter the v1 processing state.

    A failed or running Scene work item requires explicit recovery. This adapter
    intentionally refuses to turn a second invocation into an implicit retry.
    """
    source = session.get(SourceVideo, source_video_id)
    if source is None:
        return _result(source_video_id, SourceAutonomousStatus.FAILED, "SOURCE_NOT_FOUND")
    stages = session.scalars(
        select(ProcessingStage).where(ProcessingStage.source_video_id == source_video_id)
    ).all()
    if (
        source.processing_status is not SourceVideoStatus.COMPLETED
        or source.duration_seconds is None
        or float(source.duration_seconds) <= 0
        or source.transcript is None
        or {stage.stage for stage in stages if stage.status is ProcessingStageStatus.COMPLETED}
        != _V1_STAGES
    ):
        return _result(source_video_id, SourceAutonomousStatus.BLOCKED, "V1_ANALYSIS_INCOMPLETE")

    scene_works = session.scalars(
        select(SceneAnalysisWorkItem)
        .where(
            SceneAnalysisWorkItem.source_video_id == source_video_id,
            SceneAnalysisWorkItem.work_type.in_(_SCENE_WORK_TYPES),
        )
    ).all()
    if any(work.status is SceneAnalysisWorkStatus.RUNNING for work in scene_works):
        return _result(source_video_id, SourceAutonomousStatus.BLOCKED, "SCENE_WORK_RUNNING")
    if any(work.status is SceneAnalysisWorkStatus.FAILED for work in scene_works):
        return _result(source_video_id, SourceAutonomousStatus.BLOCKED, "SCENE_RETRY_REQUIRED")

    active = services or SourceAutonomousServices()
    if not all(
        callable(analyzer)
        for analyzer in (
            active.extract,
            active.analyze_audio,
            active.analyze_visual,
            active.discover,
        )
    ):
        return _result(source_video_id, SourceAutonomousStatus.BLOCKED, "SCENE_ANALYZER_UNAVAILABLE")
    warnings: list[str] = []
    try:
        source_path = storage.resolve(source.storage_reference)
    except Exception:
        return _result(source_video_id, SourceAutonomousStatus.FAILED, "SOURCE_UNAVAILABLE")

    def audio_analyzer() -> ModalityAnalysis:
        audio = active.extract(
            source_path,
            scene_workspace.audio_directory(
                project_id=source.project_id, source_video_id=source.id
            ),
        )
        return active.analyze_audio(
            audio.audio_path,
            source_video_id=source.id,
            duration_seconds=float(source.duration_seconds),
        )

    def visual_analyzer() -> ModalityAnalysis:
        return active.analyze_visual(
            source_path,
            source_video_id=source.id,
            duration_seconds=float(source.duration_seconds),
        )

    discovery: AutonomousDiscoveryResult | None = None
    error_code: str | None = None
    try:
        discovery = active.discover(
            session,
            source.id,
            audio_analyzer=audio_analyzer,
            visual_analyzer=visual_analyzer,
        )
    except Exception:
        # Do not expose raw media paths, subprocess output, or provider details.
        error_code = "SCENE_DISCOVERY_FAILED"
    finally:
        try:
            scene_workspace.cleanup_source(
                project_id=source.project_id, source_video_id=source.id
            )
        except Exception:
            warnings.append("SCENE_TEMPORARY_CLEANUP_FAILED")

    if error_code is not None:
        return _result(source_video_id, SourceAutonomousStatus.FAILED, error_code, tuple(warnings))
    assert discovery is not None
    return SourceAutonomousResult(
        source_video_id=source_video_id,
        status=(SourceAutonomousStatus.ABSTAINED if discovery.abstained else SourceAutonomousStatus.COMPLETED),
        discovery=discovery,
        warnings=tuple(discovery.warnings) + tuple(warnings),
    )


def _result(
    source_video_id: UUID,
    status: SourceAutonomousStatus,
    code: str,
    warnings: tuple[str, ...] = (),
) -> SourceAutonomousResult:
    return SourceAutonomousResult(source_video_id, status, safe_error_code=code, warnings=warnings)
