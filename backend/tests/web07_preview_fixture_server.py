"""Local WEB-07 browser fixture: seed process memory from an existing QA render.

This is test-only state, not render recovery. It never writes or modifies render files.
"""

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import os
from uuid import UUID

import uvicorn

from backend.app.main import app, PROJECT_RENDER_OUTPUT_DIRECTORY
from backend.app.services.media_probe import probe_media
from backend.app.services.project_render_execution import RenderRunStatus
from backend.app.services.project_rendering import ProjectRenderResult


project_id = UUID(os.environ["WEB07_QA_PROJECT_ID"])
render_id = UUID(os.environ["WEB07_QA_RENDER_ID"])
directory = (PROJECT_RENDER_OUTPUT_DIRECTORY / "projects" / project_id.hex / "renders" / render_id.hex).resolve()
expected = PROJECT_RENDER_OUTPUT_DIRECTORY.resolve() / "projects" / project_id.hex / "renders" / render_id.hex
if directory != expected:
    raise RuntimeError("QA render path is unsafe.")
plain = directory / "final.mp4"
subtitled = directory / "final-subtitled.mp4"
subtitle = directory / "final.srt"
if not all(path.is_file() and path.stat().st_size > 0 for path in (plain, subtitled, subtitle)):
    raise RuntimeError("A complete existing QA render is required.")
info = probe_media(plain)
result = ProjectRenderResult(
    project_id=project_id, render_id=render_id, output_path=plain,
    candidate_ids=(), duration_seconds=info.duration_seconds,
    video_codec=info.video_codec, audio_codec=info.audio_codec,
    file_size_bytes=plain.stat().st_size, subtitle_path=subtitle,
    hard_subtitle_path=subtitled,
)

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def fixture_lifespan(application):
    async with original_lifespan(application):
        registry = application.state.project_render_run_registry
        if not registry.start(project_id, lambda: result):
            raise RuntimeError("Could not seed QA render status.")
        for _ in range(100):
            if registry.snapshot(project_id).status is RenderRunStatus.COMPLETED:
                break
            await asyncio.sleep(0.01)
        else:
            raise RuntimeError("QA render status did not complete.")
        yield


app.router.lifespan_context = fixture_lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
