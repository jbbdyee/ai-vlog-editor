from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from backend.app.storage.source_storage import SourceStorage
from backend.app.tools.contracts import ToolResult, ToolStatus
from backend.app.tools.media import (
    ProbeVideoData,
    ProbeVideoInput,
    probe_video as internal_probe_video,
)
from backend.app.tools.resources import DatabaseSourceResourceResolver


logger = logging.getLogger("cutory.mcp")
ProbeVideoTool = Callable[..., ToolResult[ProbeVideoData]]


class ProbeVideoMCPAdapter:
    """Translate one MCP call into exactly one internal probe_video invocation."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        storage: SourceStorage,
        tool: ProbeVideoTool = internal_probe_video,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._tool = tool

    def __call__(
        self,
        source_video_id: UUID,
        project_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Inspect one registered SourceVideo without exposing storage details."""
        with self._session_factory() as session:
            resolver = DatabaseSourceResourceResolver(
                session=session,
                storage=self._storage,
            )
            result = self._tool(
                ProbeVideoInput(
                    source_video_id=source_video_id,
                    expected_project_id=project_id,
                ),
                resolver=resolver,
            )

        response = _probe_result_response(result)
        logger.info(
            "mcp_tool_call tool=%s invocation_id=%s status=%s error_code=%s duration_ms=%.3f",
            result.metadata.tool_name,
            result.metadata.invocation_id,
            result.status.value,
            result.error.code.value if result.error is not None else None,
            result.metadata.duration_ms,
        )
        return response


def _probe_result_response(
    result: ToolResult[ProbeVideoData],
) -> dict[str, Any]:
    execution = {
        "invocation_id": str(result.metadata.invocation_id),
        "tool_name": result.metadata.tool_name,
        "tool_version": result.metadata.tool_version,
        "duration_ms": result.metadata.duration_ms,
    }
    response: dict[str, Any] = {
        "status": result.status.value,
        "execution": execution,
        "warnings": list(result.warnings),
    }
    if result.status is ToolStatus.SUCCEEDED:
        if result.data is None:
            raise RuntimeError("Successful probe_video ToolResult is missing data.")
        response["data"] = {
            "duration_seconds": result.data.duration_seconds,
            "has_video_stream": result.data.has_video_stream,
            "has_audio_stream": result.data.has_audio_stream,
            "video_codec": result.data.video_codec,
            "audio_codec": result.data.audio_codec,
            "format_name": result.data.format_name,
        }
        return response

    if result.error is None:
        raise RuntimeError("Failed probe_video ToolResult is missing an error.")
    response["error"] = {
        "code": result.error.code.value,
        "safe_message": result.error.safe_message,
        "retryable": result.error.retryable,
        "affected_resource_id": (
            str(result.error.affected_resource_id)
            if result.error.affected_resource_id is not None
            else None
        ),
    }
    return response
