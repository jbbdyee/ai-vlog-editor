from collections.abc import Callable
from concurrent.futures import Executor
from threading import Lock
from uuid import UUID


class ProjectRunRegistry:
    """Guard in-process Project runs without pretending to be a distributed lock."""

    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        self._active: set[UUID] = set()
        self._lock = Lock()

    def start(self, project_id: UUID, operation: Callable[[], None]) -> bool:
        with self._lock:
            if project_id in self._active:
                return False
            self._active.add(project_id)

        def guarded_operation() -> None:
            try:
                operation()
            finally:
                with self._lock:
                    self._active.discard(project_id)

        try:
            self._executor.submit(guarded_operation)
        except Exception:
            with self._lock:
                self._active.discard(project_id)
            raise
        return True

    def is_active(self, project_id: UUID) -> bool:
        with self._lock:
            return project_id in self._active
