"""VLM scene captions: validation, non-authoritative persistence, API, and use by the LLM edit interpreter."""

import json
import time
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.app.models import (SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneCandidate, SceneDiscoveryMethod,
                                SceneEvidence, SceneEvidenceModality, SourceVideo)
from backend.app.services import project_scene_vision
from backend.app.services.llm_edit_interpreter import interpret_with_llm
from backend.app.services.project_scene_candidates import ActiveCandidateSummary
from backend.app.services.vlm_scene_captioner import EVIDENCE_TYPE, CaptionResult, VLMCaptionError, VLMSceneCaption, store_caption
from backend.tests import test_qa03_render_integrity as qa03


def result(caption="잔디밭을 달리는 강아지", tags=("강아지", "잔디")):
    return CaptionResult(VLMSceneCaption(caption=caption, tags=list(tags), place="야외", mood="활기참"), 1.5, (1.1, 1.5, 1.9), "ab" * 32, "gemma3:4b")


class CaptionSchemaTests(TestCase):
    def test_schema_rejects_extra_keys_and_empty_tags(self):
        with self.assertRaises(ValidationError):
            VLMSceneCaption.model_validate({"caption": "카페", "tags": ["카페"], "start_seconds": 3})
        with self.assertRaises(ValidationError):
            VLMSceneCaption.model_validate({"caption": "카페", "tags": [" "]})
        self.assertEqual(VLMSceneCaption.model_validate({"caption": "카페", "tags": ["카페", "카페 "]}).tags, ["카페"])


class SceneVisionApiTests(TestCase):
    setUp = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url

    def wait(self):
        for _ in range(200):
            state = self.client.get(self.url("/scene-vision")).json()
            if state["status"] not in ("QUEUED", "RUNNING"):
                return state
            time.sleep(0.02)
        self.fail("vision run did not finish")

    def test_caption_is_stored_as_non_authoritative_visual_evidence_and_shown(self):
        with self.factory() as session:
            candidate = session.get(SceneCandidate, self.candidate_id)
            before = (float(candidate.start_seconds), float(candidate.end_seconds))
        with patch("backend.app.services.project_scene_vision.caption_interval", return_value=result()) as call, \
             patch.object(type(qa03.app.state.source_storage), "resolve", lambda self, ref: ref):
            self.assertEqual(self.client.post(self.url("/scene-vision")).status_code, 202)
            state = self.wait()
            self.assertEqual((state["status"], state["captioned"], state["failed"]), ("COMPLETED", 1, 0))
            self.assertEqual(call.call_args.args[1:3], before)  # Python passes its own interval to the VLM
            # Re-run is idempotent per model: no second VLM call.
            self.client.post(self.url("/scene-vision")); state = self.wait()
            self.assertEqual((state["skipped"], call.call_count), (1, 1))
        with self.factory() as session:
            rows = session.scalars(select(SceneEvidence).where(SceneEvidence.evidence_type == EVIDENCE_TYPE)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0].modality.value, rows[0].payload["authoritative"], rows[0].source_reference), ("VISUAL", False, "vlm:gemma3:4b:v0.2"))
            candidate = session.get(SceneCandidate, self.candidate_id)
            self.assertEqual((float(candidate.start_seconds), float(candidate.end_seconds)), before)  # interval untouched
        listed = self.client.get(self.url("/scene-candidates")).json()["candidates"][0]
        self.assertEqual((listed["visual_caption"], listed["visual_tags"]), ("잔디밭을 달리는 강아지", ["강아지", "잔디"]))

    def test_vlm_failure_is_reported_without_breaking_the_flow(self):
        with patch("backend.app.services.project_scene_vision.caption_interval", side_effect=VLMCaptionError("VLM_TIMEOUT")), \
             patch.object(type(qa03.app.state.source_storage), "resolve", lambda self, ref: ref):
            self.client.post(self.url("/scene-vision")); state = self.wait()
        self.assertEqual((state["status"], state["failed"], state["error_codes"]), ("COMPLETED_WITH_WARNINGS", 1, ["VLM_TIMEOUT"]))
        self.assertIsNone(self.client.get(self.url("/scene-candidates")).json()["candidates"][0]["visual_caption"])
        self.assertEqual(self.client.post(f"/projects/{uuid4()}/scene-vision").status_code, 404)


class InterpreterUsesVisionTests(TestCase):
    def test_visual_caption_reaches_prompt_and_counts_as_explicit_match(self):
        src = uuid4()
        talk = ActiveCandidateSummary(uuid4(), src, Decimal("0"), Decimal("5"), (), "오늘 날씨 좋네요", "카페 테이블", ("카페",))
        dog = ActiveCandidateSummary(uuid4(), src, Decimal("6"), Decimal("10"), (), "신나게 뛰어노는 모습", "잔디밭을 달리는 개", ("강아지", "잔디"))
        prompts = []
        def complete(system, user, schema):
            prompts.append(user)
            return json.dumps({"interpretation": "x", "selected_scenes": [1, 2]})
        out = interpret_with_llm("강아지 장면만", [talk, dog], ("fake", "m", complete))
        self.assertIn("화면: 잔디밭을 달리는 개 [강아지, 잔디]", prompts[0])
        self.assertEqual([s.candidate_id for s in out.suggestion.scenes], [dog.candidate_id])  # tag match is explicit

    def test_visual_categories_make_broad_requests_deterministic(self):
        src = uuid4()
        latte = ActiveCandidateSummary(uuid4(), src, Decimal("0"), Decimal("4"), (), None, "라떼 아트", ("커피",), ("음료",))
        cake = ActiveCandidateSummary(uuid4(), src, Decimal("5"), Decimal("9"), (), None, "딸기 케이크", ("케이크",), ("음식", "실내"))
        dog = ActiveCandidateSummary(uuid4(), src, Decimal("10"), Decimal("14"), (), None, "풀밭의 개", ("강아지",), ("동물", "자연풍경"))
        wrong_llm = ("fake", "m", lambda s, u, schema: json.dumps({"interpretation": "x", "selected_scenes": [1, 3]}))
        out = interpret_with_llm("음식이 보이는 장면만", [latte, cake, dog], wrong_llm)
        self.assertEqual([s.candidate_id for s in out.suggestion.scenes], [cake.candidate_id])  # LLM's dog/latte picks overridden


