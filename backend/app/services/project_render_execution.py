"""Process-local Project render tracking; output files are not execution records."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from uuid import UUID

from backend.app.services.project_rendering import ProjectRenderError, ProjectRenderResult


class RenderRunStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RenderRunSnapshot:
    status: RenderRunStatus
    result: ProjectRenderResult | None = None
    safe_error_code: str | None = None


class ProjectRenderRunRegistry:
    """Guard one active render per Project in this process only."""

    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        self._lock = Lock()
        self._active: set[UUID] = set()
        self._snapshots: dict[UUID, RenderRunSnapshot] = {}
        self._completed: dict[tuple[UUID, UUID], ProjectRenderResult] = {}

    def start(self, project_id: UUID, operation: Callable[[], ProjectRenderResult]) -> bool:
        with self._lock:
            if project_id in self._active:
                return False
            previous = self._snapshots.get(project_id)
            self._active.add(project_id)
            self._snapshots[project_id] = RenderRunSnapshot(RenderRunStatus.QUEUED)

        def run() -> None:
            with self._lock:
                self._snapshots[project_id] = RenderRunSnapshot(RenderRunStatus.RUNNING)
            try:
                result = operation()
                if result.project_id != project_id:
                    raise ProjectRenderError("RENDER_PROJECT_MISMATCH", "Render result Project did not match.")
                with self._lock:
                    self._completed[(project_id, result.render_id)] = result
                    self._snapshots[project_id] = RenderRunSnapshot(RenderRunStatus.COMPLETED, result)
            except ProjectRenderError as error:
                with self._lock:
                    self._snapshots[project_id] = RenderRunSnapshot(RenderRunStatus.FAILED, safe_error_code=error.code)
            except Exception:
                with self._lock:
                    self._snapshots[project_id] = RenderRunSnapshot(RenderRunStatus.FAILED, safe_error_code="PROJECT_RENDER_FAILED")
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

    def is_active(self, project_id: UUID) -> bool:
        with self._lock:
            return project_id in self._active

    def snapshot(self, project_id: UUID) -> RenderRunSnapshot:
        with self._lock:
            return self._snapshots.get(project_id, RenderRunSnapshot(RenderRunStatus.NOT_STARTED))

    def completed_result(self, project_id: UUID, render_id: UUID) -> ProjectRenderResult | None:
        with self._lock:
            return self._completed.get((project_id, render_id))
