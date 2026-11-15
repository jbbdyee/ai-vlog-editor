import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest import mock
from uuid import uuid4

import numpy as np

from backend.app.services import speaker_voice as sv
from backend.app.services.project_analyze_all import AnalyzeAllRegistry
from backend.tests.test_project_analyze_all import FakeSteps, _wait_finished

RATE = sv.SAMPLE_RATE


def _audio(seconds: float, kind: float) -> np.ndarray:
    """Fake audio whose constant value says whose voice it is (1 = me, -1 = someone else)."""
    return np.full(int(seconds * RATE), kind, np.float32)


def fake_embedder(samples: np.ndarray):
    if len(samples) < RATE:  # under 1 s → too short to tell
        return None
    me = float(np.mean(samples)) > 0
    return np.array([1.0, 0.0], np.float32) if me else np.array([0.0, 1.0], np.float32)


# a 20 s "video": I talk 0-10 s, someone else 10-20 s
TIMELINE = np.concatenate([_audio(10, 1.0), _audio(10, -1.0)])


def fake_load_audio(media_path, start=None, duration=None):
    if start is None:
        return TIMELINE
    return TIMELINE[int(start * RATE):int((start + duration) * RATE)]


SEGMENTS = (
    {"start_seconds": 1.0, "end_seconds": 4.0, "text": "오늘 학원 끝났어"},
    {"start_seconds": 12.0, "end_seconds": 15.0, "text": "다음 동작 갈게요"},
    {"start_seconds": 19.9, "end_seconds": 20.0, "text": "응"},
)


class SpeakerVoiceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.project_id, self.source_id = uuid4(), uuid4()
        patcher = mock.patch.object(sv, "load_audio", side_effect=fake_load_audio)
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, start=1.0, end=4.0):
        return sv.add_my_voice_sample(self.root, self.project_id, source_video_id=self.source_id, media_path=Path("x.mp4"),
                                      start=start, end=end, text="오늘 학원 끝났어", embedder=fake_embedder)

    def test_features_have_80_bands_and_short_audio_has_none(self):
        assert sv.fbank(np.random.default_rng(0).normal(size=RATE).astype(np.float32) * 1000).shape == (98, 80)
        assert sv.fbank(np.zeros(100, np.float32)) is None

    def test_short_lines_are_widened_around_their_middle(self):
        assert sv.listen_range(2.0, 5.0) == (2.0, 5.0)
        a, b = sv.listen_range(3.0, 3.2)
        assert abs((b - a) - sv.MIN_LINE_SECONDS) < 1e-9 and abs((a + b) / 2 - 3.1) < 1e-9
        assert sv.listen_range(0.0, 0.2)[0] == 0.0

    def test_no_voice_registered_means_no_version(self):
        voice = sv.load_my_voice(self.root, self.project_id)
        assert voice.centroid is None and voice.version is None and voice.samples == ()

    def test_registering_a_line_saves_a_file_and_marking_the_same_line_again_does_not_duplicate(self):
        voice = self.register()
        assert len(voice.samples) == 1 and voice.version
        assert (self.root / str(self.project_id) / "my_voice.json").is_file()
        assert len(self.register().samples) == 1
        assert len(self.register(start=5.0, end=8.0).samples) == 2

    def test_too_short_line_cannot_be_registered(self):
        with mock.patch.object(sv, "listen_range", return_value=(1.0, 1.2)):
            with self.assertRaises(sv.SpeakerVoiceError):
                self.register(start=1.0, end=1.2)

    def test_lines_are_scored_me_other_and_unknown(self):
        voice = self.register()
        scores = sv.score_source(self.root, self.project_id, source_video_id=self.source_id, media_path=Path("x.mp4"),
                                 segments=SEGMENTS, my_voice=voice, embedder=fake_embedder)
        assert [sv.speaker_label(score) for score in scores] == ["me", "other", "unknown"]
        assert sv.source_is_current(self.root, self.project_id, self.source_id, 3, voice.version)

    def test_registering_another_line_makes_old_scores_out_of_date(self):
        voice = self.register()
        sv.score_source(self.root, self.project_id, source_video_id=self.source_id, media_path=Path("x.mp4"),
                        segments=SEGMENTS, my_voice=voice, embedder=fake_embedder)
        newer = self.register(start=5.0, end=8.0)
        assert newer.version != voice.version
        assert not sv.source_is_current(self.root, self.project_id, self.source_id, 3, newer.version)

    def test_clearing_my_voice_forgets_it(self):
        self.register()
        sv.clear_my_voice(self.root, self.project_id)
        assert sv.load_my_voice(self.root, self.project_id).centroid is None

    def test_background_run_scores_only_out_of_date_videos(self):
        self.register()
        registry = sv.VoiceRunRegistry(ThreadPoolExecutor(max_workers=1), self.root, embedder=fake_embedder)
        sources = [sv.VoiceSource(self.source_id, Path("x.mp4"), SEGMENTS)]
        assert registry.start(self.project_id, lambda: sources)
        deadline = time.monotonic() + 5
        while registry.state(self.project_id).status == "RUNNING":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        state = registry.state(self.project_id)
        assert (state.status, state.done, state.total) == ("COMPLETED", 1, 1)
        assert registry.pending(self.project_id, sources) == []

    def test_background_run_without_my_voice_fails_with_a_hint(self):
        registry = sv.VoiceRunRegistry(ThreadPoolExecutor(max_workers=1), self.root, embedder=fake_embedder)
        assert registry.start(self.project_id, lambda: [])
        deadline = time.monotonic() + 5
        while registry.state(self.project_id).status == "RUNNING":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        state = registry.state(self.project_id)
        assert state.status == "FAILED" and "내 목소리" in state.error

    def test_model_file_missing_is_reported_not_crashing_the_server(self):
        embedder = sv.OnnxVoiceEmbedder(self.root / "missing.onnx")
        assert not embedder.available()
        with self.assertRaises(sv.SpeakerVoiceError):
            embedder(np.random.default_rng(1).normal(size=RATE * 2).astype(np.float32) * 1000)


