"""Natural-language edit request -> suggested scene order (rule based, read-only)."""

from decimal import Decimal
from unittest import TestCase
from uuid import uuid4

from sqlalchemy import select

from backend.app.models import (
    ProjectSceneEditPlan, SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneCandidate,
    SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo, Transcript,
)
from backend.app.services.edit_request import parse_edit_request, suggest_edit
from backend.app.services.project_scene_candidates import ActiveCandidateSummary, CandidateEvidenceSummary
from backend.tests import test_qa03_render_integrity as qa03

SOURCE = uuid4()


def candidate(start, end, speech=None, *types):
    return ActiveCandidateSummary(uuid4(), SOURCE, Decimal(str(start)), Decimal(str(end)),
                                  tuple(CandidateEvidenceSummary("X", kind, 1) for kind in types), speech)


class ParseTests(TestCase):
    def test_duration_count_keywords_exclusions_categories_order(self):
        intent = parse_edit_request("강아지 나오는 장면 위주로 리액션 많이, 1분 30초 이내로 3개만, 광고는 빼고 역순으로")
        self.assertEqual(intent.target_seconds, 90)
        self.assertEqual(intent.max_count, 3)
        self.assertIn("강아지", intent.keywords)
        self.assertEqual(intent.excluded, ("광고",))
        self.assertNotIn("광고", intent.keywords)
        self.assertEqual(intent.categories, ("reaction",))
        self.assertEqual(intent.order, "reverse")

    def test_quoted_phrase_and_empty_request(self):
        self.assertIn("맛있다", parse_edit_request("'맛있다' 라고 말한 장면").keywords)
        intent = parse_edit_request("   ")
        self.assertEqual((intent.target_seconds, intent.max_count, intent.keywords, intent.categories), (None, None, (), ()))


class SuggestTests(TestCase):
    def setUp(self):
        self.cafe = candidate(0, 4, "카페에 도착했어요", "TRANSCRIPT_STRUCTURE")
        self.dance = candidate(10, 15, "같이 춤 춰요", "VISUAL_ACTIVITY", "TRANSCRIPT_STRUCTURE")
        self.wow = candidate(20, 23, "우와 대박", "TRANSCRIPT_REACTION_CUE")
        self.ad = candidate(30, 34, "광고 협찬 안내", "TRANSCRIPT_STRUCTURE")
        self.all = [self.cafe, self.dance, self.wow, self.ad]

    def ids(self, suggestion):
        return [scene.candidate_id for scene in suggestion.scenes]

    def test_keyword_selects_matching_scene_with_reason(self):
        result = suggest_edit("카페 장면만 넣어줘", self.all)
        self.assertEqual(self.ids(result), [self.cafe.candidate_id])
        self.assertIn("'카페' 언급", result.scenes[0].reasons)

    def test_category_and_exclusion_and_chronological_order(self):
        result = suggest_edit("움직임이랑 리액션 위주로, 광고 빼고", self.all)
        self.assertEqual(self.ids(result), [self.dance.candidate_id, self.wow.candidate_id])
        self.assertNotIn(self.ad.candidate_id, self.ids(result))

    def test_target_duration_and_count_limit(self):
        self.assertLessEqual(suggest_edit("10초 이내로 만들어줘", self.all).total_seconds, 10)
        self.assertEqual(len(suggest_edit("2개만", self.all).scenes), 2)

    def test_reverse_order_and_select_all(self):
        result = suggest_edit("전부 역순으로", self.all)
        self.assertEqual(self.ids(result), [c.candidate_id for c in reversed(self.all)])

    def test_no_match_falls_back_with_note_instead_of_empty_plan(self):
        result = suggest_edit("고양이 장면", self.all)
        self.assertTrue(result.scenes)
        self.assertTrue(any("고양이" in note for note in result.notes))


class EditSuggestionApiTests(TestCase):
    setUp = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url

    def test_suggestion_is_read_only_and_returns_active_candidates_with_speech(self):
        with self.factory.begin() as session:
            source = session.scalars(select(SourceVideo)).one()
            session.add(Transcript(source_video_id=source.id, text="강아지랑 산책", language="ko",
                                   segments=[{"start_seconds": 0.5, "end_seconds": 2.5, "text": "강아지랑 산책해요"}]))
        before = self.client.get(self.url("/scene-edit-plan")).json()
        candidates = self.client.get(self.url("/scene-candidates")).json()["candidates"]
        self.assertEqual(candidates[0]["transcript_text"], "강아지랑 산책해요")
        response = self.client.post(self.url("/edit-suggestions"), json={"request": "강아지 10초 이내로"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["candidate_ids"], [str(self.candidate_id)])
        self.assertIn("'강아지' 언급", body["scenes"][0]["reasons"])
        self.assertEqual((body["target_seconds"], body["order"]), (10, "chronological"))
        visual = self.client.post(self.url("/edit-suggestions"), json={"request": "강아지 장면만"})
        self.assertEqual(visual.status_code, 200)
        self.assertEqual(visual.json()["candidate_ids"], [])  # STT alone does not prove what is visible
        self.assertEqual(self.client.get(self.url("/scene-edit-plan")).json(), before)  # nothing saved
        self.assertEqual(self.client.post(self.url("/edit-suggestions"), json={"request": ""}).status_code, 422)
        self.assertEqual(self.client.post(self.url("/edit-suggestions"), json={"request": "x" * 301}).status_code, 422)
        self.assertEqual(self.client.post(f"/projects/{uuid4()}/edit-suggestions", json={"request": "a"}).status_code, 404)
