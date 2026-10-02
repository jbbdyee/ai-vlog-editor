from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.models import SourceVideo
from backend.app.storage.source_storage import (
    InvalidSourceReference,
    SourceStorage,
    SourceStorageError,
)


class ResourceResolutionError(RuntimeError):
    pass


class InvalidResourceInputError(ResourceResolutionError):
    pass


class ResourceNotFoundError(ResourceResolutionError):
    pass


class ResourceOwnershipError(ResourceResolutionError):
    pass


class ResourceSecurityError(ResourceResolutionError):
    pass


class ResourceUnreadableError(ResourceResolutionError):
    pass


@dataclass(frozen=True)
class ResolvedSource:
    source_video_id: UUID
    project_id: UUID
    path: Path


class SourceResourceResolver(Protocol):
    def resolve_source(
        self, source_video_id: UUID, *, expected_project_id: UUID | None = None
    ) -> ResolvedSource: ...


class DatabaseSourceResourceResolver:
    def __init__(self, *, session: Session, storage: SourceStorage) -> None:
        self._session = session
        self._storage = storage

    def resolve_source(
        self, source_video_id: UUID, *, expected_project_id: UUID | None = None
    ) -> ResolvedSource:
        if not isinstance(source_video_id, UUID):
            raise InvalidResourceInputError("source_video_id must be a UUID.")
        if expected_project_id is not None and not isinstance(expected_project_id, UUID):
            raise InvalidResourceInputError("expected_project_id must be a UUID.")

        source = self._session.get(SourceVideo, source_video_id)
        if source is None:
            raise ResourceNotFoundError("SourceVideo was not found.")
        if expected_project_id is not None and source.project_id != expected_project_id:
            raise ResourceOwnershipError("SourceVideo does not belong to the expected Project.")
        try:
            path = self._storage.resolve(source.storage_reference)
        except InvalidSourceReference as exc:
            raise ResourceSecurityError("Source resource reference is invalid.") from exc
        except SourceStorageError as exc:
            raise ResourceUnreadableError("Source resource could not be resolved.") from exc
        if not path.is_file():
            raise ResourceUnreadableError("Source resource is unavailable.")
        return ResolvedSource(source.id, source.project_id, path)


class TemporaryArtifactKind(str, Enum):
    AUDIO_WAV = "AUDIO_WAV"


@dataclass(frozen=True)
class TemporaryArtifactRef:
    artifact_id: UUID
    project_id: UUID
    source_video_id: UUID
    scope_id: UUID
    artifact_kind: TemporaryArtifactKind


@dataclass(frozen=True)
class _TemporaryArtifactRecord:
    reference: TemporaryArtifactRef
    path: Path


class TemporaryArtifactRegistry:
    """Workspace-scoped opaque ID registry; paths never cross the tool boundary."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._records: dict[UUID, _TemporaryArtifactRecord] = {}
        self._lock = RLock()

    def register(
        self,
        path: Path,
        *,
        project_id: UUID,
        source_video_id: UUID,
        scope_id: UUID,
        artifact_kind: TemporaryArtifactKind,
    ) -> TemporaryArtifactRef:
        resolved = self._validated_path(path)
        if not resolved.is_file():
            raise ResourceUnreadableError("Temporary artifact is unavailable.")
        reference = TemporaryArtifactRef(
            artifact_id=uuid4(),
            project_id=project_id,
            source_video_id=source_video_id,
            scope_id=scope_id,
            artifact_kind=artifact_kind,
        )
        with self._lock:
            self._records[reference.artifact_id] = _TemporaryArtifactRecord(reference, resolved)
        return reference

    def resolve(
        self,
        artifact_id: UUID,
        *,
        expected_project_id: UUID | None = None,
        expected_source_video_id: UUID | None = None,
        expected_scope_id: UUID | None = None,
        expected_kind: TemporaryArtifactKind | None = None,
    ) -> Path:
        if not isinstance(artifact_id, UUID):
            raise InvalidResourceInputError("artifact_id must be a UUID.")
        with self._lock:
            record = self._records.get(artifact_id)
        if record is None:
            raise ResourceNotFoundError("Temporary artifact was not found.")
        ref = record.reference
        if (
            (expected_project_id is not None and ref.project_id != expected_project_id)
            or (expected_source_video_id is not None and ref.source_video_id != expected_source_video_id)
            or (expected_scope_id is not None and ref.scope_id != expected_scope_id)
            or (expected_kind is not None and ref.artifact_kind is not expected_kind)
        ):
            raise ResourceOwnershipError("Temporary artifact ownership or scope does not match.")
        path = self._validated_path(record.path)
        if not path.is_file():
            raise ResourceUnreadableError("Temporary artifact is unavailable.")
        return path

    def cleanup(self, artifact_id: UUID) -> None:
        with self._lock:
            record = self._records.pop(artifact_id, None)
        if record is None:
            return
        path = self._validated_path(record.path)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            with self._lock:
                self._records[artifact_id] = record
            raise ResourceUnreadableError("Temporary artifact cleanup failed.") from exc

    def _validated_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ResourceSecurityError("Temporary artifact escapes its workspace.") from exc
        return resolved
