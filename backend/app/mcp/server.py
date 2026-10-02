from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import (
    DatabaseSettings,
    PROJECT_ROOT,
    load_environment,
)
from backend.app.database import create_database_engine, create_session_factory
from backend.app.mcp.adapters import ProbeVideoMCPAdapter, ProbeVideoTool
from backend.app.storage.source_storage import LocalSourceStorage, SourceStorage


MCP_SERVER_NAME = "cutory-video-editing"
MCP_SERVER_VERSION = "1.0"
SOURCE_STORAGE_ROOT_ENV = "CUTORY_SOURCE_STORAGE_ROOT"
DEFAULT_SOURCE_STORAGE_ROOT = PROJECT_ROOT / "storage" / "originals"
logger = logging.getLogger("cutory.mcp")


def _configure_safe_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_video_editing_server(
    *,
    session_factory: sessionmaker[Session],
    storage: SourceStorage,
    probe_tool: ProbeVideoTool,
    engine: Engine | None = None,
) -> MCPServer[Any]:
    """Create the allowlisted stdio-capable server with probe_video only."""
    _configure_safe_logging()

    @asynccontextmanager
    async def lifespan(server: MCPServer[Any]) -> AsyncIterator[None]:
        del server
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    server = MCPServer(
        MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        description="Safe Cutory video inspection capabilities.",
        lifespan=lifespan,
        log_level="CRITICAL",
    )
    adapter = ProbeVideoMCPAdapter(
        session_factory=session_factory,
        storage=storage,
        tool=probe_tool,
    )

    def probe_video_mcp(
        source_video_id: UUID,
        project_id: UUID | None = None,
    ) -> dict[str, Any]:
        try:
            return adapter(source_video_id=source_video_id, project_id=project_id)
        except Exception as error:
            logger.error(
                "mcp_tool_internal_error tool=probe_video exception_type=%s",
                type(error).__name__,
            )
            raise RuntimeError("Internal MCP tool execution failed.") from None

    server.add_tool(
        probe_video_mcp,
        name="probe_video",
        description=(
            "Inspect a registered SourceVideo by UUID. Optional project_id asserts "
            "Project ownership. Paths, URLs and storage references are not accepted."
        ),
        structured_output=True,
    )
    return server


def build_server_from_environment(
    environment: Mapping[str, str] | None = None,
) -> MCPServer[Any]:
    """Build production stdio dependencies without loading unrelated media models."""
    values = os.environ if environment is None else environment
    settings = DatabaseSettings.from_environment(values)
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    storage = LocalSourceStorage(_source_storage_root(values))
    from backend.app.tools.media import probe_video

    return create_video_editing_server(
        session_factory=session_factory,
        storage=storage,
        probe_tool=probe_video,
        engine=engine,
    )


def _source_storage_root(environment: Mapping[str, str]) -> Path:
    configured = environment.get(SOURCE_STORAGE_ROOT_ENV, "").strip()
    if not configured:
        return DEFAULT_SOURCE_STORAGE_ROOT
    return Path(configured).expanduser().resolve()


def main() -> None:
    """Run the local-first MCP process over protocol-only stdio."""
    load_environment()
    server = build_server_from_environment()
    logger.info("mcp_server_start name=%s transport=stdio", MCP_SERVER_NAME)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
