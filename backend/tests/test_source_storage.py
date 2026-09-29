from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from backend.app.services.video_storage import VideoValidationError
from backend.app.storage.source_storage import (
    FINGERPRINT_ALGORITHM,
    InvalidSourceReference,
    LocalSourceStorage,
)


class LocalSourceStorageTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "originals"
        self.storage = LocalSourceStorage(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_stores_under_project_namespace_and_calculates_sha256(self) -> None:
        project_id = uuid4()
        content = _video_bytes(b"source-content")

        stored = self.storage.store(
            project_id=project_id,
            file_object=BytesIO(content),
            original_filename="../../holiday.MOV",
            content_type="video/quicktime",
        )

        self.assertEqual(stored.original_filename, "../../holiday.MOV")
        self.assertEqual(stored.fingerprint_algorithm, FINGERPRINT_ALGORITHM)
        self.assertEqual(stored.fingerprint, sha256(content).hexdigest())
        self.assertRegex(
            stored.resource_reference,
            rf"^projects/{project_id.hex}/sources/[0-9a-f]{{32}}\.mov$",
        )
        self.assertFalse(Path(stored.resource_reference).is_absolute())
        self.assertNotIn(str(self.root), stored.resource_reference)
        self.assertTrue(self.storage.exists(stored.resource_reference))
        stored_path = self.storage.resolve(stored.resource_reference)
        self.assertTrue(stored_path.is_relative_to(self.root))
        self.assertEqual(stored_path.read_bytes(), content)
        self.assertEqual(
            self.storage.fingerprint(stored.resource_reference),
            stored.fingerprint,
        )

        self.storage.delete(stored.resource_reference)
        self.assertFalse(self.storage.exists(stored.resource_reference))

    def test_existing_validation_rejects_unsupported_or_invalid_content(self) -> None:
        cases = (
            ("source.avi", "video/x-msvideo", _video_bytes()),
            ("source.mp4", "video/mp4", b"not-a-video"),
            ("source.mov", "video/mp4", _video_bytes()),
        )
        for filename, content_type, content in cases:
            with self.subTest(filename=filename, content_type=content_type):
                with self.assertRaises(VideoValidationError):
                    self.storage.store(
                        project_id=uuid4(),
                        file_object=BytesIO(content),
                        original_filename=filename,
                        content_type=content_type,
                    )

        self.assertEqual(list(self.root.rglob("*")) if self.root.exists() else [], [])

    def test_reference_validation_blocks_absolute_and_traversal_paths(self) -> None:
        for reference in (
            "../outside.mp4",
            "C:/outside.mp4",
            "/outside.mp4",
            "projects/not-a-uuid/sources/source.mp4",
        ):
            with self.subTest(reference=reference):
                with self.assertRaises(InvalidSourceReference):
                    self.storage.exists(reference)


def _video_bytes(payload: bytes = b"payload") -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + payload
