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
        # TODO 14: the hook (under the title) shows no name tag of an item that is never numbered
        self.assertEqual([s.label for s in draft.scenes], ["", "브라운 미니스커트", "브라운 미니스커트"])
        self.assertEqual(draft.title, "추천템 1가지", "the title counts the name tags")

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


def looked(rows, length=3.0):
    """rows: (activity, item, speech) per shot."""
    return [Shot(i, "s", "a.mp4", (i - 1) * length, i * length, f"장면{i}", speech, (i - 1) * length if speech else None,
                 i * length if speech else None, item, activity) for i, (activity, item, speech) in enumerate(rows, start=1)]


class CaptionQualityTests(TestCase):
    """TODO 11: auto mode by vote, no copied speech or counting, name tags and "첫 번째" by Python."""

    def test_auto_mode_follows_what_most_shots_are_doing(self):
        rows = [("옷 보여주기", "브라운 미니스커트", "")] * 6 + [("이야기·셀카", "", "")] * 3
        fake, calls = engine({"mode": "daily_vlog", "title": "t", "hook_shot": 1, "scenes": [{"shot": 1, "caption": "a"}]})
        draft = build_draft(looked(rows), mode_key="auto", pace_key="normal", target_seconds=15, engine=fake)
        self.assertEqual(draft.mode, "try_on")
        self.assertIn("지정된 모드: try_on", calls[0][1])
        self.assertTrue(any("9개 중 6개" in note for note in draft.notes))
        mixed = looked([("춤", "", ""), ("요리", "", ""), ("운동", "", ""), ("이동·풍경", "", ""), ("기타", "", "")])
        fake, _ = engine({"mode": "travel", "title": "t", "hook_shot": 1, "scenes": [{"shot": 1, "caption": "a"}]})
        self.assertEqual(build_draft(mixed, mode_key="auto", pace_key="normal", target_seconds=10, engine=fake).mode, "travel",
                         "no clear majority: the AI still chooses")

    def test_counting_is_not_given_to_the_ai_and_copied_lines_are_rewritten_once(self):
        rows = [("춤", "", "1, 2, 3, 4, 5!"), ("춤", "", "호흡 진흙 호흡"), ("춤", "", "할 수 있어")]
        first = {"mode": "challenge", "title": "첫 댄스곡 도전기", "hook_shot": 1, "scenes": [
            {"shot": 1, "caption": "1, 2, 3, 4, 5!"}, {"shot": 2, "caption": "호흡, 진흙, 호흡!"},
            {"shot": 3, "caption": "포기 안 해"}]}
        second = {**first, "scenes": [{"shot": 1, "caption": "동작 바로잡기"}, {"shot": 2, "caption": "호흡, 진흙, 호흡!"},
                                      {"shot": 3, "caption": "포기 안 해"}]}
        third = {"lines": [{"shot": 2, "caption": "거울 보며 맞추기"}]}  # TODO 14: the emptied line is filled
        answers = iter([first, second, third])
        calls = []

        def complete(system, user, schema):
            calls.append(user)
            return json.dumps(next(answers), ensure_ascii=False)
        draft = build_draft(looked(rows), mode_key="challenge", pace_key="normal", target_seconds=10,
                            engine=("ollama", "gemma3:4b", complete))
        self.assertNotIn("1, 2, 3, 4, 5", calls[0])
        self.assertIn("들린 말(참고만): 호흡 진흙 호흡", calls[0])
        self.assertEqual(len(calls), 4, "draft, rewrite, fill, then the title-only call (TODO 20)")
        self.assertIn("다시 써라: 장면 1, 2의", calls[1])
        self.assertNotIn("호흡 진흙 호흡", calls[1], "copied shots lose their speech in the rewrite")
        self.assertIn("채울 장면: 2", calls[2])
        self.assertNotIn("호흡 진흙", calls[2], "the fill request never shows what was heard")
        captions = {s.shot_index: s.caption for s in draft.scenes}
        self.assertEqual(captions[1], "동작 바로잡기")
        self.assertEqual(captions[2], "거울 보며 맞추기", "still copied after the rewrite: a new line, not the lyric")
        self.assertEqual(captions[3], "포기 안 해")

    def test_try_on_gets_name_tags_and_numbers_from_the_screen(self):
        rows = [("옷 보여주기", "플라워 롱원피스", ""), ("옷 보여주기", "브라운 미니스커트", ""),
                ("옷 보여주기", "브라운 스커트", ""), ("옷 보여주기", "플라워 원피스", ""), ("옷 보여주기", "", ""),
                ("옷 보여주기", "빈티지 롱스커트", "")]
        fake, calls = engine({"mode": "try_on", "title": "직접 입어본 추천템 3가지", "hook_shot": 1,
                          "scenes": [{"shot": n, "caption": f"문구{n}"} for n in range(1, 7)]})
        draft = build_draft(looked(rows, 2.5), mode_key="auto", pace_key="normal", target_seconds=15, engine=fake)
        self.assertIn("보여주는 옷·물건 4가지(촬영 순서): 플라워 롱원피스(장면 1~1), 브라운 미니스커트(장면 2~3)", calls[0][1])
        got = [(s.shot_index, s.label, s.caption) for s in draft.scenes]
        self.assertEqual(got, [(1, "플라워 원피스", "문구1"), (2, "브라운 미니스커트", "첫 번째"), (3, "브라운 미니스커트", "문구3"),
                               (4, "플라워 원피스", "두 번째"), (5, "플라워 원피스", "문구5"), (6, "빈티지 롱스커트", "세 번째")])

    def test_try_on_like_blo_three_items_title_count_and_every_scene_has_a_line(self):
        """TODO 14, the user's try-on sample: 5 names on screen (fur jacket, blouse) but 3 items in Blo."""
        rows = [("옷 보여주기", item, "") for item in (
            "블랙 데님", "브라운 미니스커트", "브라운 미니스커트", "화이트 퍼 재킷", "", "녹색 레이스 원피스", "그린 블라우스",
            "카모플라주 팬츠", "", "")]
        captions = {1: "오늘 고른 옷들", 2: "첫 핏 체크", 3: "이 스커트 예쁘다", 4: "재킷 걸쳐보기", 5: "장미빛 스커트 💖.",
                    6: "레이스 원피스", 7: "살랑살랑", 8: "팬츠도 입어봄", 9: "이 팬츠 맘에 들어", 10: "이 팬츠 맘에 들어"}
        answers = iter([
            {"mode": "try_on", "title_lead": "오늘의", "title": "오늘의 꿀템 5가지", "hook_shot": 1,
             "scenes": [{"shot": n, "caption": text} for n, text in captions.items()]},
            {"lines": [{"shot": 10, "caption": "이 팬츠 맘에 들어"}]},  # same as the line before: refused
        ])
        calls = []

        def complete(system, user, schema):
            calls.append(user)
            return json.dumps(next(answers), ensure_ascii=False)
        draft = build_draft(looked(rows, 2.5), mode_key="try_on", pace_key="normal", target_seconds=25,
                            engine=("ollama", "gemma3:4b", complete))
        got = {s.shot_index: (s.label, s.caption) for s in draft.scenes}
        self.assertEqual({label for label, _ in got.values() if label},
                         {"브라운 미니스커트", "녹색 레이스 원피스", "카모플라주 팬츠"}, "jacket and blouse are layers")
        self.assertEqual(got[1], ("", "오늘 고른 옷들"), "the hook's jeans are never numbered, so no name tag")
        self.assertEqual(got[4], ("브라운 미니스커트", "재킷 걸쳐보기"))
        self.assertEqual([got[n][1] for n in (2, 6, 8)], ["첫 번째", "두 번째", "세 번째"])
        self.assertEqual(got[5][1], "장미빛 스커트", "no emoji")
        self.assertIn("채울 장면: 10", calls[1])
        self.assertEqual(got[10], ("카모플라주 팬츠", "팬츠"), "last resort: the kind of item, as Blo does")
        self.assertEqual((draft.title_lead, draft.title), ("오늘의", "꿀템 3가지"))
        self.assertIn("제목의 개수를 이름표 개수(3가지)에 맞췄습니다.", draft.notes)

    def test_count_in_words_and_old_drafts_without_a_lead_in(self):
        from backend.app.services.reel_draft import _match_count, _title_parts, draft_from_json
        self.assertEqual(_match_count("직접 입어본 세 가지", 4), "직접 입어본 네 가지")
        self.assertEqual(_match_count("특별한 개 산책", 2), "특별한 개 산책")
        self.assertEqual(_title_parts("나만 아는 가수의", "첫 댄스곡 도전기 ✨"), ("나만 아는 가수의", "첫 댄스곡 도전기"))
        # the small AI's real answers on the user's samples
        self.assertEqual(_title_parts("", "직접 입어본 / 추천템 3가지"), ("직접 입어본", "추천템 3가지"))
        self.assertEqual(_title_parts("첫 댄스곡 도전기", "나만 아는 가수의 / 첫 댄스곡 도전기"),
                         ("나만 아는 가수의", "첫 댄스곡 도전기"))
        old = build_draft(shots([2.5] * 2), mode_key="challenge", pace_key="normal", target_seconds=5, engine=None).to_json()
        old.pop("title_lead")
        self.assertEqual(draft_from_json(old).title_lead, "")

    def test_counting_inside_a_line_and_base_tee_in_item_names(self):
        from backend.app.services.reel_draft import _copies_speech, _is_counting, _one_item
        self.assertTrue(_is_counting("1, 2, 3, 4, 5! 긍정 에너지!"))
        self.assertFalse(_is_counting("직접 입어본 추천템 3가지"))
        self.assertTrue(_copies_speech("대, 대야!! 완벽해!", "호흡.. 진흙... 대, 대야!! 잘했어!"))
        self.assertFalse(_copies_speech("폭풍 칭찬 받았어요", "잘하셨습니다 너무 잘 따라왔죠"))
        self.assertEqual(_one_item("흰색 반팔티, 짙은 갈색 미니스커트"), "짙은 갈색 미니스커트")

    def test_old_saved_shots_without_item_still_load(self):
        from backend.app.services.reel_draft import shots_from_json
        old = {"index": 1, "source_video_id": "s", "source_filename": "a.mp4", "start_seconds": 0.0, "end_seconds": 2.0,
               "caption": "c", "speech": "", "speech_start": None, "speech_end": None}
        self.assertEqual(shots_from_json([old])[0].item, "")


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

    def test_screen_answer_keeps_item_and_activity(self):
        from backend.app.services.reel_draft import ShotLook
        source_id = uuid4()

        def detect(path, *, source_video_id, duration_seconds, config):
            return ShotStructureResult(source_video_id, duration_seconds, (), (ShotInterval(source_video_id, 0.0, 3.0, None, None),))
        result = analyze_shots([SourceInput(source_id, "a.mp4", Path("a.mp4"), 3.0)], detect=detect,
                               describe=lambda *_: ShotLook(caption="거울 앞 셀카", item="브라운 미니스커트", activity="옷 보여주기"))
        self.assertEqual((result[0].item, result[0].activity), ("브라운 미니스커트", "옷 보여주기"))


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


