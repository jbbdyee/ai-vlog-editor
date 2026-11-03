"""LLM edit interpretation: Pydantic validation, deterministic re-checks and rule-based fallback."""

import json
from dataclasses import replace
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from backend.app.services.llm_edit_interpreter import LLMEditError, LLMEditPlan, configured_engine, interpret_with_llm
from backend.app.services.project_scene_candidates import ActiveCandidateSummary, CandidateEvidenceSummary

SOURCE = uuid4()


def scene(start, end, speech):
    return ActiveCandidateSummary(uuid4(), SOURCE, Decimal(str(start)), Decimal(str(end)),
                                  (CandidateEvidenceSummary("TRANSCRIPT", "TRANSCRIPT_STRUCTURE", 1),), speech)


CAFE, LATTE, CAKE, DOG, SUNSET = (scene(0, 8, "골목에 있는 작은 카페에 왔어요"), scene(8, 17, "하트 모양 라떼 아트가 예쁘네요"),
                                 scene(17, 26, "우와 대박 딸기 케이크가 맛있어 보여요"), scene(34, 41, "뛰어노는 강아지를 만났어요"),
                                 scene(42, 52, "노을이 지기 시작했어요"))
ALL = [SUNSET, CAFE, DOG, LATTE, CAKE]  # unordered on purpose: numbering is chronological


def engine(payload, calls=None):
    def complete(system, user, schema):
        if calls is not None:
            calls.append(user)
        if isinstance(payload, Exception):
            raise payload
        return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ("fake", "m", complete)


def ids(result):
    return [s.candidate_id for s in result.suggestion.scenes]


