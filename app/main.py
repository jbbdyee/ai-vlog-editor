import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.routers.videos import router as video_router
from app.services.stt_service import load_model


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.stt_model = await run_in_threadpool(load_model)
    application.state.pipeline_semaphore = asyncio.Semaphore(1)
    yield


app = FastAPI(
    title="AI Vlog Editor",
    description="AI-powered vlog editing service",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(video_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