class AnalyzeAllVoicePhaseTest(unittest.TestCase):
    def _registry(self):
        return AnalyzeAllRegistry(ThreadPoolExecutor(max_workers=2), poll_seconds=0.001)

    def test_voice_step_is_skipped_until_my_voice_is_registered(self):
        registry, project_id = self._registry(), uuid4()
        assert registry.start(project_id, FakeSteps(transcribed=True, scened=True, captioned=True).build())
        state = _wait_finished(registry, project_id)
        assert state.phase == "done" and state.voice_skipped

    def test_voice_step_runs_after_vision_when_registered(self):
        registry, project_id, calls = self._registry(), uuid4(), []
        status = {"value": "IDLE", "polls": 0}

        def voice_status():
            if status["value"] == "RUNNING":
                status["polls"] += 1
                if status["polls"] > 2:
                    status["value"] = "COMPLETED"
            return status["value"]

        def start_voice():
            calls.append("voice")
            status["value"] = "RUNNING"

        steps = replace(FakeSteps(transcribed=True, scened=True, captioned=True).build(),
                        voice_registered=lambda: True, voice_needed=lambda: status["value"] != "COMPLETED",
                        start_voice=start_voice, voice_status=voice_status)
        assert registry.start(project_id, steps)
        state = _wait_finished(registry, project_id)
        assert state.phase == "done" and not state.voice_skipped and calls == ["voice"]

    def test_failed_voice_step_stops_with_a_message(self):
        registry, project_id = self._registry(), uuid4()
        steps = replace(FakeSteps(transcribed=True, scened=True, captioned=True).build(),
                        voice_registered=lambda: True, voice_needed=lambda: True,
                        start_voice=lambda: None, voice_status=lambda: "FAILED")
        assert registry.start(project_id, steps)
        state = _wait_finished(registry, project_id)
        assert state.phase == "failed" and "목소리" in state.error


if __name__ == "__main__":
    unittest.main()
