from fastapi import APIRouter, UploadFile, File


router = APIRouter(
    prefix="/videos",
    tags=["videos"],
)


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    return {
        "filename": file.filename,
        "content_type": file.content_type,
    }
