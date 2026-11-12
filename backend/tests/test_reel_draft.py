"""TODO 10: short-form reel draft (modes, pace, hook first, length fit, AI fallback, save and read back)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import EpisodeSplitPolicy, Project, SourceVideo
from backend.app.services import project_reel
from backend.app.services.llm_edit_interpreter import LLMEditError
from backend.app.services.reel_draft import Shot, SourceInput, analyze_shots, build_draft
from backend.app.services.shot_structure import ShotInterval, ShotStructureResult


def shots(lengths, speech=None, source="00000000-0000-0000-0000-000000000001"):
    out, t = [], 0.0
    for i, length in enumerate(lengths, start=1):
        s, e = round(t, 3), round(t + length, 3)
        line = (speech or {}).get(i)
        out.append(Shot(i, source, "a.mp4", s, e, f"장면{i} 설명", line[2] if line else "",
                        line[0] if line else None, line[1] if line else None))
        t += length
    return out


def engine(answer):
    calls = []

    def complete(system, user, schema):
        calls.append((system, user, schema))
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer, ensure_ascii=False)
    return ("ollama", "gemma3:4b", complete), calls


class BuildDraftTests(TestCase):
    def test_hook_first_then_filmed_order_and_pace_sets_clip_length(self):
        fake, calls = engine({"mode": "challenge", "title": "첫 댄스곡 도전기", "hook_shot": 5,
                              "scenes": [{"shot": n, "caption": f"문구{n}", "label": "무시"} for n in (3, 1, 5, 2, 4)]})
        draft = build_draft(shots([6] * 6), mode_key="auto", pace_key="normal", target_seconds=12, engine=fake)
        self.assertEqual([s.shot_index for s in draft.scenes], [5, 1, 2, 3, 4])
        self.assertTrue(draft.scenes[0].is_hook)
        self.assertEqual(draft.mode, "challenge")
        self.assertEqual(draft.title, "첫 댄스곡 도전기")
        self.assertTrue(all(abs((s.end_seconds - s.start_seconds) - 2.5) < 1e-6 for s in draft.scenes))
        self.assertTrue(all(s.label == "" for s in draft.scenes), "labels only for item modes")
        self.assertEqual(draft.engine, "llm:ollama/gemma3:4b")
        self.assertIn("약 5개 장면", calls[0][1])

    def test_relaxed_pace_gives_longer_clips_than_fast(self):
        answer = {"mode": "daily_vlog", "title": "하루", "hook_shot": 1, "scenes": [{"shot": 1, "caption": "a"}]}
        relaxed = build_draft(shots([6] * 10), mode_key="daily_vlog", pace_key="relaxed", target_seconds=30, engine=engine(answer)[0])
        fast = build_draft(shots([6] * 10), mode_key="daily_vlog", pace_key="fast", target_seconds=30, engine=engine(answer)[0])
        self.assertGreater(relaxed.scenes[1].end_seconds - relaxed.scenes[1].start_seconds,
                           fast.scenes[1].end_seconds - fast.scenes[1].start_seconds)
        self.assertGreater(len(fast.scenes), len(relaxed.scenes))

    def test_spoken_line_is_never_cut(self):
        fake, _ = engine({"mode": "daily_vlog", "title": "t", "hook_shot": 1,
                          "scenes": [{"shot": 1, "caption": "a"}, {"shot": 2, "caption": "b"}]})
        draft = build_draft(shots([3, 7], speech={2: (3.5, 6.8, "오늘 진짜 재밌었다")}), mode_key="daily_vlog",
                            pace_key="fast", target_seconds=8, engine=fake)
        second = draft.scenes[1]
        self.assertLessEqual(second.start_seconds, 3.5)
        self.assertGreaterEqual(second.end_seconds, 6.8)

    def test_long_lyrics_do_not_stretch_a_shot_past_twice_the_pace(self):
        fake, _ = engine({"mode": "challenge", "title": "t", "hook_shot": 1, "scenes": [{"shot": 1, "caption": "a"}]})
        draft = build_draft(shots([8], speech={1: (0.0, 8.0, "노래 가사")}), mode_key="challenge",
                            pace_key="normal", target_seconds=5, engine=fake)
        self.assertAlmostEqual(draft.scenes[0].end_seconds - draft.scenes[0].start_seconds, 5.0)

    def test_item_mode_keeps_labels(self):
        fake, _ = engine({"mode": "try_on", "title": "추천템 3가지", "hook_shot": 3, "scenes": [
            {"shot": 1, "caption": "첫 번째 미니스커트", "label": "브라운 미니스커트"},
            {"shot": 2, "caption": "핏이 탄탄해요", "label": "브라운 미니스커트"},
            {"shot": 3, "caption": "두 번째 원피스", "label": "플라워 원피스"}]})
        draft = build_draft(shots([2.5] * 3), mode_key="try_on", pace_key="normal", target_seconds=8, engine=fake)
        self.assertEqual([s.label for s in draft.scenes], ["플라워 원피스", "브라운 미니스커트", "브라운 미니스커트"])

    def test_too_long_drops_middle_scenes_and_keeps_hook(self):
        fake, _ = engine({"mode": "travel", "title": "여행", "hook_shot": 4,
                          "scenes": [{"shot": n, "caption": "c"} for n in range(1, 21)]})
        draft = build_draft(shots([5] * 20), mode_key="travel", pace_key="normal", target_seconds=15, engine=fake)
        self.assertLessEqual(draft.total_seconds, 15 * 1.1)
        self.assertEqual(draft.scenes[0].shot_index, 4)
        self.assertEqual(draft.scenes[1].shot_index, 1)
        self.assertEqual(draft.scenes[-1].shot_index, 20)

    def test_short_footage_says_so(self):
        fake, _ = engine({"mode": "travel", "title": "여행", "hook_shot": 1, "scenes": [{"shot": 1, "caption": "c"}]})
        draft = build_draft(shots([2, 2]), mode_key="travel", pace_key="normal", target_seconds=30, engine=fake)
        self.assertEqual(len(draft.scenes), 2)
        self.assertTrue(any("짧게" in note for note in draft.notes))

    def test_ai_failures_fall_back_to_rule_draft(self):
        for answer, code in ((LLMEditError("LLM_TIMEOUT"), "LLM_TIMEOUT"), ({"oops": 1}, "LLM_SCHEMA_INVALID"),
                             ({"mode": "travel", "title": "t", "hook_shot": 99, "scenes": [{"shot": 99, "caption": "x"}]},
                              "LLM_SCENES_INVALID")):
            draft = build_draft(shots([3] * 4), mode_key="auto", pace_key="normal", target_seconds=10, engine=engine(answer)[0])
            self.assertEqual(draft.engine, "rule")
            self.assertEqual(draft.fallback_reason, code)
            self.assertEqual(draft.scenes[0].shot_index, 1)
            self.assertEqual(draft.mode, "daily_vlog")
        none = build_draft(shots([3] * 4), mode_key="recipe", pace_key="normal", target_seconds=10, engine=None)
        self.assertEqual((none.mode, none.fallback_reason), ("recipe", "LLM_NOT_CONFIGURED"))


class AnalyzeShotsTests(TestCase):
    def test_long_shots_are_split_and_fake_speech_over_music_is_dropped(self):
        source_id = uuid4()

        def detect(path, *, source_video_id, duration_seconds, config):
            return ShotStructureResult(source_video_id, duration_seconds, (), (
                ShotInterval(source_video_id, 0.0, 3.0, None, 3.0), ShotInterval(source_video_id, 3.0, 20.0, 3.0, None)))
        segments = ({"start_seconds": 0.5, "end_seconds": 2.0, "text": "구독과 좋아요 부탁드려요!"},
                    {"start_seconds": 4.0, "end_seconds": 5.0, "text": "할 수 있어"})
        result = analyze_shots([SourceInput(source_id, "dance.mp4", Path("dance.mp4"), 20.0, segments)],
                               detect=detect, describe=lambda path, start, end: f"{start:.0f}초 장면")
        self.assertEqual([(s.start_seconds, s.end_seconds) for s in result],
                         [(0.0, 3.0), (3.0, 8.667), (8.667, 14.333), (14.333, 20.0)])
        self.assertEqual(result[0].speech, "")
        self.assertEqual((result[1].speech, result[1].speech_start, result[1].speech_end), ("할 수 있어", 4.0, 5.0))
        self.assertEqual(result[2].caption, "9초 장면")


class ReelDraftApiTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite+pysqlite:///{root / 'reel.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start()
        self.addCleanup(loader.stop)
        context = TestClient(app)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        video = root / "originals" / "clip.mp4"
        video.parent.mkdir()
        video.write_bytes(b"fake video")
        self.resolve = patch.object(app.state.source_storage, "resolve", lambda reference: video)
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        with self.factory() as session:
            project = Project(name="reels", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project)
            session.flush()
            session.add(SourceVideo(project_id=project.id, original_filename="dance.mp4",
                                    storage_reference=f"projects/{project.id.hex}/sources/x.mp4", duration_seconds=20))
            session.commit()
            self.project_id = project.id
        self.analyze_calls = 0

    def fake_analyze(self, sources, on_progress=None):
        self.analyze_calls += 1
        return shots([4] * 5)

    def wait(self):
        for _ in range(200):
            body = self.client.get(f"/projects/{self.project_id}/reel-draft").json()
            if body["status"] != "RUNNING":
                return body
            time.sleep(0.02)
        self.fail("reel draft did not finish")

    def test_options_come_from_one_settings_file(self):
        body = self.client.get("/projects/reel-options").json()
        self.assertEqual([f["key"] for f in body["formats"]], ["short", "long"])
        self.assertEqual(len(body["modes"]), 9)
        self.assertEqual(body["modes"][0]["key"], "auto")
        self.assertEqual([p["key"] for p in body["paces"]], ["relaxed", "normal", "fast"])

    def test_make_save_and_reuse_shots_when_only_the_mode_changes(self):
        self.assertIsNone(self.client.get(f"/projects/{self.project_id}/reel-draft").json()["draft"])
        with patch.object(project_reel, "analyze_shots", self.fake_analyze), \
                patch("backend.app.services.reel_draft.configured_engine", return_value=None):
            started = self.client.post(f"/projects/{self.project_id}/reel-draft",
                                       json={"format": "short", "mode": "recipe", "pace": "fast", "target_seconds": 15})
            self.assertEqual(started.status_code, 202)
            first = self.wait()
            self.assertEqual(first["status"], "COMPLETED")
            self.assertEqual(first["draft"]["mode"], "recipe")
            self.assertEqual(first["draft"]["pace"], "fast")
            self.assertEqual(first["draft"]["shot_count"], 5)
            self.client.post(f"/projects/{self.project_id}/reel-draft", json={"mode": "travel", "pace": "relaxed", "target_seconds": 15})
            second = self.wait()
        self.assertEqual(second["draft"]["mode"], "travel")
        self.assertEqual(self.analyze_calls, 1, "same videos: shots are reused, only the draft is rebuilt")

    def test_long_form_and_bad_options_are_refused(self):
        long = self.client.post(f"/projects/{self.project_id}/reel-draft", json={"format": "long"})
        self.assertEqual((long.status_code, long.json()["detail"]["code"]), (409, "LONG_FORM_USES_STORY_DIRECTION"))
        bad = self.client.post(f"/projects/{self.project_id}/reel-draft", json={"mode": "dance_battle"})
        self.assertEqual((bad.status_code, bad.json()["detail"]["code"]), (422, "REEL_OPTION_INVALID"))
        missing = self.client.get(f"/projects/{uuid4()}/reel-draft")
        self.assertEqual(missing.status_code, 404)
