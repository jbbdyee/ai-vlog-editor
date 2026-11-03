"""Bounded Project list API, without loading source/candidate/render relationships."""

from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import EpisodeSplitPolicy, Project, ProjectRenderRun, ProjectSceneEditPlan, SourceVideo
from backend.app.routers.projects import router


class ProjectListApiTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        engine = create_engine(f"sqlite+pysqlite:///{temporary.name}/list.db", connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        app = FastAPI()
        app.include_router(router)
        app.state.project_session_factory = factory
        self.client = TestClient(app)
        with factory() as session:
            older = Project(name="", split_policy=EpisodeSplitPolicy.SINGLE,
                            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            newer = Project(name="newer", split_policy=EpisodeSplitPolicy.SINGLE,
                            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
            session.add_all([older, newer])
            session.flush()
            session.add(SourceVideo(project_id=older.id, original_filename="one.mov", storage_reference="test/one.mov"))
            session.add(ProjectSceneEditPlan(project_id=older.id))
            session.add(ProjectRenderRun(render_id=uuid4(), project_id=older.id, status="FAILED",
                                         plan_snapshot=[], plan_fingerprint="x" * 64))
            session.commit()
            self.older_id, self.newer_id = str(older.id), str(newer.id)

    def test_order_pagination_and_real_summary(self):
        first = self.client.get("/projects?limit=1&offset=0")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["items"][0]["project_id"], self.newer_id)
        self.assertEqual(first.json()["next_offset"], 1)
        second = self.client.get("/projects?limit=1&offset=1")
        item = second.json()["items"][0]
        self.assertEqual(item["project_id"], self.older_id)
        self.assertEqual(item["name"], "")
        self.assertEqual(item["source_count"], 1)
        self.assertTrue(item["has_edit_plan"])
        self.assertEqual(item["latest_render_status"], "FAILED")
        self.assertIsNone(second.json()["next_offset"])
        self.assertEqual(self.client.get("/projects?offset=2").json()["items"], [])

    def test_limits_and_existing_detail_contract(self):
        self.assertEqual(self.client.get("/projects?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/projects?limit=51").status_code, 422)
        self.assertEqual(self.client.get("/projects?offset=-1").status_code, 422)
        self.assertEqual(self.client.get(f"/projects/{self.newer_id}").status_code, 200)
