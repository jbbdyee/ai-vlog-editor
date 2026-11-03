"""Persistent render API contracts using an isolated synthetic SQLite store."""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectRenderRun, ProjectSceneEditPlan, ProjectSceneEditPlanItem,
    SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus,
    SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)
from backend.app.services.persistent_render_execution import PersistentProjectRenderRunRegistry, utcnow, verified_output
from backend.app.services.project_rendering import ProjectRenderError, ProjectRenderResult


class ManualExecutor:
    def __init__(self): self.operations = []
    def submit(self, operation): self.operations.append(operation)
    def run_next(self): self.operations.pop(0)()


class PersistentRenderApiTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        engine = create_engine(f"sqlite+pysqlite:///{self.root / 'render.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.factory = sessionmaker(bind=engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start(); self.addCleanup(loader.stop)
        context = TestClient(app)
        self.client = context.__enter__(); self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        self.output = self.root / "outputs"
        app.state.project_render_output_root = self.output
        self.executor = ManualExecutor()
        app.state.project_render_run_registry = PersistentProjectRenderRunRegistry(self.executor, self.factory, self.output)
        with self.factory.begin() as session:
            project = Project(name="persistent QA", split_policy=EpisodeSplitPolicy.SINGLE)
            other = Project(name="other", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add_all([project, other]); session.flush()
            self.project_id, self.other_id = project.id, other.id
            source = SourceVideo(project_id=project.id, original_filename="fake.mp4",
                                 storage_reference="private/fake.mp4", duration_seconds=5)
            session.add(source); session.flush()
            work = SceneAnalysisWorkItem(
                project_id=project.id, source_video_id=source.id, work_type="AUTONOMOUS_PROMOTION",
                status=SceneAnalysisWorkStatus.COMPLETED, input_fingerprint="source", producer="test",
                producer_version="1", result_reference="autonomous:candidates:1", result_fingerprint="result",
            )
            session.add(work); session.flush()
            candidate = SceneCandidate(source_video_id=source.id, analysis_work_item_id=work.id,
                                       start_seconds=1, end_seconds=2, discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                                       input_fingerprint="source")
            session.add(candidate); session.flush()
            session.add_all([
                SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                              evidence_type="AUDIO_ACTIVITY", payload={}, producer="test", producer_version="1",
                              source_reference="fake"),
            ])
            plan = ProjectSceneEditPlan(project_id=project.id)
            plan.items = [ProjectSceneEditPlanItem(position=0, candidate_id=candidate.id)]
            session.add(plan)
            self.candidate_id = candidate.id

    def url(self, suffix): return f"/projects/{self.project_id}{suffix}"

    def fake_result(self, **kwargs):
        render_id = kwargs["render_id"]
        self.assertEqual(kwargs["expected_plan_snapshot"][0]["candidate_id"], str(self.candidate_id))
        directory = self.output / "projects" / self.project_id.hex / "renders" / render_id.hex
        directory.mkdir(parents=True, exist_ok=False)
        base = directory / "final.mp4"; base.write_bytes(b"valid synthetic MP4" * 10)
        hard = directory / "final-subtitled.mp4"; hard.write_bytes(b"synthetic hard subtitles" * 10)
        return ProjectRenderResult(self.project_id, render_id, base, (self.candidate_id,), 1.0,
                                   "h264", "aac", base.stat().st_size, hard_subtitle_path=hard)

    def render_once(self):
        with patch("backend.app.routers.projects.render_project_edit_plan", side_effect=self.fake_result):
            response = self.client.post(self.url("/render"))
            self.assertEqual(response.status_code, 202, response.text)
            render_id = response.json()["render_id"]
            self.assertEqual(self.client.get(self.url("/rendering")).json()["status"], "QUEUED")
            self.executor.run_next()
        return render_id

    def test_restart_restores_result_and_range_downloads(self):
        render_id = self.render_once()
        before = self.client.get(self.url("/rendering")).json()
        self.assertEqual(before["status"], "COMPLETED")
        self.assertTrue(before["download_available"])
        app.state.project_render_run_registry = PersistentProjectRenderRunRegistry(ManualExecutor(), self.factory, self.output)
        after = self.client.get(self.url("/rendering")).json()
        self.assertEqual(after["render_id"], render_id)
        self.assertEqual(after["output"]["download_url"], before["output"]["download_url"])
        for suffix in ("download", "subtitled/download"):
            response = self.client.get(self.url(f"/renders/{render_id.replace('-', '')}/{suffix}"),
                                       headers={"Range": "bytes=0-4"})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.headers["content-type"], "video/mp4")
            self.assertEqual(len(response.content), 5)
        history = self.client.get(self.url("/renders")).json()
        self.assertEqual(history["items"][0]["render_id"], render_id)
        with self.factory() as session:
            row = session.get(ProjectRenderRun, UUID(render_id))
            self.assertEqual(row.plan_snapshot[0]["candidate_id"], str(self.candidate_id))
            self.assertFalse(Path(row.base_relpath).is_absolute())

    def test_missing_variants_and_project_mismatch(self):
        render_id = self.render_once(); compact = render_id.replace("-", "")
        base_url = self.url(f"/renders/{compact}/download")
        hard_url = self.url(f"/renders/{compact}/subtitled/download")
        self.assertEqual(self.client.get(f"/projects/{self.other_id}/renders/{compact}/download").status_code, 404)
        self.assertEqual(self.client.get(self.url(f"/renders/{uuid4().hex}/download")).status_code, 404)
        self.assertEqual(self.client.get(self.url("/renders/bad.mp4/download")).status_code, 422)
        directory = self.output / "projects" / self.project_id.hex / "renders" / compact
        (directory / "final-subtitled.mp4").unlink()
        self.assertEqual(self.client.get(hard_url).status_code, 404)
        self.assertEqual(self.client.get(base_url).status_code, 200)
        self.assertEqual(self.client.get(self.url("/rendering")).json()["hard_subtitle_status"], "MISSING")
        (directory / "final.mp4").unlink()
        state = self.client.get(self.url("/rendering")).json()
        self.assertFalse(state["download_available"])
        self.assertEqual(state["safe_error_code"], "RENDER_FILE_MISSING")
        self.assertEqual(self.client.get(base_url).status_code, 404)

    def test_later_failure_preserves_previous_success(self):
        first = self.render_once(); compact = first.replace("-", "")
        with patch("backend.app.routers.projects.render_project_edit_plan",
                   side_effect=ProjectRenderError("CONCAT_FAILED", "private path")):
            self.assertEqual(self.client.post(self.url("/render")).status_code, 202)
            self.executor.run_next()
        current = self.client.get(self.url("/rendering")).json()
        self.assertEqual(current["status"], "FAILED")
        self.assertEqual(current["safe_error_code"], "CONCAT_FAILED")
        self.assertEqual(self.client.get(self.url(f"/renders/{compact}/download")).status_code, 200)
        items = self.client.get(self.url("/renders")).json()["items"]
        self.assertEqual([item["status"] for item in items], ["FAILED", "COMPLETED"])

    def test_missing_srt_after_render_preserves_base_mp4(self):
        def result_without_srt(**kwargs):
            result = self.fake_result(**kwargs)
            missing = result.output_path.parent / "final.srt"
            return ProjectRenderResult(**{**result.__dict__, "subtitle_path": missing})

        with patch("backend.app.routers.projects.render_project_edit_plan", side_effect=result_without_srt):
            response = self.client.post(self.url("/render"))
            self.assertEqual(response.status_code, 202)
            self.executor.run_next()
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertTrue(state["download_available"])
        with self.factory() as session:
            row = session.get(ProjectRenderRun, UUID(response.json()["render_id"]))
            self.assertEqual(row.subtitle_error_code, "SUBTITLE_OUTPUT_INVALID")
            self.assertIsNone(row.srt_relpath)
        compact = response.json()["render_id"].replace("-", "")
        self.assertEqual(self.client.get(self.url(f"/renders/{compact}/download")).status_code, 200)

    def test_duplicate_and_expired_lease(self):
        first = self.client.post(self.url("/render"))
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.client.post(self.url("/render")).status_code, 409)
        render_id = first.json()["render_id"]
        with self.factory.begin() as session:
            row = session.get(ProjectRenderRun, UUID(render_id))
            row.lease_expires_at = utcnow() - timedelta(seconds=100)
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["status"], "INTERRUPTED")
        self.executor.run_next()
        self.assertEqual(self.client.get(self.url("/rendering")).json()["status"], "INTERRUPTED")

    def test_db_completion_failure_cannot_claim_success(self):
        with self.factory().bind.begin() as connection:
            connection.execute(text("CREATE TRIGGER deny_completed BEFORE UPDATE OF status ON project_render_runs "
                                    "WHEN NEW.status = 'COMPLETED' BEGIN SELECT RAISE(FAIL, 'blocked'); END"))
        with patch("backend.app.routers.projects.render_project_edit_plan", side_effect=self.fake_result):
            response = self.client.post(self.url("/render"))
            self.assertEqual(response.status_code, 202)
            self.executor.run_next()
        self.assertNotEqual(self.client.get(self.url("/rendering")).json()["status"], "COMPLETED")

    def test_path_escape_and_size_mismatch(self):
        render_id = uuid4()
        path = self.root / "outside.mp4"; path.write_bytes(b"private")
        expected = f"projects/{self.project_id.hex}/renders/{render_id.hex}/final.mp4"
        self.assertIsNone(verified_output(self.output, self.project_id, render_id, "final.mp4", "../outside.mp4", 7))
        self.assertIsNone(verified_output(self.output, self.project_id, render_id, "final.mp4", expected, 7))
