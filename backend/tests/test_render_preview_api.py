"""Existing render download routes as browser-readable Range media responses."""

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
from backend.app.models import EpisodeSplitPolicy, Project
from backend.app.services.project_render_execution import ProjectRenderRunRegistry
from backend.app.services.project_rendering import ProjectRenderResult


class _ImmediateExecutor:
    def submit(self, operation):
        operation()
        return object()


class RenderPreviewApiTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        engine = create_engine(f"sqlite+pysqlite:///{self.root / 'api.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start(); self.addCleanup(loader.stop)
        context = TestClient(app)
        self.client = context.__enter__(); self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = factory
        app.state.project_render_output_root = self.root / "outputs"
        app.state.project_render_run_registry = ProjectRenderRunRegistry(_ImmediateExecutor())
        with factory() as session:
            project = Project(name="preview", split_policy=EpisodeSplitPolicy.SINGLE)
            other = Project(name="other", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add_all([project, other]); session.commit()
            self.project_id, self.other_id = project.id, other.id
        self.render_id = uuid4()
        directory = self.root / "outputs" / "projects" / self.project_id.hex / "renders" / self.render_id.hex
        directory.mkdir(parents=True)
        self.plain = directory / "final.mp4"
        self.subtitled = directory / "final-subtitled.mp4"
        self.plain_bytes = b"basic" * 100
        self.subtitled_bytes = b"subtitled" * 100
        self.plain.write_bytes(self.plain_bytes)
        self.subtitled.write_bytes(self.subtitled_bytes)
        self.result = ProjectRenderResult(
            project_id=self.project_id, render_id=self.render_id, output_path=self.plain,
            candidate_ids=(), duration_seconds=1, video_codec="h264", audio_codec="aac",
            file_size_bytes=len(self.plain_bytes), hard_subtitle_path=self.subtitled,
        )
        app.state.project_render_run_registry.start(self.project_id, lambda: self.result)
        base = f"/projects/{self.project_id}/renders/{self.render_id.hex}"
        self.basic_url = f"{base}/download"
        self.subtitled_url = f"{base}/subtitled/download"

    def test_both_variants_support_range_and_keep_distinct_bytes(self):
        for url, content, disposition in (
            (self.basic_url, self.plain_bytes, "inline"),
            (self.subtitled_url, self.subtitled_bytes, "attachment"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, headers={"Range": "bytes=10-29"})
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.content, content[10:30])
                self.assertEqual(response.headers["content-type"], "video/mp4")
                self.assertEqual(response.headers["content-range"], f"bytes 10-29/{len(content)}")
                self.assertEqual(response.headers["accept-ranges"], "bytes")
                self.assertIn(disposition, response.headers["content-disposition"])
                self.assertEqual(self.client.get(url).content, content)
                self.assertEqual(self.client.get(url, headers={"Range": "bytes=9999-"}).status_code, 416)
        self.assertEqual(self.plain.read_bytes(), self.plain_bytes)
        self.assertEqual(self.subtitled.read_bytes(), self.subtitled_bytes)

    def test_invalid_cross_project_and_missing_files(self):
        self.assertEqual(self.client.get(f"/projects/{self.other_id}/renders/{self.render_id.hex}/download").status_code, 404)
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/renders/{uuid4().hex}/download").status_code, 404)
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/renders/not-hex/download").status_code, 422)
        self.subtitled.unlink()
        self.assertEqual(self.client.get(self.subtitled_url).status_code, 404)
        self.assertEqual(self.client.get(self.basic_url).status_code, 200)
        self.plain.unlink()
        self.assertEqual(self.client.get(self.basic_url).status_code, 404)