class ReelChatHistoryApiTests(ReelDraftApiTests):
    """TODO 18: put a removed scene back, undo many times, and edit while a video is being made."""

    def test_put_back_and_undo_many_times(self):
        with patch.object(project_reel, "analyze_shots", self.fake_analyze), \
                patch("backend.app.services.reel_draft.configured_engine", return_value=None):
            self.client.post(f"/projects/{self.project_id}/reel-draft", json={"mode": "travel", "pace": "fast", "target_seconds": 15})
            original = self.wait()
        self.assertEqual((original["undo_count"], original["unused_shots"]), (0, []))
        edit = lambda message: self.client.post(f"/projects/{self.project_id}/reel-draft/edit",  # noqa: E731
                                                json={"message": message}).json()
        with patch("backend.app.services.llm_edit_interpreter.configured_engine", return_value=None):
            removed = edit("2번 빼")
            self.assertEqual([shot["index"] for shot in removed["unused_shots"]],
                             [original["draft"]["scenes"][1]["shot_index"]])
            edit("1번 자막 '안녕' 추가")
            # a video being made does not block editing any more
            project_reel._render_jobs[self.project_id] = project_reel.ReelJob(status="RUNNING", step="영상")
            self.addCleanup(project_reel._render_jobs.pop, self.project_id, None)
            back = edit("아까 뺀 장면 다시 넣어줘")
        self.assertTrue(back["done_edits"][0].startswith("컷 "))
        self.assertEqual(back["draft"]["scenes"], [{**original["draft"]["scenes"][0], "caption": "안녕"},
                                                   *original["draft"]["scenes"][1:]])
        self.assertEqual((back["undo_count"], back["unused_shots"]), (3, []))
        self.assertEqual(back["recent_changes"][1], "1번 장면 문구 → '안녕'")
        undone = [self.client.post(f"/projects/{self.project_id}/reel-draft/undo").json() for _ in range(3)]
        self.assertEqual([u["undo_count"] for u in undone], [2, 1, 0])
        self.assertEqual(undone[0]["undone"], back["done_edits"][0])
        self.assertEqual(undone[-1]["draft"], original["draft"])
        self.assertEqual(self.client.post(f"/projects/{self.project_id}/reel-draft/undo").status_code, 409)

    def test_older_save_with_one_previous_draft_can_still_undo(self):
        with patch.object(project_reel, "analyze_shots", self.fake_analyze), \
                patch("backend.app.services.reel_draft.configured_engine", return_value=None):
            self.client.post(f"/projects/{self.project_id}/reel-draft", json={"mode": "travel", "pace": "fast", "target_seconds": 15})
            original = self.wait()
        from backend.app.models.reel import ProjectReelDraft
        with self.factory() as session:
            record = session.get(ProjectReelDraft, self.project_id)
            record.draft = {**record.draft, "title": "고친 제목", "previous_draft": dict(record.draft)}
            session.commit()
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/reel-draft").json()["undo_count"], 1)
        undone = self.client.post(f"/projects/{self.project_id}/reel-draft/undo").json()
        self.assertEqual((undone["draft"]["title"], undone["undo_count"]), (original["draft"]["title"], 0))


