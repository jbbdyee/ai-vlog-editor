import os
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from mcp import Client, StdioServerParameters
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.config import DatabaseSettings, PROJECT_ROOT
from backend.app.database import create_database_engine
from backend.app.models import EpisodeSplitPolicy, ProcessingStage, Project, SourceVideo
from backend.app.services.source_ingestion import ingest_source
from backend.app.storage.source_storage import LocalSourceStorage


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class MCPStdioIntegrationTests(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.storage_root = root / "originals"
        self.storage = LocalSourceStorage(self.storage_root)
        self.session = Session(bind=self.engine, expire_on_commit=False)
        self.project = Project(
            name="MCP stdio integration",
            split_policy=EpisodeSplitPolicy.SINGLE,
        )
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

    def tearDown(self) -> None:
        self.session.execute(
            delete(ProcessingStage).where(
                ProcessingStage.source_video_id == self.ingested.source_video_id
            )
        )
        self.session.execute(
            delete(SourceVideo).where(SourceVideo.id == self.ingested.source_video_id)
        )
        self.session.execute(delete(Project).where(Project.id == self.project.id))
        self.session.commit()
        self.session.close()
        self.temporary_directory.cleanup()

    async def test_real_stdio_protocol_and_ffprobe_smoke(self) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "backend.app.mcp.server"],
            cwd=PROJECT_ROOT,
            env=self._server_environment(),
        )
        async with Client(parameters, read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            self.assertEqual([tool.name for tool in tools.tools], ["probe_video"])

            success = await client.call_tool(
                "probe_video",
                {
                    "source_video_id": str(self.ingested.source_video_id),
                    "project_id": str(self.project.id),
                },
            )
            self.assertFalse(success.is_error)
            payload = success.structured_content
            self.assertEqual(payload["status"], "SUCCEEDED")
            self.assertTrue(payload["data"]["has_video_stream"])
            self.assertTrue(payload["data"]["has_audio_stream"])
            self.assertGreater(payload["data"]["duration_seconds"], 0)
            self.assertEqual(payload["data"]["video_codec"], "mpeg4")
            self.assertEqual(payload["data"]["audio_codec"], "aac")

            invalid = await client.call_tool(
                "probe_video", {"source_video_id": "../../secret.mp4"}
            )
            self.assertTrue(invalid.is_error)

            missing = await client.call_tool(
                "probe_video", {"source_video_id": str(uuid4())}
            )
            self.assertFalse(missing.is_error)
            self.assertEqual(
                missing.structured_content["error"]["code"],
                "RESOURCE_NOT_FOUND",
            )

            wrong_scope = await client.call_tool(
                "probe_video",
                {
                    "source_video_id": str(self.ingested.source_video_id),
                    "project_id": str(uuid4()),
                },
            )
            self.assertFalse(wrong_scope.is_error)
            self.assertEqual(
                wrong_scope.structured_content["error"]["code"],
                "SECURITY_VIOLATION",
            )

        serialized = json.dumps(
            {
                "success": success.model_dump(mode="json"),
                "missing": missing.model_dump(mode="json"),
                "wrong_scope": wrong_scope.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        self.assertNotIn(str(self.storage_root), serialized)
        self.assertNotIn("storage_reference", serialized)
        self.assertNotIn(os.environ["POSTGRES_PASSWORD"], serialized)
        self.assertNotIn("ffprobe stderr", serialized)

    def _server_environment(self) -> dict[str, str]:
        names = (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        )
        environment = {name: os.environ[name] for name in names}
        environment["CUTORY_SOURCE_STORAGE_ROOT"] = str(self.storage_root)
        environment["PATH"] = os.environ.get("PATH", "")
        return environment

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
