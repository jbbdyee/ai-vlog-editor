import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from backend.app.services.project_analyze_all import AnalyzeAllRegistry, AnalyzeAllSteps


class FakeSteps:
    """Each step finishes a few polls after it is started, like the real background runs."""

    def __init__(self, *, transcribed=False, scened=False, captioned=False, transcribed_after=2, vision_fails=False):
        self.calls: list[str] = []
        self.transcribed, self.scened, self.captioned = transcribed, scened, captioned
        self.transcribed_after = transcribed_after
        self.vision_fails = vision_fails
        self._busy = {"transcript": 0, "scenes": 0, "vision": 0}

    def _tick(self, name: str) -> bool:
        if self._busy[name] > 0:
            self._busy[name] -= 1
            return True
        return False

    def build(self) -> AnalyzeAllSteps:
        def start(name, done_attr):
            def run():
                self.calls.append(name)
                self._busy[name] = 2
                setattr(self, done_attr, True)
            return run

        return AnalyzeAllSteps(
            transcript_needed=lambda: not self.transcribed,
            start_transcript=start("transcript", "transcribed"),
            transcript_busy=lambda: self._tick("transcript"),
            transcribed_count=lambda: self.transcribed_after if self.transcribed else 0,
            scenes_needed=lambda: not self.scened,
            start_scenes=start("scenes", "scened"),
            scene_status=lambda: "RUNNING" if self._tick("scenes") else ("COMPLETED" if self.scened else "NOT_STARTED"),
            vision_needed=lambda: not self.captioned,
            start_vision=start("vision", "captioned"),
            vision_status=lambda: "RUNNING" if self._tick("vision") else (
                ("FAILED" if self.vision_fails else "COMPLETED") if self.captioned else "NOT_STARTED"),
        )


def _wait_finished(registry, project_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while registry.state(project_id).running:
        assert time.monotonic() < deadline, "analyze-all did not finish"
        time.sleep(0.005)
    return registry.state(project_id)


def _registry():
    return AnalyzeAllRegistry(ThreadPoolExecutor(max_workers=2), poll_seconds=0.001)


class AnalyzeAllRegistryTest(unittest.TestCase):
    def test_runs_all_three_steps_in_order_without_a_browser(self):
        registry, project_id, steps = _registry(), uuid4(), FakeSteps()
        assert registry.state(project_id).phase == "idle"
        assert registry.start(project_id, steps.build())
        state = _wait_finished(registry, project_id)
        assert state.phase == "done" and state.error is None and state.finished_at is not None
        assert steps.calls == ["transcript", "scenes", "vision"]


    def test_skips_steps_that_are_already_finished(self):
        registry, project_id = _registry(), uuid4()
        steps = FakeSteps(transcribed=True, scened=True, captioned=True)
        assert registry.start(project_id, steps.build())
        assert _wait_finished(registry, project_id).phase == "done"
        assert steps.calls == []


    def test_stops_with_a_clear_message_when_no_video_has_a_transcript(self):
        registry, project_id = _registry(), uuid4()
        steps = FakeSteps(transcribed_after=0)
        assert registry.start(project_id, steps.build())
        state = _wait_finished(registry, project_id)
        assert state.phase == "failed"
        assert state.error == "대사 단계를 마친 영상이 없어 장면 분석으로 넘어갈 수 없습니다."
        assert steps.calls == ["transcript"]


    def test_reports_a_failed_vision_step(self):
        registry, project_id = _registry(), uuid4()
        assert registry.start(project_id, FakeSteps(vision_fails=True).build())
        state = _wait_finished(registry, project_id)
        assert state.phase == "failed" and "Ollama" in state.error


    def test_refuses_a_second_start_while_running_and_allows_one_after(self):
        registry, project_id = AnalyzeAllRegistry(ThreadPoolExecutor(max_workers=2), poll_seconds=0.05), uuid4()
        assert registry.start(project_id, FakeSteps().build())
        assert not registry.start(project_id, FakeSteps().build())
        _wait_finished(registry, project_id)
        assert registry.start(project_id, FakeSteps(transcribed=True, scened=True, captioned=True).build())
        assert _wait_finished(registry, project_id).phase == "done"


    def test_close_lets_a_waiting_run_end(self):
        registry, project_id = AnalyzeAllRegistry(ThreadPoolExecutor(max_workers=2), poll_seconds=10), uuid4()
        steps = FakeSteps()
        steps_built = steps.build()
        assert registry.start(project_id, steps_built)
        time.sleep(0.05)
        registry.close()
        state = _wait_finished(registry, project_id)
        assert state.phase == "failed" and "서버가 꺼져서" in state.error