def by_prompt(draft, titles=None, more=()):
    """Fake AI: the title-only call gets ``titles``, every other call the next answer (the draft first)."""
    from backend.app.services.reel_draft import TITLE_SYSTEM_PROMPT
    answers = iter([draft, *more])
    calls = []

    def complete(system, user, schema):
        calls.append((system, user, schema))
        if system == TITLE_SYSTEM_PROMPT:
            if titles is None:
                raise LLMEditError("LLM_UNAVAILABLE")
            return json.dumps({"titles": titles}, ensure_ascii=False)
        return json.dumps(next(answers), ensure_ascii=False)
    return ("ollama", "gemma3:4b", complete), calls


class HookTitleTests(TestCase):
    """TODO 20: three more titles from a title-only call (different formulas) next to the draft's own title; Python
    picks one. Lines over 14 characters are rewritten once, then shortened by a small call."""

    def test_title_call_adds_candidates_and_a_screen_word_wins(self):
        rows = [Shot(1, "s", "a.mp4", 0, 3, "연습실 거울 앞에서 춤을 배운다"), Shot(2, "s", "a.mp4", 3, 6, "선생님이 동작을 알려준다")]
        fake, calls = by_prompt(
            {"mode": "challenge", "title_lead": "오늘의", "title": "춤 연습 시작", "hook_shot": 1,
             "scenes": [{"shot": 1, "caption": "거울 보며 따라하기"}, {"shot": 2, "caption": "동작 배우는 중"}]},
            [{"formula": "반전", "title_lead": "처음 배웠는데", "title": "선생님 칭찬 폭격"},
             {"formula": "단언", "title_lead": "춤 연습은", "title": "무조건 거울 앞 ✨"},
             {"formula": "고백", "title_lead": "사실", "title": "사실 처음임"}])
        draft = build_draft(rows, mode_key="challenge", pace_key="normal", target_seconds=6, engine=fake)
        self.assertEqual((draft.title_lead, draft.title), ("처음 배웠는데", "선생님 칭찬 폭격"),
                         "first candidate with a word from the screen; the bland draft title loses")
        self.assertEqual([(o.lead, o.title, o.formula) for o in draft.title_options], [
            ("처음 배웠는데", "선생님 칭찬 폭격", "반전"), ("춤 연습은", "무조건 거울 앞", "단언"), ("사실", "처음임", "고백"),
            ("오늘의", "춤 연습 시작", "모드")])
        system, user, schema = calls[-1]
        self.assertEqual(schema["properties"]["titles"]["minItems"], 3)
        self.assertNotIn("모드", schema["$defs"]["_AITitle"]["properties"]["formula"]["enum"])
        self.assertIn("반전: ○○했는데 / ○○", user)
        self.assertIn("- 연습실 거울 앞에서 춤을 배운다", user)

    def test_without_the_title_call_the_draft_keeps_its_own_title(self):
        fake, _ = by_prompt({"mode": "travel", "title_lead": "바다 보러", "title": "떠난 하루", "hook_shot": 1,
                             "scenes": [{"shot": 1, "caption": "바다 앞 산책"}]})
        draft = build_draft(shots([3]), mode_key="travel", pace_key="normal", target_seconds=3, engine=fake)
        self.assertEqual((draft.title_lead, draft.title, draft.title_options), ("바다 보러", "떠난 하루", ()))

    def test_lifted_examples_speech_and_repeats_lose(self):
        from backend.app.services.reel_draft import TitleOption, _pick_title
        rows = [Shot(1, "s", "a.mp4", 0, 3, "장발의 여성이 연습실에서 춤을 춘다", "호흡, 진흙, 호흡!")]
        picked = _pick_title([TitleOption("처음 뵙겠습니다", "장발의 도전기", "반전"),
                              TitleOption("첫 도전기", "장발의 첫 도전기", "모드"),
                              TitleOption("호흡하다가", "진흙 호흡의 이유", "궁금증"),
                              TitleOption("연습실에서", "춤 실력 폭발", "단언")], rows, ("처음 뵙겠습니다",))
        self.assertEqual(picked[0].title, "춤 실력 폭발")

    def test_long_lines_are_rewritten_then_shortened(self):
        long1, long2 = "선생님 따라서 열심히 동작을 맞추는 중", "거울 앞에서 다 같이 포즈 잡기 성공"
        first = {"mode": "challenge", "title_lead": "처음인데", "title": "칭찬 받음", "hook_shot": 1,
                 "scenes": [{"shot": 1, "caption": "시작"}, {"shot": 2, "caption": long1}, {"shot": 3, "caption": long2}]}
        second = {**first, "scenes": [{"shot": 1, "caption": "시작"}, {"shot": 2, "caption": "동작 / 맞추는 중"},
                                      {"shot": 3, "caption": "거울 앞에서 다 같이 포즈 잡기 성공해서 신남"}]}
        shorter = {"lines": [{"shot": 3, "caption": "거울 앞 포즈 성공"}]}
        fake, calls = by_prompt(first, more=(second, shorter))
        draft = build_draft(shots([2.5] * 3), mode_key="challenge", pace_key="normal", target_seconds=7, engine=fake)
        self.assertIn("다시 써라: 장면 2, 3의 문구가 너무 길거나(14자 넘음)", calls[1][1])
        self.assertIn("[3] 거울 앞에서 다 같이 포즈 잡기 성공", calls[2][1], "only the line still too long is shortened")
        captions = {s.shot_index: s.caption for s in draft.scenes}
        self.assertEqual(captions[2], "동작 맞추는 중", "shorter rewrite taken, no '/' in a line")
        self.assertEqual(captions[3], "거울 앞 포즈 성공", "longer rewrite refused, then shortened")

    def test_title_options_survive_saving(self):
        from backend.app.services.reel_draft import TitleOption, draft_from_json
        fake, _ = by_prompt({"mode": "travel", "title_lead": "a", "title": "b", "hook_shot": 1,
                             "scenes": [{"shot": 1, "caption": "바다 앞 산책"}]}, [{"formula": "고백", "title_lead": "c", "title": "d"}])
        draft = build_draft(shots([3]), mode_key="travel", pace_key="normal", target_seconds=3, engine=fake)
        back = draft_from_json(json.loads(json.dumps(draft.to_json())))
        self.assertEqual(set(back.title_options), {TitleOption("a", "b", "모드"), TitleOption("c", "d", "고백")})
