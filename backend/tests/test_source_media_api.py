"""Read-only source preview route and byte range regression tests."""

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
from backend.app.models import EpisodeSplitPolicy, Project, SourceVideo
from backend.app.storage.source_storage import LocalSourceStorage


class SourceMediaApiTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        engine = create_engine(f"sqlite+pysqlite:///{self.root / 'api.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start()
        self.addCleanup(loader.stop)
        context = TestClient(app, client=("127.0.0.1", 50000))
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = factory
        self.storage = LocalSourceStorage(self.root / "sources")
        app.state.source_storage = self.storage
        with factory() as session:
            project = Project(name="preview", split_policy=EpisodeSplitPolicy.SINGLE)
            other = Project(name="other", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add_all([project, other]); session.flush()
            self.project_id, self.other_id = project.id, other.id
            reference = f"projects/{project.id.hex}/sources/{uuid4().hex}.mov"
            source = SourceVideo(project_id=project.id, original_filename="clip.mov", storage_reference=reference)
            session.add(source); session.commit()
            self.source_id = source.id
        self.path = self.storage._root.joinpath(*reference.split("/"))
        self.path.parent.mkdir(parents=True)
        self.payload = b"0123456789" * 20
        self.path.write_bytes(self.payload)
        self.url = f"/projects/{self.project_id}/sources/{self.source_id}/media"

    def test_stream_range_and_integrity(self):
        before = self.path.read_bytes()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, before)
        self.assertEqual(response.headers["content-type"], "video/quicktime")
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        self.assertIn("inline", response.headers["content-disposition"])
        partial = self.client.get(self.url, headers={"Range": "bytes=10-19"})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, before[10:20])
        self.assertEqual(partial.headers["content-range"], "bytes 10-19/200")
        self.assertEqual(self.client.get(self.url, headers={"Range": "bytes=999-"}).status_code, 416)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_mismatch_and_unsafe_reference(self):
        self.assertEqual(self.client.get(f"/projects/not-a-uuid/sources/{self.source_id}/media").status_code, 422)
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/sources/not-a-uuid/media").status_code, 422)
        self.assertEqual(self.client.get(f"/projects/{uuid4()}/sources/{self.source_id}/media").status_code, 404)
        self.assertEqual(self.client.get(f"/projects/{self.other_id}/sources/{self.source_id}/media").status_code, 404)
        self.assertEqual(self.client.get(f"/projects/{self.project_id}/sources/{uuid4()}/media").status_code, 404)
        factory = app.state.project_session_factory
        with factory() as session:
            source = session.get(SourceVideo, self.source_id)
            source.storage_reference = "../../outside.mov"
            session.commit()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_missing_file_and_nonlocal_client(self):
        self.path.unlink()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        remote = TestClient(app, client=("192.0.2.10", 50000))
        self.assertEqual(remote.get(self.url).status_code, 403)

    def test_symlink_escape_is_denied_when_supported(self):
        outside = self.root / "outside.mov"
        outside.write_bytes(b"private")
        self.path.unlink()
        try:
            self.path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation requires additional Windows privileges.")
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(outside.read_bytes(), b"private")

    def test_mp4_mime(self):
        factory = app.state.project_session_factory
        mp4 = self.path.with_suffix(".mp4")
        mp4.write_bytes(b"mp4 data")
        with factory() as session:
            source = session.get(SourceVideo, self.source_id)
            source.storage_reference = source.storage_reference[:-4] + ".mp4"
            session.commit()
        self.assertEqual(self.client.get(self.url).headers["content-type"], "video/mp4")
