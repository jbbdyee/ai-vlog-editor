from fastapi import FastAPI


app = FastAPI(
    title="AI Vlog Editor",
    description="AI-powered vlog editing service",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}