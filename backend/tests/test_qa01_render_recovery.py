"""QA-01 isolated PostgreSQL render state scenarios.

Run only with QA01_POSTGRES_URL pointing at a disposable database on the
isolated PostgreSQL instance. Never point this at the current Cutory DB.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import TestCase
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectRenderRun, ProjectSceneEditPlan,
    ProjectSceneEditPlanItem, SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate,
    SceneAnalysisWorkStatus, SceneCandidate, SceneDiscoveryMethod, SceneEvidence,
    SceneEvidenceModality, SourceVideo,
)
from backend.app.services.persistent_render_execution import (
    PersistentProjectRenderRunRegistry, utcnow,
)
from backend.app.services.project_rendering import ProjectRenderError, ProjectRenderResult
from backend.app.services.project_scene_edit_plan import get_scene_edit_plan


class ManualExecutor:
    def __init__(self):
        self.operations = []

    def submit(self, operation):
        self.operations.append(operation)

    def run_next(self):
        self.operations.pop(0)()


class IsolatedPostgresRenderTests(TestCase):
    def setUp(self):
        url = os.getenv("QA01_POSTGRES_URL")
        if not url or "55432" not in url or "cutory_qa01_" not in url:
            self.skipTest("Disposable QA-01 PostgreSQL URL is required.")
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "outputs"
        self.engine = create_engine(url)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.executor_a, self.executor_b = ManualExecutor(), ManualExecutor()
        self.a = PersistentProjectRenderRunRegistry(self.executor_a, self.factory, self.root)
        self.b = PersistentProjectRenderRunRegistry(self.executor_b, self.factory, self.root)
        self.projects = []
        with self.factory.begin() as session:
            for index in range(2):
                project = Project(name=f"QA-01 {index}", split_policy=EpisodeSplitPolicy.SINGLE)
                session.add(project); session.flush()
                source = SourceVideo(project_id=project.id, original_filename="mock.mp4",
                                     storage_reference=f"qa01/{index}.mp4", duration_seconds=5)
                session.add(source); session.flush()
                work = SceneAnalysisWorkItem(
                    project_id=project.id, source_video_id=source.id, work_type="AUTONOMOUS_PROMOTION",
                    status=SceneAnalysisWorkStatus.COMPLETED, input_fingerprint="source", producer="qa01",
                    producer_version="1", result_reference="autonomous:candidates:1", result_fingerprint="result")
                session.add(work); session.flush()
                candidate = SceneCandidate(source_video_id=source.id, analysis_work_item_id=work.id,
                                           start_seconds=1, end_seconds=2,
                                           discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                                           input_fingerprint="source")
                session.add(candidate); session.flush()
                session.add_all([
                    SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                    SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                                  evidence_type="AUDIO_ACTIVITY", payload={}, producer="qa01",
                                  producer_version="1", source_reference="qa01"),
                ])
                plan = ProjectSceneEditPlan(project_id=project.id)
                plan.items = [ProjectSceneEditPlanItem(position=0, candidate_id=candidate.id)]
                session.add(plan)
                self.projects.append((project.id, candidate.id))

    def result(self, project_id, candidate_id, render_id):
        directory = self.root / "projects" / project_id.hex / "renders" / render_id.hex
        directory.mkdir(parents=True, exist_ok=False)
        base = directory / "final.mp4"
        base.write_bytes(b"synthetic QA-01 bytes" * 20)
        return ProjectRenderResult(project_id, render_id, base, (candidate_id,), 1.0,
                                   "h264", "aac", base.stat().st_size)

    def test_project_scoped_admission_retry_recovery_and_file_loss(self):
        first, second = self.projects
        with self.factory() as session:
            self.assertEqual(get_scene_edit_plan(session, first[0]).invalid_candidate_ids, ())
            self.assertEqual(get_scene_edit_plan(session, second[0]).invalid_candidate_ids, ())
        barrier = Barrier(2)

        def admit(registry):
            barrier.wait()
            return registry.start(first[0], lambda rid, snapshot: self.result(first[0], first[1], rid))

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(admit, (self.a, self.b)))
        self.assertEqual(sum(value is not None for value in attempts), 1)
        winner = self.a if self.executor_a.operations else self.b
        other = self.b if winner is self.a else self.a
        self.assertEqual(winner.snapshot(first[0]).status.value, "QUEUED")
        independent = other.start(second[0], lambda rid, snapshot: self.result(second[0], second[1], rid))
        self.assertIsNotNone(independent)
        self.assertEqual(other.snapshot(second[0]).status.value, "QUEUED")
        (self.executor_b if other is self.b else self.executor_a).run_next()
        self.assertEqual(self.a.snapshot(second[0]).status.value, "COMPLETED")

        active_id = next(value for value in attempts if value is not None)
        with self.factory.begin() as session:
            session.get(ProjectRenderRun, active_id).lease_expires_at = utcnow() - timedelta(seconds=100)
        self.assertEqual(winner.snapshot(first[0]).status.value, "QUEUED")
        (self.executor_a if winner is self.a else self.executor_b).run_next()
        self.assertEqual(self.a.snapshot(first[0]).status.value, "COMPLETED")
        self.assertEqual(self.b.completed_result(first[0], active_id).render_id, active_id)

        failed_id = self.a.start(first[0], lambda rid, snapshot: (_ for _ in ()).throw(
            ProjectRenderError("QA01_FAILURE", "synthetic failure")))
        self.executor_a.run_next()
        self.assertEqual(self.a.snapshot(first[0]).status.value, "FAILED")
        self.assertNotEqual(active_id, failed_id)
        self.assertIsNotNone(self.a.completed_result(first[0], active_id))
        retry_id = self.a.start(first[0], lambda rid, snapshot: self.result(first[0], first[1], rid))
        self.assertNotIn(retry_id, (active_id, failed_id))
        self.executor_a.run_next()
        self.assertEqual(self.b.snapshot(first[0]).render_id, retry_id)
        self.assertEqual([item.status.value for item in self.b.history(first[0])[0]][:3],
                         ["COMPLETED", "FAILED", "COMPLETED"])

        file = self.root / "projects" / first[0].hex / "renders" / active_id.hex / "final.mp4"
        file.unlink()
        self.assertFalse(file.exists())
        app.state.project_session_factory = self.factory
        app.state.project_render_run_registry = self.b
        app.state.project_render_output_root = self.root
        client = TestClient(app)
        missing = client.get(f"/projects/{first[0]}/renders/{active_id.hex}/download")
        self.assertEqual(missing.status_code, 404)
        history = client.get(f"/projects/{first[0]}/renders").json()["items"]
        self.assertEqual([item["status"] for item in history[:3]],
                         ["COMPLETED", "FAILED", "COMPLETED"])
        self.assertFalse(history[2]["download_available"])
        self.assertEqual(history[2]["safe_error_code"], "RENDER_FILE_MISSING")
        with self.factory.begin() as session:
            empty = Project(name="QA-01 no saved plan", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(empty); session.flush()
            empty_id = empty.id
        no_plan = client.post(f"/projects/{empty_id}/render")
        self.assertEqual(no_plan.status_code, 422)
        self.assertEqual(no_plan.json()["detail"]["code"], "EMPTY_EDIT_PLAN")
        with self.factory() as session:
            rows = session.scalars(select(ProjectRenderRun).where(
                ProjectRenderRun.project_id == first[0])).all()
            self.assertEqual(len(rows), 3)

    def test_ownerless_expired_rows_are_interrupted_or_reconciled(self):
        project_id, candidate_id = self.projects[0]
        old = utcnow() - timedelta(seconds=200)
        with self.factory.begin() as session:
            first = ProjectRenderRun(
                render_id=uuid4(), project_id=project_id, status="RUNNING",
                plan_snapshot=[{"candidate_id": str(candidate_id)}],
                plan_fingerprint="qa01", created_at=old, started_at=old,
                owner_token=uuid4(), heartbeat_at=old, lease_expires_at=old,
            )
            session.add(first)
        self.assertEqual(self.b.snapshot(project_id).status.value, "INTERRUPTED")
        with self.factory() as session:
            row = session.get(ProjectRenderRun, first.render_id)
            self.assertEqual(row.safe_error_code, "RENDER_WORKER_INTERRUPTED")
        second_id = self.a.start(project_id, lambda rid, snapshot: self.result(project_id, candidate_id, rid))
        self.executor_a.run_next()
        self.assertEqual(self.b.snapshot(project_id).render_id, second_id)
        with self.factory.begin() as session:
            partial = ProjectRenderRun(
                render_id=uuid4(), project_id=project_id, status="QUEUED",
                plan_snapshot=[{"candidate_id": str(candidate_id)}],
                plan_fingerprint="qa01", created_at=utcnow(),
                owner_token=uuid4(), heartbeat_at=old, lease_expires_at=old,
            )
            session.add(partial)
        path = self.root / "projects" / project_id.hex / "renders" / partial.render_id.hex
        path.mkdir(parents=True)
        (path / "final.mp4").write_bytes(b"partial mock output")
        self.assertEqual(self.a.snapshot(project_id).status.value, "RECONCILIATION_REQUIRED")
        with self.factory() as session:
            row = session.get(ProjectRenderRun, partial.render_id)
            self.assertEqual(row.safe_error_code, "RENDER_RECOVERY_REQUIRED")
        self.assertIsNotNone(self.b.completed_result(project_id, second_id))

    def test_same_size_corruption_should_disable_download(self):
        """QA-01 gap resolved by QA-03: the completion-time SHA-256 blocks same-size rewrites.

        Until QA-03 this was an expectedFailure whose first assertion recorded the
        defective 200 response; it now asserts the blocked 409 contract instead.
        """
        project_id, candidate_id = self.projects[0]
        render_id = self.a.start(project_id, lambda rid, snapshot: self.result(project_id, candidate_id, rid))
        self.executor_a.run_next()
        file = self.root / "projects" / project_id.hex / "renders" / render_id.hex / "final.mp4"
        original = file.read_bytes()
        file.write_bytes(b"X" * len(original))
        app.state.project_session_factory = self.factory
        app.state.project_render_run_registry = self.b
        app.state.project_render_output_root = self.root
        client = TestClient(app)
        blocked = client.get(f"/projects/{project_id}/renders/{render_id.hex}/download")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], "RENDER_FILE_CORRUPT")
        self.assertNotIn(b"X" * 32, blocked.content)
        ranged = client.get(f"/projects/{project_id}/renders/{render_id.hex}/download", headers={"Range": "bytes=0-9"})
        self.assertEqual(ranged.status_code, 409)
        state = client.get(f"/projects/{project_id}/rendering").json()
        self.assertFalse(state["download_available"])
        self.assertEqual(state["safe_error_code"], "RENDER_FILE_CORRUPT")
        with self.factory() as session:
            row = session.get(ProjectRenderRun, render_id)
            self.assertEqual(row.status, "COMPLETED")
            self.assertRegex(row.base_sha256, r"^[0-9a-f]{64}$")
