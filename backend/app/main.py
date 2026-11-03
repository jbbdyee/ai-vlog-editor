import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import inspect
from starlette.concurrency import run_in_threadpool

from backend.app.config import DatabaseConfigError, DatabaseSettings, load_environment
from backend.app.database import create_database_engine, create_session_factory
from backend.app.routers.projects import router as project_router
from backend.app.routers.videos import router as video_router
from backend.app.services.project_execution import ProjectRunRegistry
from backend.app.services.project_scene_execution import ProjectSceneRunRegistry
from backend.app.services.project_render_execution import ProjectRenderRunRegistry
from backend.app.services.persistent_render_execution import PersistentProjectRenderRunRegistry
from backend.app.services.stt_service import load_model
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_SOURCE_DIRECTORY = PROJECT_ROOT / "storage" / "originals"
PRODUCT_TEMPORARY_DIRECTORY = PROJECT_ROOT / "temporary"
PROJECT_RENDER_OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "projects"


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.stt_model = await run_in_threadpool(load_model)
    application.state.pipeline_semaphore = asyncio.Semaphore(1)
    application.state.source_storage = LocalSourceStorage(PRODUCT_SOURCE_DIRECTORY)
    application.state.processing_workspace = LocalProcessingWorkspace(
        PRODUCT_TEMPORARY_DIRECTORY
    )
    application.state.scene_processing_workspace = LocalProcessingWorkspace(
        PRODUCT_TEMPORARY_DIRECTORY / "scene"
    )
    project_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="cutory-project"
    )
    application.state.project_run_registry = ProjectRunRegistry(project_executor)
    application.state.project_scene_run_registry = ProjectSceneRunRegistry(project_executor)
    application.state.project_render_run_registry = ProjectRenderRunRegistry(project_executor)
    application.state.project_render_output_root = PROJECT_RENDER_OUTPUT_DIRECTORY

    load_environment()
    database_engine = None
    try:
        settings = DatabaseSettings.from_environment()
    except DatabaseConfigError:
        application.state.project_session_factory = None
    else:
        database_engine = create_database_engine(settings)
        application.state.project_session_factory = create_session_factory(
            database_engine
        )
        if os.environ.get("CUTORY_RENDER_PERSISTENCE_ENABLED") == "1":
            if not inspect(database_engine).has_table("project_render_runs"):
                raise RuntimeError("Render persistence requires the project_render_runs migration.")
            render_columns = {column["name"] for column in
                              inspect(database_engine).get_columns("project_render_runs")}
            if not {"base_sha256", "srt_sha256", "hard_sha256"} <= render_columns:
                # QA-03: fail fast instead of 500s on every render status/history query.
                raise RuntimeError("Render persistence requires the render digest migration (e3a1c9d27b45).")
            application.state.project_render_run_registry = PersistentProjectRenderRunRegistry(
                project_executor, application.state.project_session_factory,
                PROJECT_RENDER_OUTPUT_DIRECTORY,
            )

    try:
        yield
    finally:
        await run_in_threadpool(project_executor.shutdown, True)
        if database_engine is not None:
            database_engine.dispose()


app = FastAPI(
    title="AI Vlog Editor",
    description="AI-powered vlog editing service",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(video_router)
app.include_router(project_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
