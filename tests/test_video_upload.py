from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.main import app, health
from app.routers.videos import upload_video


MOV_CONTENT = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  "
MP4_CONTENT = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isom"


def make_upload(filename: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


class VideoUploadTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.upload_directory = (
            Path(self.temporary_directory.name) / "missing" / "uploads"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_mov_upload_succeeds_and_creates_directory(self) -> None:
        upload = make_upload("eval_01.MOV", "video/quicktime", MOV_CONTENT)

        with patch("app.routers.videos.UPLOAD_DIRECTORY", self.upload_directory):
            response = await upload_video(upload)

        stored_path = self.upload_directory / response["stored_filename"]

        self.assertTrue(self.upload_directory.is_dir())
        self.assertEqual(response["original_filename"], "eval_01.MOV")
        self.assertEqual(response["content_type"], "video/quicktime")
        self.assertEqual(stored_path.suffix, ".mov")
        self.assertEqual(stored_path.read_bytes(), MOV_CONTENT)
        self.assertEqual(UUID(response["video_id"]).hex, response["video_id"])

    async def test_mp4_upload_succeeds(self) -> None:
        upload = make_upload("clip.mp4", "video/mp4", MP4_CONTENT)

        with patch("app.routers.videos.UPLOAD_DIRECTORY", self.upload_directory):
            response = await upload_video(upload)

        stored_path = self.upload_directory / response["stored_filename"]

        self.assertEqual(response["original_filename"], "clip.mp4")
        self.assertEqual(response["content_type"], "video/mp4")
        self.assertEqual(stored_path.read_bytes(), MP4_CONTENT)

    async def test_unsupported_file_type_is_rejected(self) -> None:
        upload = make_upload("notes.txt", "text/plain", b"not a video")

        with patch("app.routers.videos.UPLOAD_DIRECTORY", self.upload_directory):
            with self.assertRaises(HTTPException) as raised:
                await upload_video(upload)

        self.assertEqual(raised.exception.status_code, 415)
        self.assertEqual(
            raised.exception.detail,
            "Only MOV and MP4 video files are allowed.",
        )
        self.assertFalse(self.upload_directory.exists())

    async def test_mismatched_content_type_is_rejected(self) -> None:
        upload = make_upload("clip.mp4", "text/plain", MP4_CONTENT)

        with patch("app.routers.videos.UPLOAD_DIRECTORY", self.upload_directory):
            with self.assertRaises(HTTPException) as raised:
                await upload_video(upload)

        self.assertEqual(raised.exception.status_code, 415)
        self.assertIn("Content-Type", raised.exception.detail)

    async def test_invalid_container_signature_is_rejected(self) -> None:
        upload = make_upload("clip.mp4", "video/mp4", b"not a video")

        with patch("app.routers.videos.UPLOAD_DIRECTORY", self.upload_directory):
            with self.assertRaises(HTTPException) as raised:
                await upload_video(upload)

        self.assertEqual(raised.exception.status_code, 415)
        self.assertIn("valid MOV or MP4 container", raised.exception.detail)

    async def test_original_filename_is_not_used_as_stored_filename(self) -> None:
        upload = make_upload("../../escape.mp4", "video/mp4", MP4_CONTENT)

        with patch("app.routers.videos.UPLOAD_DIRECTORY", self.upload_directory):
            response = await upload_video(upload)

        self.assertNotIn("escape", response["stored_filename"])
        self.assertEqual(
            (self.upload_directory / response["stored_filename"]).parent,
            self.upload_directory,
        )

    async def test_health_endpoint_stays_available(self) -> None:
        self.assertEqual(await health(), {"status": "ok"})
        self.assertIn("/health", app.openapi()["paths"])
