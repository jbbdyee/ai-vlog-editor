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