class LLMEditTests(TestCase):
    def test_semantic_selection_is_applied_with_reasons_and_engine(self):
        calls = []
        dog = replace(DOG, visual_caption="공원에서 뛰는 강아지", visual_tags=("강아지",))
        result = interpret_with_llm("달달한 거랑 동물 나오는 장면만", [*ALL[:2], dog, *ALL[3:]], engine({
            "interpretation": "디저트와 강아지 장면", "selected_scenes": [3, 4], "excluded_scenes": [],
            "target_seconds": None, "mood": "fun", "order": "chronological",
            "reasons": [{"scene": 3, "reason": "딸기 케이크"}, {"scene": 4, "reason": "강아지"}]}, calls))
        self.assertEqual(ids(result), [dog.candidate_id])
        self.assertEqual((result.engine, result.mood, result.fallback_reason), ("llm:fake/m", "fun", None))
        self.assertIn("시각 조건 '동물'", result.suggestion.scenes[0].reasons[0])
        self.assertIn("1. 0.0~8.0초", calls[0])  # chronological numbering with speech in the prompt
        self.assertIn("대사: 뛰어노는 강아지를 만났어요", calls[0])

    def test_exclusion_order_and_length_cap_are_enforced_by_code(self):
        result = interpret_with_llm("노을부터 거꾸로, 카페 빼고 20초", ALL, engine({
            "interpretation": "역순", "selected_scenes": [1, 2, 3, 5], "excluded_scenes": [1],
            "target_seconds": 20, "order": "reverse", "reasons": []}))
        # reverse → 5,3,2 (1 excluded); cap 20 s keeps 5 (10 s) + 3 (9 s), drops 2.
        self.assertEqual(ids(result), [SUNSET.candidate_id, CAKE.candidate_id])
        self.assertLessEqual(result.suggestion.total_seconds, 20)
        self.assertTrue(any("목표 20초" in note for note in result.suggestion.notes))

    def test_custom_order_is_kept(self):
        result = interpret_with_llm("강아지 먼저, 그다음 라떼", ALL, engine({
            "interpretation": "순서 지정", "selected_scenes": [4, 2], "order": "custom", "reasons": []}))
        self.assertEqual(ids(result), [DOG.candidate_id, LATTE.candidate_id])

    def test_invalid_outputs_fall_back_to_rules(self):
        cases = {
            "LLM_SCHEMA_INVALID": "not json",
            "LLM_SCHEMA_INVALID ": {"interpretation": "x", "selected_scenes": [1], "surprise": True},
            "LLM_UNKNOWN_SCENE": {"interpretation": "x", "selected_scenes": [9]},
            "LLM_TIMEOUT": LLMEditError("LLM_TIMEOUT"),
        }
        for code, payload in cases.items():
            with self.subTest(code):
                result = interpret_with_llm("라떼 장면만", ALL, engine(payload))
                self.assertEqual((result.engine, result.fallback_reason), ("rule", code.strip()))
                self.assertEqual(ids(result), [LATTE.candidate_id])  # rule-based keyword match still works
                self.assertTrue(any("규칙 기반" in note for note in result.suggestion.notes))

    def test_empty_selection_without_verbatim_match_falls_back(self):
        result = interpret_with_llm("분위기 좋은 장면", ALL, engine({"interpretation": "x", "selected_scenes": [2], "excluded_scenes": [2]}))
        self.assertEqual((result.engine, result.fallback_reason), ("rule", "LLM_EMPTY_SELECTION"))

    def test_llm_cannot_drop_scenes_named_verbatim(self):
        result = interpret_with_llm("라떼랑 케이크만, 케이크 먼저", ALL, engine({
            "interpretation": "x", "selected_scenes": [1, 3], "excluded_scenes": [2, 4, 5], "order": "chronological"}))
        self.assertEqual(ids(result), [CAKE.candidate_id, LATTE.candidate_id])  # cafe dropped, latte kept, cake first
        self.assertTrue(any("맞지 않는 AI 선택" in note for note in result.suggestion.notes))

    def test_provider_configuration(self):
        with patch.dict("os.environ", {"CUTORY_EDIT_LLM_PROVIDER": ""}):
            self.assertIsNone(configured_engine())
            self.assertEqual(interpret_with_llm("라떼", ALL).engine, "rule")
        with patch.dict("os.environ", {"CUTORY_EDIT_LLM_PROVIDER": "ollama", "CUTORY_EDIT_LLM_MODEL": ""}):
            self.assertEqual(configured_engine()[:2], ("ollama", "gemma3:4b"))
        with patch.dict("os.environ", {"CUTORY_EDIT_LLM_PROVIDER": "openai", "OPENAI_API_KEY": ""}):
            self.assertIsNone(configured_engine())  # no key → rules, never an error

    def test_schema_rejects_extra_keys(self):
        self.assertFalse(LLMEditPlan.model_json_schema().get("additionalProperties", True))

    def test_first_word_is_not_cut_by_josa(self):
        # "노을 먼저" must not become "노" (+을), which also matched "뛰어노는" in the dog scene.
        dog = replace(DOG, visual_caption="뛰는 강아지")
        sunset = replace(SUNSET, visual_caption="석양이 보이는 하늘")
        result = interpret_with_llm("강아지랑 노을 장면, 노을 먼저", [sunset, CAFE, dog, LATTE, CAKE], engine({
            "interpretation": "x", "selected_scenes": [4, 5], "order": "chronological"}))
        self.assertEqual(ids(result), [SUNSET.candidate_id, DOG.candidate_id])
        self.assertTrue(all("시각 조건" in scene.reasons[0] for scene in result.suggestion.scenes))

    def test_literal_reason_distinguishes_spoken_and_visual_matches(self):
        visual = replace(scene(0, 3, "오늘 여행을 시작해요"), visual_caption="음식이 담긴 접시", visual_tags=("음식",))
        spoken = scene(4, 7, "음식이 맛있네요")
        both = replace(scene(8, 11, "음식이 보이네요"), visual_categories=("음식",))
        result = interpret_with_llm("음식이 나오는 장면만", [both, visual, spoken], engine({
            "interpretation": "음식 장면", "selected_scenes": [1, 2, 3], "order": "chronological",
            "reasons": [{"scene": 3, "reason": "접시 화면"}]}))
        self.assertEqual(ids(result), [visual.candidate_id, both.candidate_id])
        self.assertIn("화면 설명", result.suggestion.scenes[0].reasons[0])
        self.assertIn("화면 분류", result.suggestion.scenes[1].reasons[0])
        self.assertTrue(all("대사" not in reason for scene in result.suggestion.scenes for reason in scene.reasons))

    def test_food_visual_gate_rejects_unrelated_llm_scenes(self):
        cafe = replace(CAFE, visual_caption="카페 내부와 테이블", visual_tags=("카페",))
        cake = replace(CAKE, visual_caption="접시에 놓인 딸기 케이크", visual_tags=("케이크",))
        latte = replace(LATTE, visual_caption="라떼 아트", visual_tags=("음료",))
        result = interpret_with_llm("음식이 보이는 장면만", [cafe, latte, cake], engine({
            "interpretation": "음식", "selected_scenes": [1, 2, 3], "order": "chronological"}))
        self.assertEqual(ids(result), [cake.candidate_id])
        self.assertIn("케이크", result.suggestion.scenes[0].reasons[0])
        self.assertTrue(any("2개를 제외" in note for note in result.suggestion.notes))

    def test_missing_visual_evidence_returns_empty_including_rule_fallback(self):
        for completion in (engine({"interpretation": "음식", "selected_scenes": [1, 2]}),
                           engine(LLMEditError("LLM_TIMEOUT"))):
            result = interpret_with_llm("음식이 보이는 장면만", [CAFE, CAKE], completion)
            self.assertEqual(ids(result), [])
            self.assertEqual(result.suggestion.total_seconds, 0)
            self.assertTrue(any("제안하지 않았습니다" in note for note in result.suggestion.notes))

    def test_uncertain_or_negated_visual_caption_does_not_pass_gate(self):
        uncertain = replace(CAKE, visual_caption="케이크일 수 있지만 불확실", visual_tags=("케이크",))
        negated = replace(LATTE, visual_caption="케이크는 보이지 않는다", visual_tags=("케이크",))
        result = interpret_with_llm("음식이 보이는 장면만", [uncertain, negated], engine({
            "interpretation": "음식", "selected_scenes": [1, 2]}))
        self.assertEqual(ids(result), [])

    def test_landscape_visual_gate_keeps_length_limit(self):
        cafe = replace(CAFE, visual_caption="카페 실내")
        sunset = replace(SUNSET, visual_caption="노을이 비치는 풍경", visual_tags=("석양",))
        result = interpret_with_llm("풍경 위주로 감성적으로 20초 이내", [cafe, sunset], engine({
            "interpretation": "감성 풍경", "selected_scenes": [1, 2], "target_seconds": 20,
            "order": "chronological"}))
        self.assertEqual(ids(result), [sunset.candidate_id])
        self.assertLessEqual(result.suggestion.total_seconds, 20)
