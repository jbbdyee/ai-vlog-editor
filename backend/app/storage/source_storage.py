from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from backend.app.services.video_storage import (
    COPY_BUFFER_SIZE,
    validate_video_file,
)


FINGERPRINT_ALGORITHM = "sha256"
RESOURCE_REFERENCE_PATTERN = re.compile(
    r"^projects/[0-9a-f]{32}/sources/[0-9a-f]{32}\.(?:mov|mp4)$"
)


class SourceStorageError(RuntimeError):
    """Raised when an original source cannot be safely stored or removed."""


class InvalidSourceReference(SourceStorageError):
    """Raised when a storage reference is not an internal source resource ID."""


@dataclass(frozen=True)
class StoredSource:
    original_filename: str
    content_type: str
    resource_reference: str
    fingerprint: str
    fingerprint_algorithm: str = FINGERPRINT_ALGORITHM


class SourceStorage(Protocol):
    """Minimal original-source storage contract used by product ingestion."""

    def store(
        self,
        *,
        project_id: UUID,
        file_object: BinaryIO,
        original_filename: str | None,
        content_type: str | None,
    ) -> StoredSource: ...

    def exists(self, resource_reference: str) -> bool: ...

    def resolve(self, resource_reference: str) -> Path: ...

    def fingerprint(self, resource_reference: str) -> str: ...

    def delete(self, resource_reference: str) -> None: ...


class LocalSourceStorage:
    """Store original videos under isolated project namespaces on local disk."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def store(
        self,
        *,
        project_id: UUID,
        file_object: BinaryIO,
        original_filename: str | None,
        content_type: str | None,
    ) -> StoredSource:
        extension = validate_video_file(
            file_object, original_filename, content_type
        )
        resource_id = uuid4().hex
        resource_reference = (
            f"projects/{project_id.hex}/sources/{resource_id}{extension}"
        )
        destination = self._resolve_reference(resource_reference)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fingerprint = sha256()

        try:
            file_object.seek(0)
            with destination.open("xb") as saved_file:
                while chunk := file_object.read(COPY_BUFFER_SIZE):
                    saved_file.write(chunk)
                    fingerprint.update(chunk)
        except Exception as error:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                raise SourceStorageError(
                    "Original source storage failed and partial cleanup failed."
                ) from error
            if isinstance(error, OSError):
                raise SourceStorageError("Original source storage failed.") from error
            raise

        return StoredSource(
            original_filename=original_filename,
            content_type=content_type,
            resource_reference=resource_reference,
            fingerprint=fingerprint.hexdigest(),
        )

    def exists(self, resource_reference: str) -> bool:
        return self._resolve_reference(resource_reference).is_file()

    def resolve(self, resource_reference: str) -> Path:
        """Resolve an opaque reference without weakening root-escape validation."""
        return self._resolve_reference(resource_reference)

    def fingerprint(self, resource_reference: str) -> str:
        """Explicitly re-hash an original when an integrity check is requested."""
        fingerprint = sha256()
        try:
            with self._resolve_reference(resource_reference).open("rb") as source_file:
                while chunk := source_file.read(COPY_BUFFER_SIZE):
                    fingerprint.update(chunk)
        except OSError as error:
            raise SourceStorageError(
                "Could not verify the original source fingerprint."
            ) from error
        return fingerprint.hexdigest()

    def delete(self, resource_reference: str) -> None:
        try:
            self._resolve_reference(resource_reference).unlink(missing_ok=True)
        except OSError as error:
            raise SourceStorageError("Stored original source cleanup failed.") from error

    def _resolve_reference(self, resource_reference: str) -> Path:
        if not RESOURCE_REFERENCE_PATTERN.fullmatch(resource_reference):
            raise InvalidSourceReference("Invalid original source resource reference.")

        relative_path = PurePosixPath(resource_reference)
        destination = self._root.joinpath(*relative_path.parts).resolve()
        try:
            destination.relative_to(self._root)
        except ValueError as error:
            raise InvalidSourceReference(
                "Original source resource reference escapes its storage root."
            ) from error
        return destination
