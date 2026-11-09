"""Server-side "전체 분석": runs transcript → scenes → vision one after another.

The browser used to hand each step to the next, so a closed or background tab stalled the run.
This keeps that hand-off on the server. State lives in this process only (lost on restart);
starting again simply skips the steps that are already finished.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Event, Lock
from uuid import UUID

ACTIVE_STATUSES = frozenset({"QUEUED", "RUNNING"})
RUNNING_PHASES = frozenset({"transcript", "scenes", "vision"})


@dataclass(frozen=True)
class AnalyzeAllState:
    phase: str = "idle"  # idle | transcript | scenes | vision | done | failed
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self.phase in RUNNING_PHASES


@dataclass(frozen=True)
class AnalyzeAllSteps:
    """How to check, start and watch each existing step; the router wires these to the real services."""

    transcript_needed: Callable[[], bool]
    start_transcript: Callable[[], object]
    transcript_busy: Callable[[], bool]
    transcribed_count: Callable[[], int]
    scenes_needed: Callable[[], bool]
    start_scenes: Callable[[], object]
    scene_status: Callable[[], str]
    vision_needed: Callable[[], bool]
    start_vision: Callable[[], object]
    vision_status: Callable[[], str]


class StepFailed(Exception):
    pass


class _Stopped(Exception):
    pass


class AnalyzeAllRegistry:
    def __init__(self, executor: Executor, poll_seconds: float = 2.0) -> None:
        self._executor = executor
        self._poll_seconds = poll_seconds
        self._lock = Lock()
        self._states: dict[UUID, AnalyzeAllState] = {}
        self._stop = Event()

    def state(self, project_id: UUID) -> AnalyzeAllState:
        with self._lock:
            return self._states.get(project_id, AnalyzeAllState())

    def start(self, project_id: UUID, steps: AnalyzeAllSteps) -> bool:
        with self._lock:
            previous = self._states.get(project_id)
            if previous is not None and previous.running:
                return False
            self._states[project_id] = AnalyzeAllState(phase="transcript", started_at=_now())
        try:
            self._executor.submit(self._run, project_id, steps)
        except Exception:
            with self._lock:
                if previous is None:
                    self._states.pop(project_id, None)
                else:
                    self._states[project_id] = previous
            raise
        return True

    def close(self) -> None:
        """Lets waiting runs exit so the server can shut down."""
        self._stop.set()

    def _set(self, project_id: UUID, **changes) -> None:
        with self._lock:
            self._states[project_id] = replace(self._states[project_id], **changes)

    def _wait_while(self, busy: Callable[[], bool]) -> None:
        while busy():
            if self._stop.wait(self._poll_seconds):
                raise _Stopped

    def _run(self, project_id: UUID, steps: AnalyzeAllSteps) -> None:
        try:
            # ① 대사
            if steps.transcript_needed():
                steps.start_transcript()
                self._wait_while(steps.transcript_busy)
            if steps.transcribed_count() == 0:
                raise StepFailed("대사 단계를 마친 영상이 없어 장면 분석으로 넘어갈 수 없습니다.")

            # ② 장면
            self._set(project_id, phase="scenes")
            if steps.scene_status() in ACTIVE_STATUSES or steps.scenes_needed():
                if steps.scene_status() not in ACTIVE_STATUSES:
                    steps.start_scenes()
                self._wait_while(lambda: steps.scene_status() in ACTIVE_STATUSES)
                if steps.scene_status() == "FAILED":
                    raise StepFailed("장면 분석이 실패했습니다.")

            # ③ 화면 설명
            self._set(project_id, phase="vision")
            if steps.vision_status() in ACTIVE_STATUSES or steps.vision_needed():
                if steps.vision_status() not in ACTIVE_STATUSES:
                    steps.start_vision()
                self._wait_while(lambda: steps.vision_status() in ACTIVE_STATUSES)
                if steps.vision_status() == "FAILED":
                    raise StepFailed("화면 설명이 실패했습니다. 내 컴퓨터의 Ollama가 켜져 있는지 확인해 주세요.")

            self._set(project_id, phase="done", finished_at=_now())
        except StepFailed as error:
            self._set(project_id, phase="failed", error=str(error), finished_at=_now())
        except _Stopped:
            self._set(project_id, phase="failed", error="서버가 꺼져서 전체 분석이 멈췄습니다. 다시 누르면 남은 단계부터 이어서 합니다.", finished_at=_now())
        except Exception:
            self._set(project_id, phase="failed", error="전체 분석 중 예상하지 못한 오류가 났습니다. 다시 눌러 주세요.", finished_at=_now())


def _now() -> datetime:
    return datetime.now(timezone.utc)
