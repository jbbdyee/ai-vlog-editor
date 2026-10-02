import os
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, skipUnless

from sqlalchemy.orm import Session

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine
from backend.app.models import EpisodeSplitPolicy, Project
from backend.app.services.source_ingestion import ingest_source
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage
from backend.app.tools.contracts import ToolStatus
from backend.app.tools.media import ExtractAudioInput, ProbeVideoInput, extract_audio, probe_video
from backend.app.tools.resources import DatabaseSourceResourceResolver, TemporaryArtifactRegistry
from backend.app.tools.transcript import (
    DetectEditMemosInput,
    TranscribeAudioInput,
    detect_edit_memos,
    transcribe_audio,
)


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class ToolLayerIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, expire_on_commit=False)
        self.temporary_directory = TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.storage = LocalSourceStorage(root / "originals")
        self.workspace = LocalProcessingWorkspace(root / "temporary")
        self.registry = TemporaryArtifactRegistry(root / "temporary")
        self.project = Project(name="Tool Integration", split_policy=EpisodeSplitPolicy.SINGLE)
        self.session.add(self.project)
        self.session.commit()
        fixture = root / "fixture.mp4"
        self._create_fixture(fixture)
        with fixture.open("rb") as source_file:
            self.ingested = ingest_source(
                session=self.session,
                storage=self.storage,
                project_id=self.project.id,
                file_object=BytesIO(source_file.read()),
                original_filename="fixture.mp4",
                content_type="video/mp4",
            )
        self.resolver = DatabaseSourceResourceResolver(
            session=self.session, storage=self.storage
        )

    def tearDown(self) -> None:
        self.session.close()
        self.transaction.rollback()
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_real_postgresql_ffprobe_ffmpeg_and_tool_chain(self) -> None:
        probe_result = probe_video(
            ProbeVideoInput(self.ingested.source_video_id, self.project.id),
            resolver=self.resolver,
        )
        self.assertEqual(probe_result.status, ToolStatus.SUCCEEDED)
        self.assertTrue(probe_result.data.has_video_stream)
        self.assertTrue(probe_result.data.has_audio_stream)

        audio_result = extract_audio(
            ExtractAudioInput(self.ingested.source_video_id, self.project.id),
            resolver=self.resolver,
            workspace=self.workspace,
            registry=self.registry,
        )
        self.assertEqual(audio_result.status, ToolStatus.SUCCEEDED)
        artifact = audio_result.data.artifact
        audio_path = self.registry.resolve(artifact.artifact_id)
        self.assertGreater(audio_path.stat().st_size, 0)

        fake_model = _FakeWhisperModel()
        transcript_result = transcribe_audio(
            TranscribeAudioInput(
                artifact.artifact_id,
                expected_project_id=self.project.id,
                expected_source_video_id=self.ingested.source_video_id,
                expected_scope_id=artifact.scope_id,
            ),
            registry=self.registry,
            model=fake_model,
        )
        self.assertEqual(transcript_result.status, ToolStatus.SUCCEEDED)
        self.assertEqual(fake_model.calls, 1)
        memo_result = detect_edit_memos(
            DetectEditMemosInput(transcript_result.data)
        )
        self.assertEqual(memo_result.status, ToolStatus.SUCCEEDED)
        self.assertEqual(len(memo_result.data.memos), 1)

        self.registry.cleanup(artifact.artifact_id)
        self.assertFalse(audio_path.exists())
        resolved_source = self.resolver.resolve_source(self.ingested.source_video_id)
        self.assertTrue(resolved_source.path.is_file())

    @staticmethod
    def _create_fixture(path: Path) -> None:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, check=False, timeout=30)
        if result.returncode != 0:
            raise AssertionError("Could not create deterministic media fixture.")


class _FakeWhisperModel:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, path, *, language, word_timestamps):
        self.calls += 1
        words = (
            SimpleNamespace(start=0.1, end=0.2, word="AI야", probability=0.99),
            SimpleNamespace(start=0.2, end=0.3, word="방금", probability=0.99),
            SimpleNamespace(start=0.3, end=0.4, word="장면", probability=0.99),
            SimpleNamespace(start=0.4, end=0.5, word="꼭", probability=0.99),
            SimpleNamespace(start=0.5, end=0.7, word="살려줘", probability=0.99),
        )
        return (
            iter(
                [
                    SimpleNamespace(
                        start=0.1,
                        end=0.7,
                        text="AI야 방금 장면 꼭 살려줘",
                        words=words,
                    )
                ]
            ),
            SimpleNamespace(language="ko", language_probability=0.99),
        )
