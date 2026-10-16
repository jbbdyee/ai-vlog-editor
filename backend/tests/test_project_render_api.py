"""Media-free API tests for process-local Project rendering and safe downloads."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectSceneEditPlan, ProjectSceneEditPlanItem,
    SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus,
    SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)
from backend.app.services.project_render_execution import ProjectRenderRunRegistry
from backend.app.services.project_rendering import ProjectRenderError, ProjectRenderResult


class _ManualExecutor:
    def __init__(self):
        self.operations = []

    def submit(self, operation):
        self.operations.append(operation)
        return object()

    def run_next(self):
        self.operations.pop(0)()


class ProjectRenderApiTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = create_engine(
            f"sqlite+pysqlite:///{self.root / 'api.db'}", connect_args={"check_same_thread": False}
        )
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
        self.output_root = self.root / "outputs"
        app.state.project_render_output_root = self.output_root
        self.executor = _ManualExecutor()
        app.state.project_render_run_registry = ProjectRenderRunRegistry(self.executor)
        with self.factory() as session:
            project = Project(name="render API", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project)
            session.commit()
            self.project_id = project.id

    def _candidate(self):
        with self.factory() as session:
            source = SourceVideo(project_id=self.project_id, original_filename="fake.mp4",
                                 storage_reference="private/fake.mp4", duration_seconds=5)
            session.add(source)
            session.flush()
            work = SceneAnalysisWorkItem(
                project_id=self.project_id, source_video_id=source.id, work_type="AUTONOMOUS_PROMOTION",
                status=SceneAnalysisWorkStatus.COMPLETED, input_fingerprint="source", producer="test",
                producer_version="1", result_reference="autonomous:candidates:1", result_fingerprint="result",
            )
            session.add(work)
            session.flush()
            candidate = SceneCandidate(
                source_video_id=source.id, analysis_work_item_id=work.id,
                start_seconds=1, end_seconds=2, discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                input_fingerprint="source",
            )
            session.add(candidate)
            session.flush()
            session.add_all([
                SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                              evidence_type="AUDIO_ACTIVITY", payload={}, producer="test",
                              producer_version="1", source_reference="fake"),
            ])
            plan = ProjectSceneEditPlan(project_id=self.project_id)
            plan.items = [ProjectSceneEditPlanItem(position=0, candidate_id=candidate.id)]
            session.add(plan)
            session.commit()
            return candidate.id, work.id

    def _url(self):
        return f"/projects/{self.project_id}"

    def _result(self, *, create_file=True):
        render_id = uuid4()
        path = self.output_root / "projects" / self.project_id.hex / "renders" / render_id.hex / "final.mp4"
        if create_file:
            path.parent.mkdir(parents=True)
            path.write_bytes(b"synthetic MP4 bytes")
        return ProjectRenderResult(self.project_id, render_id, path, (), 1.0, "h264", "aac", 19)

    def test_accept_running_success_and_download(self):
        self._candidate()
        result = self._result()
        observed_running = []
        def render_operation(**_kwargs):
            observed_running.append(self.client.get(self._url() + "/rendering").json()["status"])
            return result
        with patch("backend.app.routers.projects.render_project_edit_plan", side_effect=render_operation) as render:
            accepted = self.client.post(self._url() + "/render")
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(accepted.json()["accepted"])
            self.assertEqual(accepted.json()["status_url"], self._url() + "/rendering")
            queued = self.client.get(self._url() + "/rendering").json()
            self.assertEqual(queued["status"], "QUEUED")
            self.assertTrue(queued["is_active"])
            self.assertIsNone(queued["render_id"])
            self.assertFalse(queued["download_available"])
            self.executor.run_next()
            render.assert_called_once()
        self.assertEqual(observed_running, ["RUNNING"])
        completed = self.client.get(self._url() + "/rendering").json()
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertTrue(completed["succeeded"])
        self.assertTrue(completed["download_available"])
        self.assertNotIn(str(self.root), repr(completed))
        self.assertEqual(completed["render_id"], str(result.render_id))
        download = self.client.get(completed["output"]["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["content-type"], "video/mp4")
        self.assertEqual(download.content, b"synthetic MP4 bytes")

    def test_duplicate_active_request_is_blocked(self):
        self._candidate()
        first = self.client.post(self._url() + "/render")
        second = self.client.post(self._url() + "/render")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"]["code"], "RENDER_ALREADY_ACTIVE")
        self.assertEqual(len(self.executor.operations), 1)
        self.assertEqual(self.client.get(self._url() + f"/renders/{uuid4().hex}/download").status_code, 409)

    def test_engine_failure_has_safe_status(self):
        self._candidate()
        with patch("backend.app.routers.projects.render_project_edit_plan",
                   side_effect=ProjectRenderError("CONCAT_FAILED", "private path")):
            self.assertEqual(self.client.post(self._url() + "/render").status_code, 202)
            self.executor.run_next()
        status = self.client.get(self._url() + "/rendering").json()
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["safe_error_code"], "CONCAT_FAILED")
        self.assertFalse(status["download_available"])
        self.assertNotIn("private path", repr(status))
        self.assertEqual(self.client.get(self._url() + f"/renders/{uuid4().hex}/download").status_code, 409)

    def test_empty_plan_invalid_candidate_and_missing_project(self):
        empty = self.client.post(self._url() + "/render")
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(empty.json()["detail"]["code"], "EMPTY_EDIT_PLAN")
        self.assertEqual(len(self.executor.operations), 0)
        _, work_id = self._candidate()
        with self.factory() as session:
            session.get(SceneAnalysisWorkItem, work_id).status = SceneAnalysisWorkStatus.FAILED
            session.commit()
        stale = self.client.post(self._url() + "/render")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["code"], "PLAN_CANDIDATE_CONFLICT")
        self.assertEqual(self.client.post(f"/projects/{uuid4()}/render").status_code, 404)

    def test_missing_file_foreign_render_id_and_traversal(self):
        self._candidate()
        result = self._result(create_file=False)
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            self.client.post(self._url() + "/render")
            self.executor.run_next()
        status = self.client.get(self._url() + "/rendering").json()
        self.assertEqual(status["status"], "COMPLETED")
        self.assertFalse(status["download_available"])
        self.assertEqual(self.client.get(self._url() + f"/renders/{result.render_id.hex}/download").status_code, 404)
        with self.factory() as session:
            other_project = Project(name="other", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(other_project)
            session.commit()
            other = other_project.id
        self.assertEqual(self.client.get(f"/projects/{other}/renders/{result.render_id.hex}/download").status_code, 404)
        self.assertEqual(self.client.get(self._url() + f"/renders/{uuid4().hex}/download").status_code, 404)
        for fragment in ("..%2F.env", "..%5C.env", f"{result.render_id.hex}%2F..", "bad.mp4"):
            response = self.client.get(self._url() + f"/renders/{fragment}/download")
            self.assertEqual(response.status_code, 422)

    def test_symlink_escape_and_restart_do_not_trust_file_alone(self):
        self._candidate()
        result = self._result(create_file=False)
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"private")
        result.output_path.parent.mkdir(parents=True)
        result.output_path.symlink_to(outside)
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            self.client.post(self._url() + "/render")
            self.executor.run_next()
        self.assertFalse(self.client.get(self._url() + "/rendering").json()["download_available"])
        self.assertEqual(self.client.get(self._url() + f"/renders/{result.render_id.hex}/download").status_code, 404)
        result.output_path.unlink()
        result.output_path.write_bytes(b"retained final")
        app.state.project_render_run_registry = ProjectRenderRunRegistry(_ManualExecutor())
        self.assertEqual(self.client.get(self._url() + "/rendering").json()["status"], "NOT_STARTED")
        self.assertEqual(self.client.get(self._url() + f"/renders/{result.render_id.hex}/download").status_code, 404)
        self.assertEqual(result.output_path.read_bytes(), b"retained final")

    def test_completed_result_remains_downloadable_during_next_run(self):
        self._candidate()
        result = self._result()
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            self.client.post(self._url() + "/render")
            self.executor.run_next()
            self.client.post(self._url() + "/render")
            self.assertEqual(self.client.get(self._url() + f"/renders/{result.render_id.hex}/download").status_code, 200)

    def test_executor_submission_failure_is_safe_and_not_marked_running(self):
        self._candidate()
        class FailingExecutor:
            def submit(self, _operation):
                raise RuntimeError("private executor detail")
        app.state.project_render_run_registry = ProjectRenderRunRegistry(FailingExecutor())
        response = self.client.post(self._url() + "/render")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["code"], "RENDER_START_FAILED")
        self.assertNotIn("private executor detail", response.text)
        self.assertEqual(self.client.get(self._url() + "/rendering").json()["status"], "NOT_STARTED")
