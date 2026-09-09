from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj
from typing import BinaryIO
from uuid import uuid4


ALLOWED_VIDEO_TYPES = {
    ".mov": frozenset({"video/quicktime"}),
    ".mp4": frozenset({"video/mp4", "application/mp4"}),
}
COPY_BUFFER_SIZE = 1024 * 1024


class VideoValidationError(ValueError):
    """Raised when an upload is not an allowed MOV or MP4 video."""


@dataclass(frozen=True)
class StoredVideo:
    original_filename: str
    stored_filename: str
    content_type: str
    video_id: str


def validate_video_file(
    file_object: BinaryIO,
    original_filename: str | None,
    content_type: str | None,
) -> str:
    """Validate the upload and return its normalized file extension."""
    if not original_filename:
        raise VideoValidationError("A filename is required.")

    extension = Path(original_filename).suffix.lower()
    allowed_content_types = ALLOWED_VIDEO_TYPES.get(extension)

    if allowed_content_types is None:
        raise VideoValidationError("Only MOV and MP4 video files are allowed.")

    if content_type not in allowed_content_types:
        raise VideoValidationError(
            "The file extension and Content-Type do not match an allowed video format."
        )

    if not _has_iso_base_media_signature(file_object):
        raise VideoValidationError(
            "The uploaded content is not a valid MOV or MP4 container."
        )

    return extension


def save_video_file(
    file_object: BinaryIO,
    original_filename: str | None,
    content_type: str | None,
    upload_directory: Path,
) -> StoredVideo:
    """Validate and stream an uploaded video to a generated local filename."""
    extension = validate_video_file(file_object, original_filename, content_type)
    upload_directory.mkdir(parents=True, exist_ok=True)

    video_id = uuid4().hex
    stored_filename = f"{video_id}{extension}"
    destination = upload_directory / stored_filename

    try:
        file_object.seek(0)
        with destination.open("xb") as saved_file:
            copyfileobj(file_object, saved_file, length=COPY_BUFFER_SIZE)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return StoredVideo(
        original_filename=original_filename,
        stored_filename=stored_filename,
        content_type=content_type,
        video_id=video_id,
    )


def _has_iso_base_media_signature(file_object: BinaryIO) -> bool:
    """Check the common ISO Base Media File Format `ftyp` box signature."""
    original_position = file_object.tell()

    try:
        file_object.seek(0)
        header = file_object.read(12)
    finally:
        file_object.seek(original_position)

    return len(header) >= 12 and header[4:8] == b"ftyp"
