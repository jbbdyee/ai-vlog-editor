from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from backend.app.storage.processing_workspace import LocalProcessingWorkspace


class LocalProcessingWorkspaceTests(TestCase):
    def test_audio_directory_is_source_owned_and_cleanup_is_scoped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "temporary"
            workspace = LocalProcessingWorkspace(root)
            project_id = uuid4()
            first_source_id = uuid4()
            second_source_id = uuid4()

            first = workspace.audio_directory(
                project_id=project_id, source_video_id=first_source_id
            )
            second = workspace.audio_directory(
                project_id=project_id, source_video_id=second_source_id
            )
            (first / "first.wav").write_bytes(b"audio")
            (second / "second.wav").write_bytes(b"audio")

            workspace.cleanup_source(
                project_id=project_id, source_video_id=first_source_id
            )

            self.assertFalse(first.parent.exists())
            self.assertTrue((second / "second.wav").is_file())
            self.assertTrue(first.is_relative_to(root))
            self.assertTrue(second.is_relative_to(root))
