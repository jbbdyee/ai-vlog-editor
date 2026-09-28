from pathlib import Path
import shutil
from uuid import UUID


class ProcessingWorkspaceError(RuntimeError):
    """Raised when a source-owned temporary workspace cannot be managed."""


class LocalProcessingWorkspace:
    """Own temporary artifacts under a Project and SourceVideo namespace."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def audio_directory(self, *, project_id: UUID, source_video_id: UUID) -> Path:
        source_directory = self._source_directory(project_id, source_video_id)
        audio_directory = source_directory / "audio"
        try:
            audio_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ProcessingWorkspaceError(
                "Could not prepare the source audio workspace."
            ) from error
        return audio_directory

    def cleanup_source(self, *, project_id: UUID, source_video_id: UUID) -> None:
        source_directory = self._source_directory(project_id, source_video_id)
        try:
            shutil.rmtree(source_directory, ignore_errors=False)
        except FileNotFoundError:
            return
        except OSError as error:
            raise ProcessingWorkspaceError(
                "Could not clean the source temporary workspace."
            ) from error

    def _source_directory(self, project_id: UUID, source_video_id: UUID) -> Path:
        directory = (
            self._root
            / "projects"
            / project_id.hex
            / "sources"
            / source_video_id.hex
        ).resolve()
        try:
            directory.relative_to(self._root)
        except ValueError as error:
            raise ProcessingWorkspaceError(
                "Source temporary workspace escapes its root."
            ) from error
        return directory
