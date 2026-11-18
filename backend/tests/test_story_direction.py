"""Project-wide recommended edit direction: LLM chapters validated by code, rule fallback, read-only API."""

import json
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from backend.app.models import EpisodeSplitPolicy, Project
from backend.app.services.llm_edit_interpreter import LLMEditError
from backend.app.services.project_scene_candidates import ActiveCandidateSummary, CandidateEvidenceSummary
from backend.app.services.story_direction import in_day_order, recommend_story_direction
from backend.tests import test_qa03_render_integrity as qa03

VIDEO_A, VIDEO_B = uuid4(), uuid4()
NAMES = {VIDEO_A: "IMG_0002.MOV", VIDEO_B: "IMG_0001.MOV"}  # B sorts first by file name


def scene(source, start, end, speech):
    return ActiveCandidateSummary(uuid4(), source, Decimal(str(start)), Decimal(str(end)),
                                  (CandidateEvidenceSummary("TRANSCRIPT", "TRANSCRIPT_STRUCTURE", 1),), speech)


ARRIVE = scene(VIDEO_B, 0, 5, "공항에 도착했어요")
HOTEL = scene(VIDEO_B, 10, 18, "호텔 체크인 했어요")
FOOD = scene(VIDEO_A, 2, 9, "저녁으로 라멘 먹어요")
NIGHT = scene(VIDEO_A, 20, 30, "야경이 정말 예쁘다")
ALL = [NIGHT, FOOD, HOTEL, ARRIVE]  # unordered on purpose; numbering = file order, then time


def engine(payload, calls=None):
    def complete(system, user, schema):
        if calls is not None:
            calls.append((user, schema))
        if isinstance(payload, Exception):
            raise payload
        return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ("fake", "m", complete)


def chapter(title, scenes):
    return {"title": title, "description": f"{title} 설명", "reason": f"{title} 이유", "scenes": scenes}


def ids(chapter_):
    return [s.candidate.candidate_id for s in chapter_.scenes]


class StoryDirectionTests(TestCase):
    def test_llm_chapters_are_used_in_order_with_file_names(self):
        calls = []
        result = recommend_story_direction(ALL, NAMES, engine({
            "title": "도쿄 여행", "summary": "도착부터 야경까지",
            "chapters": [chapter("도착", [1, 2]), chapter("저녁", [3]), chapter("밤", [4])]}, calls))
        self.assertEqual(result.engine, "llm:fake/m")
        self.assertEqual((result.title, result.fallback_reason), ("도쿄 여행", None))
        self.assertEqual([c.title for c in result.chapters], ["도착", "저녁", "밤"])
        self.assertEqual(ids(result.chapters[0]), [ARRIVE.candidate_id, HOTEL.candidate_id])
        self.assertEqual(result.chapters[0].scenes[0].source_filename, "IMG_0001.MOV")
        self.assertEqual(result.chapters[0].total_seconds, 13.0)
        prompt, schema = calls[0]
        self.assertIn("1. 영상 1 0.0~5.0초", prompt)
        self.assertIn("4. 영상 2 20.0~30.0초", prompt)
        self.assertNotIn("IMG_", prompt)  # file names stay local
        self.assertEqual(schema["$defs"]["LLMChapter"]["properties"]["scenes"]["items"]["enum"], [1, 2, 3, 4])

    def test_duplicates_keep_first_chapter_and_unused_scenes_are_noted(self):
        result = recommend_story_direction(ALL, NAMES, engine({
            "title": "t", "summary": "s", "chapters": [chapter("A", [2, 1]), chapter("B", [1]), chapter("C", [3])]}))
        self.assertEqual([c.title for c in result.chapters], ["A", "C"])  # B became empty and was dropped
        self.assertEqual(ids(result.chapters[0]), [HOTEL.candidate_id, ARRIVE.candidate_id])  # LLM order kept
        self.assertTrue(any("겹친 장면 1개" in n for n in result.notes))
        self.assertTrue(any("넣지 않은 장면이 1개" in n for n in result.notes))

    def test_bad_llm_output_falls_back_to_one_chapter_per_video(self):
        for payload, reason in [
            ({"title": "t", "summary": "s", "chapters": [chapter("A", [9])]}, "LLM_UNKNOWN_SCENE"),
            ("not json", "LLM_SCHEMA_INVALID"),
            ({"title": "t", "summary": "s", "chapters": []}, "LLM_SCHEMA_INVALID"),
            (LLMEditError("LLM_TIMEOUT"), "LLM_TIMEOUT"),
        ]:
            with self.subTest(reason=reason):
                result = recommend_story_direction(ALL, NAMES, engine(payload))
                self.assertEqual((result.engine, result.fallback_reason), ("rule", reason))
                self.assertEqual([c.title for c in result.chapters], ["영상 1: IMG_0001.MOV", "영상 2: IMG_0002.MOV"])
                self.assertEqual(ids(result.chapters[1]), [FOOD.candidate_id, NIGHT.candidate_id])
                self.assertIn("AI 추천을 만들지 못해", result.notes[0])

    def test_without_llm_configuration_rule_outline_is_returned(self):
        with patch("backend.app.services.story_direction.configured_engine", return_value=None):
            result = recommend_story_direction(ALL, NAMES)
        self.assertEqual((result.engine, result.fallback_reason), ("rule", None))
        self.assertEqual(len(result.chapters), 2)
        self.assertIn("AI 설정이 없어", result.notes[0])


