"""Process-local Scene run tracking; candidate and Work data remain in the DB."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from uuid import UUID

from backend.app.services.project_scene_processing import (
    ProjectSceneProcessingResult,
    ProjectSceneSourceResult,
    SceneSourceOutcome,
)


class SceneRunStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SceneRunSnapshot:
    run_status: SceneRunStatus
    sources: tuple[ProjectSceneSourceResult, ...] = ()
    safe_error_code: str | None = None


class ProjectSceneRunRegistry:
    """Guard duplicate Project Scene runs on this process only."""

    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        self._lock = Lock()
        self._active: set[UUID] = set()
        self._snapshots: dict[UUID, SceneRunSnapshot] = {}

    def start(
        self,
        project_id: UUID,
        operation: Callable[[Callable[[ProjectSceneSourceResult], None]], ProjectSceneProcessingResult],
    ) -> bool:
        with self._lock:
            if project_id in self._active:
                return False
            previous = self._snapshots.get(project_id)
            self._active.add(project_id)
            self._snapshots[project_id] = SceneRunSnapshot(SceneRunStatus.QUEUED)

        def record(item: ProjectSceneSourceResult) -> None:
            with self._lock:
                current = self._snapshots[project_id]
                self._snapshots[project_id] = SceneRunSnapshot(
                    SceneRunStatus.RUNNING, current.sources + (item,)
                )

        def run() -> None:
            with self._lock:
                self._snapshots[project_id] = SceneRunSnapshot(SceneRunStatus.RUNNING)
            try:
                result = operation(record)
                with self._lock:
                    warning = any(
                        item.outcome in {
                            SceneSourceOutcome.FAILED,
                            SceneSourceOutcome.BLOCKED,
                            SceneSourceOutcome.SKIPPED_V1_INCOMPLETE,
                        }
                        or item.warnings
                        for item in result.sources
                    )
                    self._snapshots[project_id] = SceneRunSnapshot(
                        SceneRunStatus.COMPLETED_WITH_WARNINGS if warning else SceneRunStatus.COMPLETED,
                        result.sources,
                    )
            except Exception:
                with self._lock:
                    current = self._snapshots[project_id]
                    self._snapshots[project_id] = SceneRunSnapshot(
                        SceneRunStatus.FAILED, current.sources,
                        safe_error_code="PROJECT_SCENE_RUN_FAILED",
                    )
            finally:
                with self._lock:
                    self._active.discard(project_id)

        try:
            self._executor.submit(run)
        except Exception:
            with self._lock:
                self._active.discard(project_id)
                if previous is None:
                    self._snapshots.pop(project_id, None)
                else:
                    self._snapshots[project_id] = previous
            raise
        return True

    def snapshot(self, project_id: UUID) -> SceneRunSnapshot:
        with self._lock:
            return self._snapshots.get(
                project_id, SceneRunSnapshot(SceneRunStatus.NOT_STARTED)
            )
