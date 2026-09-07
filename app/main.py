from fastapi import FastAPI

from app.routers.videos import router as video_router


app = FastAPI(
    title="AI Vlog Editor",
    description="AI-powered vlog editing service",
    version="0.1.0",
)


app.include_router(video_router)


@app.get("/health")
async def health():
    return {"status": "ok"}