class StoryDirectionApiTests(TestCase):
    setUp = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url

    def test_story_direction_is_read_only_and_lists_scenes_with_file_names(self):
        before = self.client.get(self.url("/scene-edit-plan")).json()
        with patch("backend.app.services.story_direction.configured_engine", return_value=None):
            response = self.client.post(self.url("/story-direction"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["engine"], body["fallback_reason"]), ("rule", None))
        scene_ = body["chapters"][0]["scenes"][0]
        self.assertEqual((scene_["candidate_id"], scene_["source_filename"]), (str(self.candidate_id), "mock.mp4"))
        self.assertEqual((scene_["start_seconds"], scene_["end_seconds"]), (1.0, 2.0))
        self.assertEqual(self.client.get(self.url("/scene-edit-plan")).json(), before)  # nothing saved

    def test_missing_project_and_project_without_scenes(self):
        self.assertEqual(self.client.post(f"/projects/{uuid4()}/story-direction").status_code, 404)
        with self.factory.begin() as session:
            empty = Project(name="빈 프로젝트", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(empty); session.flush()
            empty_id = empty.id
        response = self.client.post(f"/projects/{empty_id}/story-direction")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "NO_SCENE_CANDIDATES")


class DayBriefTests(TestCase):
    """TODO 23: the user's "오늘 있었던 일" note goes first in the AI request and is kept per project."""

    def test_brief_leads_the_request_and_adds_the_brief_rule(self):
        seen = []

        def complete(system, user, schema):
            seen.append((system, user))
            return json.dumps({"title": "t", "summary": "s", "chapters": [chapter("도착", [1])]})
        recommend_story_direction(ALL, NAMES, ("fake", "m", complete), day_brief="  공항 도착, 저녁 라멘이 핵심  ")
        recommend_story_direction(ALL, NAMES, ("fake", "m", complete))
        (system, user), (plain_system, plain_user) = seen
        self.assertTrue(user.startswith("오늘 있었던 일(사용자가 직접 적음):\n공항 도착, 저녁 라멘이 핵심\n"))
        self.assertIn("설명을 믿는다", system)
        self.assertNotIn("오늘 있었던 일", plain_user)
        self.assertNotIn("설명을 믿는다", plain_system)
        self.assertNotIn("도착·준비", system)  # the generic shape gives way to the note
        self.assertIn("도착·준비", plain_system)


class DayBriefApiTests(TestCase):
    setUp = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url

    def test_brief_is_saved_reused_and_cleared(self):
        self.assertEqual(self.client.get(self.url("/day-brief")).json(), {"text": ""})
        seen = []

        def complete(system, user, schema):
            seen.append(user)
            return json.dumps({"title": "t", "summary": "s", "chapters": [chapter("하루", [1])]})
        with patch("backend.app.services.story_direction.configured_engine", return_value=("fake", "m", complete)):
            first = self.client.post(self.url("/story-direction"), json={"day_brief": "학원에서 팀 회의"})
            again = self.client.post(self.url("/story-direction"))  # no note sent -> the saved one is used
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()["day_brief"], again.json()["day_brief"]), ("학원에서 팀 회의", "학원에서 팀 회의"))
        self.assertTrue(all("학원에서 팀 회의" in user for user in seen))
        self.assertEqual(self.client.get(self.url("/day-brief")).json(), {"text": "학원에서 팀 회의"})
        with patch("backend.app.services.story_direction.configured_engine", return_value=None):
            cleared = self.client.post(self.url("/story-direction"), json={"day_brief": ""})
        self.assertEqual(cleared.json()["day_brief"], "")
        self.assertEqual(self.client.get(self.url("/day-brief")).json(), {"text": ""})


