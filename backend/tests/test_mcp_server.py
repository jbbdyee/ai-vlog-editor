import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock
from uuid import uuid4

from mcp import Client
from sqlalchemy import create_engine

from backend.app.database import create_session_factory
from backend.app.mcp.adapters import ProbeVideoMCPAdapter
from backend.app.mcp.server import create_video_editing_server
from backend.app.storage.source_storage import LocalSourceStorage
from backend.app.tools.contracts import (
    ToolError,
    ToolErrorCode,
    ToolInvocation,
)
from backend.app.tools.media import ProbeVideoData


class ProbeVideoMCPAdapterTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.storage = LocalSourceStorage(
            Path(self.temporary_directory.name) / "originals"
        )
        self.engine = create_engine("sqlite://")
        self.session_factory = create_session_factory(self.engine)
        self.source_id = uuid4()
        self.project_id = uuid4()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_success_calls_internal_tool_exactly_once_and_maps_allowlist(self) -> None:
        tool = Mock(return_value=_success_result())
        adapter = ProbeVideoMCPAdapter(
            session_factory=self.session_factory,
            storage=self.storage,
            tool=tool,
        )

        response = adapter(self.source_id, self.project_id)

        tool.assert_called_once()
        request = tool.call_args.args[0]
        self.assertEqual(request.source_video_id, self.source_id)
        self.assertEqual(request.expected_project_id, self.project_id)
        self.assertEqual(response["status"], "SUCCEEDED")
        self.assertEqual(response["data"]["video_codec"], "h264")
        self.assertEqual(
            set(response), {"status", "data", "execution", "warnings"}
        )
        _assert_no_sensitive_values(self, response)

    def test_expected_failure_is_structured_without_retry(self) -> None:
        tool = Mock(return_value=_failure_result(ToolErrorCode.RESOURCE_NOT_FOUND))
        adapter = ProbeVideoMCPAdapter(
            session_factory=self.session_factory,
            storage=self.storage,
            tool=tool,
        )

        response = adapter(self.source_id)

        tool.assert_called_once()
        self.assertEqual(response["status"], "FAILED")
        self.assertEqual(response["error"]["code"], "RESOURCE_NOT_FOUND")
        self.assertFalse(response["error"]["retryable"])
        _assert_no_sensitive_values(self, response)

    def test_security_failure_is_sanitized(self) -> None:
        tool = Mock(return_value=_failure_result(ToolErrorCode.SECURITY_VIOLATION))
        adapter = ProbeVideoMCPAdapter(
            session_factory=self.session_factory,
            storage=self.storage,
            tool=tool,
        )

        response = adapter(self.source_id, uuid4())

        self.assertEqual(response["error"]["safe_message"], "Safe tool failure.")
        _assert_no_sensitive_values(self, response)

    def test_programmer_error_is_not_converted_to_expected_failure(self) -> None:
        tool = Mock(side_effect=RuntimeError("traceback C:/secret/video.mp4"))
        adapter = ProbeVideoMCPAdapter(
            session_factory=self.session_factory,
            storage=self.storage,
            tool=tool,
        )

        with self.assertRaises(RuntimeError):
            adapter(self.source_id)

        tool.assert_called_once()


class VideoEditingMCPInProcessTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.engine = create_engine("sqlite://")
        self.session_factory = create_session_factory(self.engine)
        self.storage = LocalSourceStorage(
            Path(self.temporary_directory.name) / "originals"
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()

    async def test_only_probe_video_is_exposed_with_uuid_schema(self) -> None:
        server = self._server(Mock(return_value=_success_result()))
        async with Client(server) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            prompts = await client.list_prompts()

        self.assertEqual([tool.name for tool in tools.tools], ["probe_video"])
        schema = tools.tools[0].input_schema
        self.assertEqual(schema["required"], ["source_video_id"])
        self.assertEqual(
            schema["properties"]["source_video_id"]["format"], "uuid"
        )
        self.assertEqual(resources.resources, [])
        self.assertEqual(prompts.prompts, [])

    async def test_protocol_success_and_expected_failure_are_structured(self) -> None:
        success_tool = Mock(return_value=_success_result())
        async with Client(self._server(success_tool)) as client:
            result = await client.call_tool(
                "probe_video", {"source_video_id": str(uuid4())}
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["status"], "SUCCEEDED")
        success_tool.assert_called_once()
        _assert_no_sensitive_values(self, result.structured_content)

        failure_tool = Mock(
            return_value=_failure_result(ToolErrorCode.RESOURCE_NOT_FOUND)
        )
        async with Client(self._server(failure_tool)) as client:
            result = await client.call_tool(
                "probe_video", {"source_video_id": str(uuid4())}
            )

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.structured_content["error"]["code"], "RESOURCE_NOT_FOUND"
        )
        failure_tool.assert_called_once()

    async def test_invalid_uuid_is_protocol_error_before_tool_call(self) -> None:
        tool = Mock(return_value=_success_result())
        async with Client(self._server(tool)) as client:
            result = await client.call_tool(
                "probe_video", {"source_video_id": "../../secret.mp4"}
            )

        self.assertTrue(result.is_error)
        tool.assert_not_called()
        self.assertNotIn("C:/", repr(result))

    async def test_programmer_failure_is_safe_protocol_error(self) -> None:
        tool = Mock(side_effect=RuntimeError("secret C:/private/video.mp4"))
        async with Client(self._server(tool)) as client:
            result = await client.call_tool(
                "probe_video", {"source_video_id": str(uuid4())}
            )

        self.assertTrue(result.is_error)
        tool.assert_called_once()
        serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        self.assertNotIn("C:/private", serialized)
        self.assertNotIn("secret", serialized)

    def _server(self, tool):
        return create_video_editing_server(
            session_factory=self.session_factory,
            storage=self.storage,
            probe_tool=tool,
        )


class MCPImportBoundaryTests(TestCase):
    def test_internal_tool_layer_does_not_import_mcp(self) -> None:
        tool_root = Path(__file__).parents[1] / "app" / "tools"
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in tool_root.glob("*.py")
        )
        self.assertNotIn("import mcp", source)
        self.assertNotIn("from mcp", source)


def _success_result():
    return ToolInvocation("probe_video", "1.0").succeeded(
        ProbeVideoData(
            duration_seconds=1.0,
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="h264",
            audio_codec="aac",
            format_name="mov,mp4",
        )
    )


def _failure_result(code: ToolErrorCode):
    return ToolInvocation("probe_video", "1.0").failed(
        ToolError(
            code=code,
            safe_message="Safe tool failure.",
            retryable=False,
            affected_resource_id=uuid4(),
        )
    )


def _assert_no_sensitive_values(test_case: TestCase, value) -> None:
    serialized = json.dumps(value, default=str, ensure_ascii=False)
    for forbidden in (
        "storage_reference",
        "C:/",
        "C:\\\\",
        "ffprobe stderr",
        "POSTGRES_PASSWORD",
        "traceback",
    ):
        test_case.assertNotIn(forbidden, serialized)
