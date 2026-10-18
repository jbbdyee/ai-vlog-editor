"""Media-free tests for the process-local Project Scene execution boundary."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.audio_extractor import ExtractedAudio
from backend.app.services.autonomous_discovery import (
    AnalysisInterval,
    AnalysisUnitType,
    ModalityAnalysis,
    SignalEvidence,
    process_autonomous_discovery,
)
from backend.app.services.project_scene_execution import ProjectSceneRunRegistry
from backend.app.services.project_scene_processing import (
    ProjectSceneProcessingResult,
    ProjectSceneSourceResult,
    SceneSourceOutcome,
)
from backend.app.services.source_autonomous_adapter import (
    SourceAutonomousServices,
    process_source_autonomous,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace


class _ManualExecutor:
    def __init__(self):
        self.operations = []

    def submit(self, operation):
        self.operations.append(operation)
        return object()

    def run_next(self):
        self.operations.pop(0)()


class _FakeStorage:
    def __init__(self, source_path):
        self.source_path = source_path
        self.references = []

    def resolve(self, reference):
        self.references.append(reference)
        return self.source_path


class ProjectSceneAPITests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = create_engine(
            f"sqlite+pysqlite:///{self.root / 'scene-api.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.source_path = self.root / "synthetic.mov"
        self.source_path.write_bytes(b"fake source, never decoded")
        self.storage = _FakeStorage(self.source_path)
        self.executor = _ManualExecutor()
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start()
        self.addCleanup(loader.stop)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        app.state.source_storage = self.storage
        app.state.scene_processing_workspace = LocalProcessingWorkspace(self.root / "scene-temp")
        app.state.project_scene_run_registry = ProjectSceneRunRegistry(self.executor)
        with self.factory() as session:
            self.project_id = self._project(session)

    def _project(self, session):
        project = Project(name="Scene API", split_policy=EpisodeSplitPolicy.SINGLE, status=ProjectStatus.COMPLETED)
        session.add(project)
        session.commit()
        return project.id

    def _source(self, project_id=None, *, completed=True, text="우와", malformed=False):
        with self.factory() as session:
            source = SourceVideo(
                project_id=project_id or self.project_id,
                original_filename="synthetic.mov",
                storage_reference=f"private/{uuid4().hex}.mov",
                fingerprint=uuid4().hex,
                fingerprint_algorithm="sha256",
                duration_seconds=30,
                processing_status=SourceVideoStatus.COMPLETED if completed else SourceVideoStatus.READY,
            )
            if completed:
                source.transcript = Transcript(
                    text=text, language="ko",
                    segments="invalid" if malformed else [{"start_seconds": 4, "end_seconds": 8, "text": text, "words": []}],
                )
            source.processing_stages.extend(
                ProcessingStage(
                    stage=kind,
                    status=ProcessingStageStatus.COMPLETED if completed else ProcessingStageStatus.PENDING,
                )
                for kind in ProcessingStageKind
            )
            session.add(source)
            session.commit()
            return source.id

    def _services(self, *, abstain_ids=(), fail_ids=(), calls=None):
        calls = calls if calls is not None else []

        def extract(source_path, directory):
            wav = directory / "fake.wav"
            wav.write_bytes(b"fake wav")
            return ExtractedAudio(source_path, wav, 30, 16_000, 1, "pcm_s16le")

        def audio(path, *, source_video_id, **_kwargs):
            calls.append(source_video_id)
            self.assertTrue(path.exists())
            if source_video_id in fail_ids:
                raise RuntimeError("private failure")
            if source_video_id in abstain_ids:
                return ModalityAnalysis(())
            return ModalityAnalysis((SignalEvidence(
                AnalysisInterval(source_video_id, 4, 8, AnalysisUnitType.AUDIO_ACTIVITY, "fake", "1"),
                modality=SceneEvidenceModality.AUDIO,
                evidence_type="AUDIO_ACTIVITY", payload={"measurement": 1},
            ),))

        def visual(_path, *, source_video_id, **_kwargs):
            if source_video_id in fail_ids:
                raise RuntimeError("private visual failure")
            return ModalityAnalysis(())

        return SourceAutonomousServices(extract=extract, analyze_audio=audio, analyze_visual=visual)

    def _run_with_fake_media(self, *, abstain_ids=(), fail_ids=(), calls=None):
        real_adapter = process_source_autonomous
        services = self._services(abstain_ids=abstain_ids, fail_ids=fail_ids, calls=calls)

        def invoke(**kwargs):
            return real_adapter(**kwargs, services=services)

        with patch("backend.app.services.project_scene_processing.process_source_autonomous", side_effect=invoke):
            self.executor.run_next()

    def _post(self, project_id=None):
        return self.client.post(f"/projects/{project_id or self.project_id}/scene-process")

    def _status(self, project_id=None):
        return self.client.get(f"/projects/{project_id or self.project_id}/scene-processing")

    def test_multiple_sources_candidate_evidence_and_existing_api(self):
        first = self._source()
        second = self._source()
        other_project_id = self._other_project()
        other = self._source(other_project_id)
        queued = self._post()
        self.assertEqual(queued.status_code, 202)
        self.assertEqual(queued.json()["status_url"], f"/projects/{self.project_id}/scene-processing")
        self.assertEqual(self._status().json()["run_status"], "QUEUED")
        self._run_with_fake_media()
        status = self._status().json()
        self.assertEqual(status["run_status"], "COMPLETED")
        self.assertEqual((status["total_sources"], status["completed_count"]), (2, 2))
        self.assertEqual({row["source_video_id"] for row in status["sources"]}, {str(first), str(second)})
        candidates = self.client.get(f"/projects/{self.project_id}/scene-candidates").json()["candidates"]
        self.assertEqual({row["source_video_id"] for row in candidates}, {str(first), str(second)})
        self.assertTrue(all(row["evidence"] for row in candidates))
        self.assertNotIn(str(other), str(candidates))
        self.assertEqual(
            self.client.get(f"/projects/{other_project_id}/scene-candidates").json()["candidates"],
            [],
        )
        with self.factory() as session:
            self.assertEqual(session.query(SceneCandidate).count(), 2)
            self.assertGreater(session.query(SceneEvidence).count(), 0)
            self.assertEqual(session.get(Project, self.project_id).status, ProjectStatus.COMPLETED)
            self.assertEqual(session.get(SourceVideo, first).processing_status, SourceVideoStatus.COMPLETED)

    def test_v1_incomplete_source_is_skipped_without_analysis(self):
        complete = self._source()
        incomplete = self._source(completed=False)
        calls = []
        self.assertEqual(self._post().status_code, 202)
        self._run_with_fake_media(calls=calls)
        status = self._status().json()
        self.assertEqual(calls, [complete])
        self.assertEqual(status["run_status"], "COMPLETED_WITH_WARNINGS")
        self.assertEqual(status["skipped_count"], 1)
        self.assertEqual({row["source_video_id"]: row["status"] for row in status["sources"]}[str(incomplete)], "SKIPPED_V1_INCOMPLETE")
        with self.factory() as session:
            self.assertEqual(session.get(SourceVideo, incomplete).processing_status, SourceVideoStatus.READY)

    def test_normal_abstain_has_no_candidate(self):
        source_id = self._source()
        self._post()
        self._run_with_fake_media(abstain_ids=(source_id,))
        status = self._status().json()
        self.assertEqual((status["run_status"], status["abstained_count"]), ("COMPLETED", 1))
        self.assertEqual(status["sources"][0]["candidate_count"], 0)
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/scene-candidates").json()["candidates"], [])

    def _diagnostics(self, project_id=None):
        return self.client.get(f"/projects/{project_id or self.project_id}/scene-diagnostics")

    def _controlled_diagnosis(self, *, transcript=True, audio=(), visual=(), audio_fails=False):
        source_id = self._source(text="ordinary speech")
        if not transcript:
            with self.factory() as session:
                source = session.get(SourceVideo, source_id)
                source.transcript.segments = []
                session.commit()

        def facts(modality, intervals):
            unit = AnalysisUnitType.AUDIO_ACTIVITY if modality is SceneEvidenceModality.AUDIO else AnalysisUnitType.VISUAL_ACTIVITY
            return ModalityAnalysis(tuple(SignalEvidence(
                AnalysisInterval(source_id, start, end, unit, "fake", "1"),
                modality=modality,
                evidence_type="AUDIO_ACTIVITY" if modality is SceneEvidenceModality.AUDIO else "VISUAL_ACTIVITY",
                payload={},
            ) for start, end in intervals))

        def audio_analyzer():
            if audio_fails:
                raise RuntimeError("private analyzer error")
            return facts(SceneEvidenceModality.AUDIO, audio)

        with self.factory() as session:
            process_autonomous_discovery(
                session, source_id, audio_analyzer=audio_analyzer,
                visual_analyzer=lambda: facts(SceneEvidenceModality.VISUAL, visual),
            )
        response = self._diagnostics()
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.json()["sources"] if item["source_video_id"] == str(source_id))
        self.assertNotIn("private", str(row))
        return source_id, row

    def test_diagnostics_zero_and_single_modality(self):
        for transcript, audio, visual, expected in (
            (False, (), (), "NO_EVIDENCE"),
            (True, (), (), "SINGLE_MODALITY"),
            (False, ((4, 8),), (), "SINGLE_MODALITY"),
            (False, (), ((4, 8),), "SINGLE_MODALITY"),
        ):
            with self.subTest(reason=expected, transcript=transcript, audio=audio, visual=visual):
                _, row = self._controlled_diagnosis(transcript=transcript, audio=audio, visual=visual)
                self.assertEqual((row["status"], row["candidate_count"], row["abstain_reason"]),
                                 ("ABSTAINED", 0, expected))

    def test_diagnostics_unsupported_nonoverlap_candidate_and_partial_failure(self):
        _, unsupported = self._controlled_diagnosis(visual=((4, 8),))
        self.assertEqual(unsupported["abstain_reason"], "UNSUPPORTED_COMBINATION")
        _, nonoverlap = self._controlled_diagnosis(audio=((10, 12),))
        self.assertEqual(nonoverlap["abstain_reason"], "NO_TEMPORAL_OVERLAP")
        source_id, created = self._controlled_diagnosis(audio=((4, 8),))
        self.assertEqual((created["status"], created["candidate_count"], created["abstain_reason"]),
                         ("COMPLETED", 1, None))
        self.assertEqual(created["evidence_counts"]["TRANSCRIPT"], 1)
        self.assertEqual(created["evidence_counts"]["AUDIO"], 1)
        self.assertEqual(created["evidence_intervals"][0]["start_seconds"], 4)
        self.assertIn(str(source_id), str(self.client.get(f"/projects/{self.project_id}/scene-candidates").json()))
        _, visual_pair = self._controlled_diagnosis(transcript=False, audio=((4, 8),), visual=((5, 7),))
        self.assertEqual((visual_pair["status"], visual_pair["candidate_count"]), ("COMPLETED", 1))
        _, partial = self._controlled_diagnosis(audio_fails=True)
        self.assertEqual(partial["abstain_reason"], "PARTIAL_ANALYZER_FAILURE")
        self.assertIsNone(partial["evidence_counts"]["AUDIO"])
        self.assertTrue(partial["warnings"])

    def test_diagnostics_missing_record_project_isolation_and_restart(self):
        source_id = self._source()
        other_project = self._other_project()
        other_source = self._source(other_project)
        response = self._diagnostics()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"][0]["source_video_id"], str(source_id))
        self.assertEqual(response.json()["sources"][0]["status"], "NOT_ANALYZED")
        self.assertIsNone(response.json()["sources"][0]["candidate_count"])
        self.assertNotIn(str(other_source), str(response.json()))
        self.assertEqual(self._diagnostics(uuid4()).status_code, 404)
        self.assertEqual(self._diagnostics(other_project).json()["sources"][0]["source_video_id"], str(other_source))
        diagnosed_source, row = self._controlled_diagnosis(audio=((4, 8),))
        app.state.project_scene_run_registry = ProjectSceneRunRegistry(_ManualExecutor())
        self.assertEqual(self._status().json()["run_status"], "NOT_STARTED")
        persisted = next(item for item in self._diagnostics().json()["sources"]
                         if item["source_video_id"] == str(diagnosed_source))
        self.assertEqual(persisted["candidate_count"], row["candidate_count"])

    def test_diagnostics_incomplete_history_is_unknown_and_candidate_api_unchanged(self):
        source_id, _ = self._controlled_diagnosis(audio=((4, 8),))
        before = self.client.get(f"/projects/{self.project_id}/scene-candidates").json()
        with self.factory() as session:
            audio_work = session.scalar(select(SceneAnalysisWorkItem).where(
                SceneAnalysisWorkItem.source_video_id == source_id,
                SceneAnalysisWorkItem.work_type == "AUDIO_EVIDENCE",
            ))
            audio_work.result_reference = "legacy:evidence-count:1"
            session.commit()
        diagnostic = next(item for item in self._diagnostics().json()["sources"]
                          if item["source_video_id"] == str(source_id))
        self.assertEqual(diagnostic["abstain_reason"], None)  # Candidate exists; no abstention diagnosis.
        self.assertIsNone(diagnostic["evidence_counts"]["AUDIO"])
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/scene-candidates").json(), before)
        abstained_source, _ = self._controlled_diagnosis()
        with self.factory() as session:
            audio_work = session.scalar(select(SceneAnalysisWorkItem).where(
                SceneAnalysisWorkItem.source_video_id == abstained_source,
                SceneAnalysisWorkItem.work_type == "AUDIO_EVIDENCE",
            ))
            audio_work.result_reference = "legacy:evidence-count:0"
            session.commit()
        incomplete = next(item for item in self._diagnostics().json()["sources"]
                          if item["source_video_id"] == str(abstained_source))
        self.assertEqual(incomplete["abstain_reason"], "UNKNOWN")

    def test_one_source_failure_does_not_remove_other_candidates(self):
        good = self._source()
        failing = self._source(malformed=True)
        self._post()
        self._run_with_fake_media(fail_ids=(failing,))
        status = self._status().json()
        self.assertEqual(status["run_status"], "COMPLETED_WITH_WARNINGS")
        self.assertEqual((status["completed_count"], status["failed_count"]), (1, 1))
        self.assertEqual({row["source_video_id"] for row in self.client.get(f"/projects/{self.project_id}/scene-candidates").json()["candidates"]}, {str(good)})
        self.assertNotIn("private", str(status))
        with self.factory() as session:
            self.assertEqual(session.get(SourceVideo, failing).processing_status, SourceVideoStatus.COMPLETED)

    def test_duplicate_run_and_failed_scene_work_do_not_auto_retry(self):
        source_id = self._source()
        first = self._post()
        duplicate = self._post()
        self.assertEqual((first.status_code, duplicate.status_code), (202, 409))
        self.assertEqual(duplicate.json()["detail"]["code"], "PROJECT_SCENE_PROCESSING_ALREADY_ACTIVE")
        self._run_with_fake_media(fail_ids=(source_id,))
        with self.factory() as session:
            self.assertTrue(any(work.status is SceneAnalysisWorkStatus.FAILED for work in session.scalars(select(SceneAnalysisWorkItem))))
        self.assertEqual(self._post().status_code, 202)
        self._run_with_fake_media()
        self.assertEqual(self._status().json()["sources"][0]["safe_error_code"], "SCENE_RETRY_REQUIRED")

    def test_project_rerun_reuses_candidates_without_media_analysis(self):
        source_id = self._source()
        calls = []
        self._post()
        self._run_with_fake_media(calls=calls)
        with self.factory() as session:
            original_work_count = session.query(SceneAnalysisWorkItem).count()
            original_candidate_count = session.query(SceneCandidate).count()
        self.assertEqual(self._post().status_code, 202)
        self._run_with_fake_media(calls=calls)
        self.assertEqual(calls, [source_id])
        with self.factory() as session:
            self.assertEqual(session.query(SceneAnalysisWorkItem).count(), original_work_count)
            self.assertEqual(session.query(SceneCandidate).count(), original_candidate_count)

    def test_status_is_visible_during_source_processing(self):
        source_id = self._source()
        self.assertEqual(self._post().status_code, 202)

        def fake_project_run(*, on_source_result, **_kwargs):
            before = self._status().json()
            self.assertEqual((before["run_status"], before["processed_count"]), ("RUNNING", 0))
            item = ProjectSceneSourceResult(source_id, SceneSourceOutcome.ABSTAINED)
            on_source_result(item)
            progress = self._status().json()
            self.assertEqual((progress["run_status"], progress["processed_count"]), ("RUNNING", 1))
            return ProjectSceneProcessingResult(self.project_id, (item,))

        with patch("backend.app.routers.projects.process_project_scenes", side_effect=fake_project_run):
            self.executor.run_next()
        self.assertEqual(self._status().json()["run_status"], "COMPLETED")

    def test_missing_project_and_before_first_run(self):
        self.assertEqual(self._post(uuid4()).status_code, 404)
        self.assertEqual(self._status(uuid4()).status_code, 404)
        self.assertEqual(self._status().json()["run_status"], "NOT_STARTED")

    def test_process_restart_loses_run_snapshot_but_not_candidate_data(self):
        self._source()
        self._post()
        self._run_with_fake_media()
        self.assertEqual(self._status().json()["run_status"], "COMPLETED")
        app.state.project_scene_run_registry = ProjectSceneRunRegistry(_ManualExecutor())
        self.assertEqual(self._status().json()["run_status"], "NOT_STARTED")
        self.assertEqual(
            len(self.client.get(f"/projects/{self.project_id}/scene-candidates").json()["candidates"]),
            1,
        )

    def test_start_failure_and_unavailable_database_are_safe(self):
        class BrokenRegistry:
            def start(self, *_args):
                raise RuntimeError("private executor path")

        app.state.project_scene_run_registry = BrokenRegistry()
        failed = self._post()
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["detail"]["code"], "PROJECT_SCENE_PROCESSING_START_FAILED")
        self.assertNotIn("private", failed.text)
        app.state.project_session_factory = None
        self.assertEqual(self._post().status_code, 503)

    def test_worker_unexpected_failure_has_safe_terminal_status(self):
        self._source()
        self.assertEqual(self._post().status_code, 202)
        with patch("backend.app.routers.projects.process_project_scenes", side_effect=RuntimeError("private worker detail")):
            self.executor.run_next()
        response = self._status().json()
        self.assertEqual((response["run_status"], response["safe_error_code"]), ("FAILED", "PROJECT_SCENE_RUN_FAILED"))
        self.assertNotIn("private", str(response))

    def _other_project(self):
        with self.factory() as session:
            return self._project(session)