# ---- TODO 32: the day in order, ending on the last scene filmed ----------------------------------------------------
MORNING, CLASS, DINNER, NIGHT_HOME = uuid4(), uuid4(), uuid4(), uuid4()
DAY_NAMES = {NIGHT_HOME: "DJI_20261112231300_0035_D.MP4", DINNER: "DJI_20261112180000_0020_D.MP4",
             CLASS: "DJI_20261112090000_0010_D.MP4", MORNING: "DJI_20261112071800_0001_D.MP4"}
WALK = scene(MORNING, 0, 6, "학원 가는 길")
TALK = scene(CLASS, 30, 40, "발표할게요")
LATE_CLASS = scene(CLASS, 300, 310, "질문 있어요")
CHICKEN = scene(DINNER, 5, 15, "치킨 먹자")
BED = scene(NIGHT_HOME, 0, 4, "오늘 끝")
DAY = [BED, CHICKEN, LATE_CLASS, TALK, WALK]


class DayOrderTests(TestCase):
    def direction(self, chapters):
        # scene numbers follow file order: 1 WALK, 2 TALK, 3 LATE_CLASS, 4 CHICKEN, 5 BED
        return recommend_story_direction(DAY, DAY_NAMES, engine({"title": "학원 하루", "summary": "하루",
                                                                  "chapters": chapters}))

    def test_mixed_times_are_put_back_in_day_order_and_end_on_last_scene(self):
        result = in_day_order(self.direction([chapter("아침", [1]), chapter("저녁", [4]), chapter("수업", [3, 2])]),
                              DAY, DAY_NAMES)
        flat = [s.candidate.candidate_id for c in result.chapters for s in c.scenes]
        self.assertEqual(flat, [s.candidate_id for s in (WALK, TALK, LATE_CLASS, CHICKEN, BED)])
        self.assertEqual([c.title for c in result.chapters], ["아침", "수업", "저녁"])
        self.assertTrue(any("거꾸로 가던 곳 2곳" in note for note in result.notes))
        self.assertTrue(any("마지막에 찍은 장면" in note for note in result.notes))

    def test_split_chapter_keeps_title_with_continued_mark(self):
        result = in_day_order(self.direction([chapter("학원", [2, 4]), chapter("수업", [3]), chapter("밤", [5])]),
                              DAY, DAY_NAMES)
        self.assertEqual([c.title for c in result.chapters], ["학원", "수업", "학원 (이어서)", "밤"])
        self.assertEqual(ids(result.chapters[2]), [CHICKEN.candidate_id])

    def test_already_in_order_is_unchanged(self):
        before = self.direction([chapter("하루", [1, 2, 5])])
        self.assertIs(in_day_order(before, DAY, DAY_NAMES), before)

    def test_without_times_in_names_file_order_is_used(self):
        names = {MORNING: "b.mp4", CLASS: "a.mp4", DINNER: "c.mp4", NIGHT_HOME: "d.mp4"}
        result = in_day_order(recommend_story_direction(DAY, names, engine({"title": "t", "summary": "s",
                              "chapters": [chapter("x", [4, 1])]})), DAY, names)
        # file order: a(CLASS) b(MORNING) c(DINNER) d(NIGHT): scene 1 = TALK, 4 = CHICKEN, last = BED
        flat = [s.candidate.candidate_id for c in result.chapters for s in c.scenes]
        self.assertEqual(flat, [TALK.candidate_id, CHICKEN.candidate_id, BED.candidate_id])

    def test_my_voice_scenes_are_shown_to_the_ai_and_kept(self):
        # TODO 32-2: the AI sees "내 목소리 N줄"; a scene in my voice it left out goes in at its time
        calls = []
        before = recommend_story_direction(DAY, DAY_NAMES, engine({"title": "t", "summary": "s",
                                           "chapters": [chapter("아침", [1]), chapter("저녁", [4])]}, calls),
                                           my_voice={TALK.candidate_id: 3})
        self.assertIn("내 목소리 3줄", calls[0][0])
        self.assertEqual(calls[0][0].count("내 목소리"), 1)
        result = in_day_order(before, DAY, DAY_NAMES, (TALK.candidate_id,))
        flat = [s.candidate.candidate_id for c in result.chapters for s in c.scenes]
        self.assertEqual(flat, [s.candidate_id for s in (WALK, TALK, CHICKEN, BED)])
        self.assertTrue(any("내가 말하는 장면 1개" in note for note in result.notes))
