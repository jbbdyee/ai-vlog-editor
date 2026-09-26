from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


RUN_ID = "a" * 32
CLIP_ID = "b" * 32
CLIP_BYTES = b"fake-mp4-content"


class ClipDownloadAPITests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = self.enterContext(TemporaryDirectory())
        self.output_root = Path(self.temporary_directory) / "outputs" / "api"
        self.output_root.mkdir(parents=True)

        self.load_model_patcher = patch("app.main.load_model", return_value=object())
        self.load_model_patcher.start()
        self.addCleanup(self.load_model_patcher.stop)
        self.output_patcher = patch(
            "app.routers.videos.PROCESS_OUTPUT_DIRECTORY", self.output_root
        )
        self.output_patcher.start()
        self.addCleanup(self.output_patcher.stop)

        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_downloads_generated_mp4_with_safe_headers(self) -> None:
        clip_path = self._write_clip()

        response = self.client.get(f"/videos/clips/{RUN_ID}/{CLIP_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "video/mp4")
        self.assertTrue(response.headers["content-disposition"].startswith("inline;"))
        self.assertIn(f'{CLIP_ID}.mp4', response.headers["content-disposition"])
        self.assertEqual(response.content, CLIP_BYTES)
        self.assertNotIn(str(clip_path), response.text)

    def test_missing_run_returns_safe_404(self) -> None:
        response = self.client.get(f"/videos/clips/{'c' * 32}/{CLIP_ID}")
        self._assert_not_found(response)

    def test_missing_clip_returns_safe_404(self) -> None:
        (self.output_root / RUN_ID / "clips").mkdir(parents=True)
        response = self.client.get(f"/videos/clips/{RUN_ID}/{CLIP_ID}")
        self._assert_not_found(response)

    def test_invalid_run_id_returns_422(self) -> None:
        response = self.client.get(f"/videos/clips/not-a-uuid/{CLIP_ID}")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["field"], "run_id")

    def test_invalid_clip_id_and_extension_injection_return_422(self) -> None:
        for clip_id in ("not-a-uuid", f"{CLIP_ID}.env", CLIP_ID.upper()):
            with self.subTest(clip_id=clip_id):
                response = self.client.get(f"/videos/clips/{RUN_ID}/{clip_id}")
                self.assertEqual(response.status_code, 422)

    def test_encoded_traversal_and_slashes_are_rejected(self) -> None:
        attack_paths = (
            f"/videos/clips/{RUN_ID}/%2E%2E%2F.env",
            f"/videos/clips/{RUN_ID}/..%5C.env",
            f"/videos/clips/{RUN_ID}/{CLIP_ID}%2Fetc",
            f"/videos/clips/{RUN_ID}/{CLIP_ID}%5C.env",
        )
        for path in attack_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 422)

    def test_absolute_path_input_is_rejected(self) -> None:
        response = self.client.get(f"/videos/clips/{RUN_ID}/%2Fetc%2Fpasswd")
        self.assertEqual(response.status_code, 422)

    def test_symlink_escape_is_not_served(self) -> None:
        outside = Path(self.temporary_directory) / "outside.mp4"
        outside.write_bytes(b"secret")
        clip_path = self.output_root / RUN_ID / "clips" / f"{CLIP_ID}.mp4"
        clip_path.parent.mkdir(parents=True)
        clip_path.symlink_to(outside)

        response = self.client.get(f"/videos/clips/{RUN_ID}/{CLIP_ID}")

        self._assert_not_found(response)
        self.assertNotIn(str(outside), response.text)

    def test_non_mp4_file_is_not_served(self) -> None:
        directory = self.output_root / RUN_ID / "clips"
        directory.mkdir(parents=True)
        (directory / f"{CLIP_ID}.wav").write_bytes(b"audio")

        response = self.client.get(f"/videos/clips/{RUN_ID}/{CLIP_ID}")

        self._assert_not_found(response)

    def test_files_outside_clip_root_are_not_addressable(self) -> None:
        (self.output_root / ".env").write_text("SECRET=value", encoding="utf-8")
        upload = Path(self.temporary_directory) / "uploads" / f"{CLIP_ID}.mp4"
        upload.parent.mkdir()
        upload.write_bytes(b"source")

        responses = (
            self.client.get(f"/videos/clips/{RUN_ID}/%2E%2E%2F%2Eenv"),
            self.client.get(f"/videos/clips/{RUN_ID}/%2E%2E%2F%2E%2E%2Fuploads%2F{CLIP_ID}"),
        )

        for response in responses:
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("SECRET=value", response.text)
            self.assertNotEqual(response.content, b"source")

    def _write_clip(self) -> Path:
        clip_path = self.output_root / RUN_ID / "clips" / f"{CLIP_ID}.mp4"
        clip_path.parent.mkdir(parents=True)
        clip_path.write_bytes(CLIP_BYTES)
        return clip_path

    def _assert_not_found(self, response) -> None:
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            {
                "code": "CLIP_NOT_FOUND",
                "message": "Rendered clip was not found.",
            },
        )