class SceneVisionRestartRestoreTests(TestCase):
    """After a restart the in-memory run record is gone; GET must restore the state from stored captions (read-only)."""
    setUp_base = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url
    wait = SceneVisionApiTests.wait

    def setUp(self):
        self.setUp_base()
        restart = patch.dict(project_scene_vision._runs, clear=True)  # simulates a fresh server process
        restart.start(); self.addCleanup(restart.stop)
        no_vlm = patch("backend.app.services.project_scene_vision.caption_interval",
                       side_effect=AssertionError("status restore must not call the VLM"))
        self.vlm = no_vlm.start(); self.addCleanup(no_vlm.stop)

    def store(self, candidate_id, model="gemma3:4b"):
        with self.factory.begin() as session:
            store_caption(session, session.get(SceneCandidate, candidate_id), result())
            if model != "gemma3:4b":
                row = session.scalars(select(SceneEvidence).where(SceneEvidence.scene_candidate_id == candidate_id,
                                                                  SceneEvidence.evidence_type == EVIDENCE_TYPE)).one()
                row.source_reference = f"vlm:{model}:v0.2"

    def add_candidate(self, active=True):
        with self.factory.begin() as session:
            first = session.get(SceneCandidate, self.candidate_id)
            work = session.get(SceneAnalysisWorkItem, first.analysis_work_item_id)
            candidate = SceneCandidate(source_video_id=first.source_video_id, analysis_work_item_id=work.id,
                                       start_seconds=3, end_seconds=4, discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                                       input_fingerprint="source")
            session.add(candidate); session.flush()
            session.add(SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                                      evidence_type="AUDIO_ACTIVITY", payload={}, producer="qa03", producer_version="1",
                                      source_reference="qa03"))
            if active:
                session.add(SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id))
                work.result_reference = "autonomous:candidates:2"
            return candidate.id

    def counts(self):
        with self.factory() as session:
            return session.scalar(select(func.count(SceneEvidence.id))), session.scalar(select(func.count(SceneCandidate.id)))

    def get(self):
        response = self.client.get(self.url("/scene-vision"))
        self.assertEqual(response.status_code, 200)
        state = response.json()
        return state["status"], state["captioned"], state["total"], state["state_source"]

    def test_stored_captions_restore_completed_without_vlm_call_or_db_write(self):
        self.store(self.candidate_id)
        before = self.counts()
        state = self.client.get(self.url("/scene-vision")).json()
        self.assertEqual((state["status"], state["model"], state["captioned"], state["total"], state["skipped"],
                          state["failed"], state["error_codes"], state["state_source"]),
                         ("COMPLETED", "gemma3:4b", 1, 1, 0, 0, [], "DATABASE"))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.vlm.call_count, 0)

    def test_no_caption_stays_not_started(self):
        self.assertEqual(self.get(), ("NOT_STARTED", 0, 1, "DATABASE"))

    def test_some_active_candidates_without_caption_are_partial_not_completed(self):
        self.add_candidate()
        self.store(self.candidate_id)
        self.assertEqual(self.get(), ("PARTIAL", 1, 2, "DATABASE"))

    def test_caption_from_other_model_or_inactive_candidate_does_not_count(self):
        self.store(self.candidate_id, model="llava:7b")
        self.assertEqual(self.get(), ("NOT_STARTED", 0, 1, "DATABASE"))
        stale = self.add_candidate(active=False)
        self.store(stale)
        self.assertEqual(self.get(), ("NOT_STARTED", 0, 1, "DATABASE"))
        with patch.dict("os.environ", {"CUTORY_VLM_MODEL": "llava:7b"}):
            self.assertEqual(self.get(), ("COMPLETED", 1, 1, "DATABASE"))

    def test_restart_then_start_skips_stored_captions_and_process_record_wins(self):
        self.store(self.candidate_id)
        with patch.object(type(qa03.app.state.source_storage), "resolve", lambda self, ref: ref):
            self.assertEqual(self.client.post(self.url("/scene-vision")).status_code, 202)
            state = self.wait()
        self.assertEqual((state["status"], state["skipped"], state["captioned"], state["state_source"]),
                         ("COMPLETED", 1, 0, "PROCESS"))
        self.assertEqual(self.vlm.call_count, 0)

    def test_in_process_failure_is_not_replaced_by_database_state(self):
        project_scene_vision._runs[self.project_id] = project_scene_vision.VisionRun(
            status="FAILED", model="gemma3:4b", total=1, failed=1, error_codes=["VLM_TIMEOUT"])
        state = self.client.get(self.url("/scene-vision")).json()
        self.assertEqual((state["status"], state["failed"], state["state_source"]), ("FAILED", 1, "PROCESS"))

    def test_unknown_project_is_404_and_database_errors_are_not_masked(self):
        self.assertEqual(self.client.get(f"/projects/{uuid4()}/scene-vision").status_code, 404)
        with patch("backend.app.services.project_scene_vision.active_candidate_ids",
                   side_effect=OperationalError("select", {}, Exception("db down"))), \
             self.assertRaises(OperationalError):
            self.client.get(self.url("/scene-vision"))
