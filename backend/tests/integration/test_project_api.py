from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.main import app
from backend.app.models import (
    EditMemo,
    ProcessingStage,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


MOV_CONTENT = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  "


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class ProjectAPIIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.stt_model = object()
        self.load_model_patcher = patch(
            "backend.app.main.load_model", return_value=self.stt_model
        )
        self.load_model_patcher.start()
        self.addCleanup(self.load_model_patcher.stop)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        app.state.source_storage = LocalSourceStorage(self.root / "originals")
        app.state.processing_workspace = LocalProcessingWorkspace(
            self.root / "temporary"
        )
        self.project_id: UUID | None = None

    def tearDown(self) -> None:
        if self.project_id is not None:
            factory = app.state.project_session_factory
            with factory() as session:
                source_ids = select(SourceVideo.id).where(
                    SourceVideo.project_id == self.project_id
                )
                session.execute(
                    delete(EditMemo).where(EditMemo.source_video_id.in_(source_ids))
                )
                session.execute(
                    delete(Transcript).where(Transcript.source_video_id.in_(source_ids))
                )
                session.execute(
                    delete(ProcessingStage).where(
                        ProcessingStage.source_video_id.in_(source_ids)
                    )
                )
                session.execute(
                    delete(SourceVideo).where(
                        SourceVideo.project_id == self.project_id
                    )
                )
                session.execute(
                    delete(Project).where(Project.id == self.project_id)
                )
                session.commit()
        self.temporary_directory.cleanup()

    def test_create_ingest_accept_background_and_read_persisted_status(self) -> None:
        created = self.client.post(
            "/projects",
            json={"name": "PostgreSQL API", "split_policy": "SINGLE"},
        )
        self.assertEqual(created.status_code, 201)
        self.project_id = UUID(created.json()["project_id"])

        ingested = self.client.post(
            f"/projects/{self.project_id}/sources",
            files={"file": ("integration.mov", MOV_CONTENT, "video/quicktime")},
        )
        self.assertEqual(ingested.status_code, 201)
        source_id = UUID(ingested.json()["source_video_id"])
        completed = Event()

        def fake_project_processor(*, session_factory, project_id, **_kwargs):
            with session_factory() as session:
                project = session.get(Project, project_id)
                source = session.get(SourceVideo, source_id)
                source.duration_seconds = 1.0
                source.video_codec = "h264"
                source.audio_codec = "aac"
                source.format_name = "mov,mp4"
                source.processing_status = SourceVideoStatus.COMPLETED
                source.transcript = Transcript(
                    text="test",
                    language="ko",
                    language_probability=1.0,
                    segments=[],
                )
                for stage in session.scalars(
                    select(ProcessingStage).where(
                        ProcessingStage.source_video_id == source_id
                    )
                ).all():
                    stage.status = ProcessingStageStatus.COMPLETED
                    stage.input_fingerprint = source.fingerprint
                project.status = ProjectStatus.COMPLETED
                session.commit()
            completed.set()

        with patch(
            "backend.app.routers.projects.process_project",
            side_effect=fake_project_processor,
        ):
            accepted = self.client.post(f"/projects/{self.project_id}/process")
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(completed.wait(timeout=5))

        status_response = self.client.get(
            f"/projects/{self.project_id}/processing"
        )
        self.assertEqual(status_response.status_code, 200)
        body = status_response.json()
        self.assertEqual(body["project_status"], "COMPLETED")
        self.assertEqual(body["completed_count"], 1)
        self.assertEqual(body["progress_ratio"], 1.0)
        self.assertEqual(body["sources"][0]["source_video_id"], str(source_id))
        self.assertNotIn("storage_reference", status_response.text)
        self.assertNotIn(str(self.root), status_response.text)

        with app.state.project_session_factory() as session:
            source = session.get(SourceVideo, source_id)
            self.assertEqual(source.processing_status, SourceVideoStatus.COMPLETED)
            self.assertIsNotNone(source.transcript)
