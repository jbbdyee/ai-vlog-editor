"""TODO 7: recommended length + widening short scene moments into clips that add up to the target."""

from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from backend.app.services.story_length import (MAX_CLIP_SECONDS, Moment, SourceTiming, accept_minutes, fit_to_length,
                                               length_notes, rule_minutes)
from backend.tests import test_qa03_render_integrity as qa03

A, B = uuid4(), uuid4()


def lengths(fit):
    return [round(end - start, 3) for start, end in fit.clips]


class RuleMinutesTests(TestCase):
    def test_about_a_quarter_between_3_and_25_minutes_and_never_longer_than_the_footage(self):
        self.assertEqual(rule_minutes(31 * 60), 8)
        self.assertEqual(rule_minutes(180 * 60), 25)
        self.assertEqual(rule_minutes(6 * 60), 3)
        self.assertEqual(rule_minutes(90), 1)  # 1.5 minutes of footage cannot become a 3 minute vlog

    def test_ai_minutes_are_accepted_only_when_possible(self):
        self.assertTrue(accept_minutes(7, 31 * 60))
        self.assertFalse(accept_minutes(None, 31 * 60))
        self.assertFalse(accept_minutes(40, 180 * 60))  # above 25
        self.assertFalse(accept_minutes(10, 5 * 60))  # longer than the footage


class FitToLengthTests(TestCase):
    timing = {A: SourceTiming(600.0), B: SourceTiming(600.0)}

    def test_short_moments_are_widened_until_the_total_reaches_the_target(self):
        moments = [Moment(A, 100, 103), Moment(A, 300, 303), Moment(B, 50, 54)]
        fit = fit_to_length(moments, self.timing, 60)
        self.assertAlmostEqual(fit.total_seconds, 60, delta=0.5)
        for moment, (start, end) in zip(moments, fit.clips):
            self.assertLessEqual(start, moment.start)  # the found moment always stays inside its clip
            self.assertGreaterEqual(end, moment.end)

    def test_clips_never_overlap_leave_the_video_or_exceed_the_cap(self):
        moments = [Moment(A, 2, 5), Moment(A, 10, 13), Moment(A, 590, 595)]
        fit = fit_to_length(moments, self.timing, 600)
        (s1, e1), (s2, e2), (s3, e3) = fit.clips
        self.assertGreaterEqual(s1, 0)
        self.assertLessEqual(e1, s2)  # neighbours meet at most at the midpoint
        self.assertLessEqual(e3, 600)
        self.assertTrue(all(length <= MAX_CLIP_SECONDS + 1e-6 for length in lengths(fit)))
        self.assertLess(fit.max_seconds, 600)
        self.assertIn("최대한 넓혀도", length_notes(fit)[0])

    def test_clip_edges_move_out_to_the_sentence_so_speech_is_not_cut(self):
        timing = {A: SourceTiming(600.0, ((80.0, 96.5), (106.0, 113.0)))}
        fit = fit_to_length([Moment(A, 100, 103)], timing, 16)
        start, end = fit.clips[0]
        self.assertEqual(end, 113.0)  # the clip end fell inside the sentence "106~113" and moved to its end
        self.assertAlmostEqual(start, 94.0, delta=0.01)  # 94 is 14 s past the sentence start (too far), so it stays

    def test_a_target_shorter_than_the_moments_keeps_them_as_they_are(self):
        fit = fit_to_length([Moment(A, 100, 110), Moment(B, 0, 10)], self.timing, 5)
        self.assertEqual(fit.clips, ((100, 110), (0, 10)))
        self.assertIn("목표보다 깁니다", length_notes(fit)[0])


class AiLengthTests(TestCase):
    def test_ai_is_asked_for_a_length_and_its_answer_is_kept(self):
        from backend.tests.test_story_direction import ALL, NAMES, chapter, engine
        calls = []
        payload = {"title": "t", "summary": "s", "chapters": [chapter("처음", [1, 2])],
                   "recommended_minutes": 7, "length_reason": "레슨이라 핵심 동작만"}
        from backend.app.services.story_direction import recommend_story_direction
        result = recommend_story_direction(ALL, NAMES, engine(payload, calls), footage_minutes=31)
        self.assertEqual((result.recommended_minutes, result.length_reason), (7, "레슨이라 핵심 동작만"))
        user, schema = calls[0]
        self.assertIn("원본 영상 전체 길이: 약 31분", user)
        self.assertIn("recommended_minutes", schema["required"])


class StoryLengthApiTests(TestCase):
    setUp = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url

    def test_rule_recommends_a_length_and_widens_the_scene(self):
        with patch("backend.app.services.story_direction.configured_engine", return_value=None):
            body = self.client.post(self.url("/story-direction")).json()
        # mock project: one 5 s video with a 1~2 s moment -> 1 minute recommended, clip grows to the whole video
        self.assertEqual((body["recommended_minutes"], body["target_minutes"]), (1, 1))
        scene = body["chapters"][0]["scenes"][0]
        self.assertEqual((scene["start_seconds"], scene["end_seconds"]), (1.0, 2.0))
        self.assertEqual((scene["clip_start_seconds"], scene["clip_end_seconds"]), (0.0, 5.0))
        self.assertEqual((body["total_seconds"], body["max_seconds"], body["footage_seconds"]), (5.0, 5.0, 5.0))
        self.assertIn(1, body["length_options"])

    def test_changing_the_length_reuses_the_chapters_without_asking_the_ai(self):
        reuse = {"title": "내 추천", "summary": "요약", "engine": "llm:fake/m", "recommended_minutes": 1,
                 "length_reason": "짧은 영상이라", "chapters": [
                     {"title": "처음", "description": "d", "reason": "r", "candidate_ids": [str(self.candidate_id)]}]}
        with patch("backend.app.services.story_direction.configured_engine", side_effect=AssertionError("AI called")):
            response = self.client.post(self.url("/story-direction"), json={"target_minutes": 3, "reuse": reuse})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["title"], body["engine"], body["target_minutes"], body["length_reason"]),
                         ("내 추천", "llm:fake/m", 3, "짧은 영상이라"))
        self.assertIn("최대한 넓혀도", body["notes"][-1])

    def test_reuse_with_only_unknown_scenes_is_refused(self):
        reuse = {"title": "t", "summary": "s", "engine": "rule", "recommended_minutes": 1, "length_reason": "x",
                 "chapters": [{"title": "c", "description": "d", "reason": "r", "candidate_ids": [str(uuid4())]}]}
        response = self.client.post(self.url("/story-direction"), json={"target_minutes": 3, "reuse": reuse})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "STORY_SCENES_GONE")
