from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.services.video_storage import VideoValidationError, save_video_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIRECTORY = PROJECT_ROOT / "uploads"


class VideoUploadResponse(BaseModel):
    original_filename: str
    stored_filename: str
    content_type: str
    video_id: str


router = APIRouter(
    prefix="/videos",
    tags=["videos"],
)


@router.post("/upload", response_model=VideoUploadResponse)
async def upload_video(file: UploadFile = File(...)):
    try:
        stored_video = await run_in_threadpool(
            save_video_file,
            file.file,
            file.filename,
            file.content_type,
            UPLOAD_DIRECTORY,
        )
    except VideoValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    finally:
        await file.close()

    return asdict(stored_video)
