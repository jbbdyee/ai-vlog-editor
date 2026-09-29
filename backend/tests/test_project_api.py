from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.project_execution import ProjectRunRegistry
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


MOV_CONTENT = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  "


class _ManualExecutor:
    def __init__(self) -> None:
        self.operations = []

    def submit(self, operation):
        self.operations.append(operation)
        return object()

    def run_next(self) -> None:
        self.operations.pop(0)()


class _FailingRegistry:
    def start(self, _project_id, _operation):
        raise RuntimeError("secret executor detail")


class ProjectAPITests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.engine = create_engine(
            f"sqlite+pysqlite:///{self.root / 'project-api.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.stt_model = object()
        self.load_model_patcher = patch(
            "backend.app.main.load_model", return_value=self.stt_model
        )
        self.load_model_patcher.start()
        self.addCleanup(self.load_model_patcher.stop)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        app.state.source_storage = LocalSourceStorage(self.root / "originals")
        app.state.processing_workspace = LocalProcessingWorkspace(
            self.root / "temporary"
        )
        self.executor = _ManualExecutor()
        app.state.project_run_registry = ProjectRunRegistry(self.executor)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_create_and_get_project_use_explicit_safe_dto(self) -> None:
        response = self._create_project()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["name"], "제주 브이로그")
        self.assertEqual(body["split_policy"], "SINGLE")
        self.assertEqual(body["target_duration_seconds"], 180.0)
        self.assertEqual(body["status"], "CREATED")
        self.assertEqual(body["source_count"], 0)
        self.assertEqual(body["processing"]["progress_ratio"], 0.0)
        self.assertNotIn("storage", response.text.lower())
        self.assertNotIn("fingerprint", response.text.lower())

        fetched = self.client.get(f"/projects/{body['project_id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["project_id"], body["project_id"])

    def test_validation_and_not_found_mapping(self) -> None:
        invalid_policy = self.client.post(
            "/projects", json={"name": "test", "split_policy": "UNKNOWN"}
        )
        invalid_uuid = self.client.get("/projects/not-a-uuid")
        missing = self.client.get(f"/projects/{uuid4()}")

        self.assertEqual(invalid_policy.status_code, 422)
        self.assertEqual(invalid_uuid.status_code, 422)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "PROJECT_NOT_FOUND")

    def test_source_ingestion_reuses_validation_and_hides_internal_identity(self) -> None:
        project_id = self._create_project().json()["project_id"]

        response = self.client.post(
            f"/projects/{project_id}/sources",
            files={"file": ("../../private.MOV", MOV_CONTENT, "video/quicktime")},
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "source_video_id",
                "project_id",
                "original_filename",
                "processing_status",
                "duplicate_fingerprint_in_project",
            },
        )
        self.assertEqual(body["original_filename"], "../../private.MOV")
        self.assertEqual(body["processing_status"], "READY")
        for forbidden in (
            "resource_reference",
            str(self.root),
            "C:\\\\",
            "/Users/",
            "/home/",
        ):
            self.assertNotIn(forbidden, response.text)

        with self.factory() as session:
            source = session.get(SourceVideo, UUID(body["source_video_id"]))
            stored_path = app.state.source_storage.resolve(source.storage_reference)
            self.assertTrue(stored_path.is_file())
            self.assertNotIn("private", stored_path.name)

    def test_invalid_source_is_415_and_missing_project_is_404(self) -> None:
        project_id = self._create_project().json()["project_id"]
        invalid = self.client.post(
            f"/projects/{project_id}/sources",
            files={"file": ("notes.txt", b"not-video", "text/plain")},
        )
        missing = self.client.post(
            f"/projects/{uuid4()}/sources",
            files={"file": ("clip.mov", MOV_CONTENT, "video/quicktime")},
        )

        self.assertEqual(invalid.status_code, 415)
        self.assertEqual(invalid.json()["detail"]["code"], "INVALID_SOURCE_MEDIA")
        self.assertEqual(missing.status_code, 404)

    def test_processing_start_is_accepted_non_blocking_guarded_and_reuses_model(self) -> None:
        project_id = self._create_project().json()["project_id"]
        processor = patch("backend.app.routers.projects.process_project").start()
        self.addCleanup(patch.stopall)

        first = self.client.post(f"/projects/{project_id}/process")
        duplicate = self.client.post(f"/projects/{project_id}/process")

        self.assertEqual(first.status_code, 202)
        self.assertTrue(first.json()["accepted"])
        self.assertEqual(
            first.json()["status_url"], f"/projects/{project_id}/processing"
        )
        self.assertEqual(duplicate.status_code, 409)
        processor.assert_not_called()
        self.assertEqual(len(self.executor.operations), 1)

        self.executor.run_next()
        processor.assert_called_once()
        arguments = processor.call_args.kwargs
        self.assertIs(arguments["stt_model"], self.stt_model)
        self.assertEqual(arguments["max_concurrency"], 1)

        restarted = self.client.post(f"/projects/{project_id}/process")
        self.assertEqual(restarted.status_code, 202)
        self.assertEqual(len(self.executor.operations), 1)

    def test_status_is_database_backed_after_registry_restart(self) -> None:
        project_id = self._create_project().json()["project_id"]
        completed_id, failed_id, running_id = self._create_sources(project_id, 3)
        project_uuid = UUID(project_id)
        with self.factory() as session:
            self._mark_completed(session, completed_id)
            failed = session.get(SourceVideo, failed_id)
            failed.processing_status = SourceVideoStatus.FAILED
            failed_stage = self._stages(session, failed_id)[ProcessingStageKind.PROBE]
            failed_stage.status = ProcessingStageStatus.FAILED
            failed_stage.safe_error_code = "PROBE_FAILED"
            running = session.get(SourceVideo, running_id)
            running.processing_status = SourceVideoStatus.PROCESSING
            running_stage = self._stages(session, running_id)[ProcessingStageKind.STT]
            running_stage.status = ProcessingStageStatus.RUNNING
            running_stage.started_at = datetime.now(timezone.utc)
            project = session.get(Project, project_uuid)
            project.status = ProjectStatus.PROCESSING
            session.commit()

        app.state.project_run_registry = ProjectRunRegistry(_ManualExecutor())
        response = self.client.get(f"/projects/{project_id}/processing")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_status"], "PROCESSING")
        self.assertEqual(body["total_sources"], 3)
        self.assertEqual(body["completed_count"], 1)
        self.assertEqual(body["failed_count"], 1)
        self.assertEqual(body["blocked_count"], 1)
        self.assertEqual(body["remaining_count"], 0)
        self.assertAlmostEqual(body["progress_ratio"], 2 / 3)
        self.assertNotIn("transcript", response.text.lower())

    def test_empty_project_status_and_openapi_routes(self) -> None:
        project_id = self._create_project().json()["project_id"]
        response = self.client.get(f"/projects/{project_id}/processing")
        paths = app.openapi()["paths"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_sources"], 0)
        self.assertEqual(response.json()["progress_ratio"], 0.0)
        for route in (
            "/health",
            "/videos/upload",
            "/videos/process",
            "/videos/clips/{run_id}/{clip_id}",
            "/projects",
            "/projects/{project_id}",
            "/projects/{project_id}/sources",
            "/projects/{project_id}/process",
            "/projects/{project_id}/processing",
        ):
            self.assertIn(route, paths)

    def test_database_unavailable_and_start_failure_are_safe(self) -> None:
        project_id = self._create_project().json()["project_id"]
        app.state.project_run_registry = _FailingRegistry()
        failed_start = self.client.post(f"/projects/{project_id}/process")

        self.assertEqual(failed_start.status_code, 500)
        self.assertEqual(
            failed_start.json()["detail"]["code"],
            "PROJECT_PROCESSING_START_FAILED",
        )
        self.assertNotIn("secret executor detail", failed_start.text)

        app.state.project_session_factory = None
        unavailable = self.client.get(f"/projects/{project_id}")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(
            unavailable.json()["detail"]["code"],
            "PROJECT_DATABASE_UNAVAILABLE",
        )

    def _create_project(self):
        return self.client.post(
            "/projects",
            json={
                "name": "제주 브이로그",
                "split_policy": "SINGLE",
                "target_duration_seconds": 180,
                "instruction": "대화 중심",
            },
        )

    def _create_sources(self, project_id, count):
        project_id = UUID(project_id)
        with self.factory() as session:
            sources = []
            for index in range(count):
                source = SourceVideo(
                    project_id=project_id,
                    original_filename=f"source-{index}.mp4",
                    storage_reference=f"projects/{project_id}/sources/{index}.mp4",
                    fingerprint=f"fingerprint-{index}",
                    fingerprint_algorithm="sha256",
                    processing_status=SourceVideoStatus.READY,
                    processing_stages=[
                        ProcessingStage(
                            stage=stage, status=ProcessingStageStatus.PENDING
                        )
                        for stage in ProcessingStageKind
                    ],
                )
                session.add(source)
                sources.append(source)
            session.commit()
            return tuple(source.id for source in sources)

    def _mark_completed(self, session, source_id):
        source = session.get(SourceVideo, source_id)
        source.duration_seconds = 1.0
        source.video_codec = "h264"
        source.audio_codec = "aac"
        source.format_name = "mov,mp4"
        source.processing_status = SourceVideoStatus.COMPLETED
        source.transcript = Transcript(
            text="test", language="ko", language_probability=1.0, segments=[]
        )
        for stage in self._stages(session, source_id).values():
            stage.status = ProcessingStageStatus.COMPLETED
            stage.input_fingerprint = source.fingerprint
        session.commit()

    @staticmethod
    def _stages(session, source_id):
        return {
            stage.stage: stage
            for stage in session.scalars(
                select(ProcessingStage).where(
                    ProcessingStage.source_video_id == source_id
                )
            ).all()
        }
