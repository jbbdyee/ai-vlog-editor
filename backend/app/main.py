import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from backend.app.config import DatabaseConfigError, DatabaseSettings, load_environment
from backend.app.database import create_database_engine, create_session_factory
from backend.app.routers.projects import router as project_router
from backend.app.routers.videos import router as video_router
from backend.app.services.project_execution import ProjectRunRegistry
from backend.app.services.stt_service import load_model
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_SOURCE_DIRECTORY = PROJECT_ROOT / "storage" / "originals"
PRODUCT_TEMPORARY_DIRECTORY = PROJECT_ROOT / "temporary"


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.stt_model = await run_in_threadpool(load_model)
    application.state.pipeline_semaphore = asyncio.Semaphore(1)
    application.state.source_storage = LocalSourceStorage(PRODUCT_SOURCE_DIRECTORY)
    application.state.processing_workspace = LocalProcessingWorkspace(
        PRODUCT_TEMPORARY_DIRECTORY
    )
    project_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="cutory-project"
    )
    application.state.project_run_registry = ProjectRunRegistry(project_executor)

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
