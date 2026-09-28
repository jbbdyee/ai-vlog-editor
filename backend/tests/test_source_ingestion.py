from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import Base
from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.source_ingestion import (
    ProjectNotFoundError,
    SourceIngestionPersistenceError,
    ingest_source,
)
from backend.app.services.video_storage import VideoValidationError
from backend.app.storage.source_storage import (
    LocalSourceStorage,
    SourceStorageError,
    StoredSource,
)


class SourceIngestionTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.factory()
        self.project = Project(
            name="Ingestion Project", split_policy=EpisodeSplitPolicy.SINGLE
        )
        self.session.add(self.project)
        self.session.commit()
        self.temporary_directory = TemporaryDirectory()
        self.storage_root = Path(self.temporary_directory.name) / "originals"
        self.storage = LocalSourceStorage(self.storage_root)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_valid_source_is_stored_and_persisted_without_local_path_exposure(self) -> None:
        result = self._ingest(
            original_filename="../camera/eval_01.MOV",
            content_type="video/quicktime",
        )
        source = self.session.get(SourceVideo, result.source_video_id)

        self.assertIsNotNone(source)
        self.assertEqual(source.project_id, self.project.id)
        self.assertEqual(source.original_filename, "../camera/eval_01.MOV")
        self.assertEqual(source.storage_reference, result.resource_reference)
        self.assertEqual(source.fingerprint, result.fingerprint)
        self.assertEqual(source.fingerprint_algorithm, "sha256")
        self.assertEqual(source.processing_status, SourceVideoStatus.READY)
        self.assertTrue(self.storage.exists(result.resource_reference))
        self.assertFalse(Path(result.resource_reference).is_absolute())
        self.assertNotIn(str(self.storage_root), repr(result))

        stage_rows = self.session.scalars(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == source.id
            )
        ).all()
        self.assertEqual({row.stage for row in stage_rows}, set(ProcessingStageKind))
        self.assertEqual(
            {row.status for row in stage_rows}, {ProcessingStageStatus.PENDING}
        )

    def test_invalid_project_is_rejected_before_storage(self) -> None:
        storage = Mock()
        with self.assertRaises(ProjectNotFoundError):
            ingest_source(
                session=self.session,
                storage=storage,
                project_id=uuid4(),
                file_object=BytesIO(_video_bytes()),
                original_filename="source.mp4",
                content_type="video/mp4",
            )

        storage.store.assert_not_called()
        self.assertEqual(self._source_count(), 0)

    def test_invalid_source_creates_no_database_row(self) -> None:
        with self.assertRaises(VideoValidationError):
            self._ingest(
                original_filename="source.txt",
                content_type="text/plain",
                content=b"not-video",
            )

        self.assertEqual(self._source_count(), 0)

    def test_storage_failure_creates_no_database_row(self) -> None:
        storage = Mock()
        storage.store.side_effect = SourceStorageError("storage unavailable")

        with self.assertRaises(SourceStorageError):
            ingest_source(
                session=self.session,
                storage=storage,
                project_id=self.project.id,
                file_object=BytesIO(_video_bytes()),
                original_filename="source.mp4",
                content_type="video/mp4",
            )

        self.assertEqual(self._source_count(), 0)

    def test_database_failure_rolls_back_and_removes_stored_file(self) -> None:
        with patch.object(
            self.session, "commit", side_effect=SQLAlchemyError("commit failed")
        ):
            with self.assertRaises(SourceIngestionPersistenceError) as raised:
                self._ingest()

        self.assertIsNone(raised.exception.cleanup_warning)
        self.assertEqual(self._source_count(), 0)
        stored_files = [path for path in self.storage_root.rglob("*") if path.is_file()]
        self.assertEqual(stored_files, [])

    def test_cleanup_failure_is_reported_without_hiding_database_failure(self) -> None:
        storage = Mock()
        storage.store.return_value = StoredSource(
            original_filename="source.mp4",
            content_type="video/mp4",
            resource_reference=(
                f"projects/{self.project.id.hex}/sources/{uuid4().hex}.mp4"
            ),
            fingerprint="a" * 64,
        )
        storage.delete.side_effect = SourceStorageError("cleanup failed")

        with patch.object(
            self.session, "commit", side_effect=SQLAlchemyError("commit failed")
        ):
            with self.assertRaises(SourceIngestionPersistenceError) as raised:
                ingest_source(
                    session=self.session,
                    storage=storage,
                    project_id=self.project.id,
                    file_object=BytesIO(_video_bytes()),
                    original_filename="source.mp4",
                    content_type="video/mp4",
                )

        self.assertEqual(
            raised.exception.cleanup_warning,
            "Stored original source cleanup failed.",
        )
        self.assertIsInstance(raised.exception.__cause__, SQLAlchemyError)

    def test_duplicate_fingerprint_is_detected_but_not_rejected(self) -> None:
        first = self._ingest()
        second = self._ingest()

        self.assertFalse(first.duplicate_fingerprint_in_project)
        self.assertTrue(second.duplicate_fingerprint_in_project)
        self.assertNotEqual(first.source_video_id, second.source_video_id)
        self.assertNotEqual(first.resource_reference, second.resource_reference)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(self._source_count(), 2)

    def test_many_sources_can_be_registered_in_one_project(self) -> None:
        results = [
            self._ingest(content=_video_bytes(index.to_bytes(2, "big")))
            for index in range(120)
        ]

        self.assertEqual(len({result.source_video_id for result in results}), 120)
        self.assertEqual(len({result.resource_reference for result in results}), 120)
        self.assertEqual(self._source_count(), 120)
        stage_count = self.session.scalar(
            select(func.count()).select_from(ProcessingStage)
        )
        self.assertEqual(stage_count, 120 * len(ProcessingStageKind))

    def _ingest(
        self,
        *,
        original_filename: str = "source.mp4",
        content_type: str = "video/mp4",
        content: bytes | None = None,
    ):
        return ingest_source(
            session=self.session,
            storage=self.storage,
            project_id=self.project.id,
            file_object=BytesIO(_video_bytes() if content is None else content),
            original_filename=original_filename,
            content_type=content_type,
        )

    def _source_count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(SourceVideo)) or 0


def _video_bytes(payload: bytes = b"payload") -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + payload
