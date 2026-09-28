import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine
from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.source_ingestion import ingest_source
from backend.app.storage.source_storage import LocalSourceStorage


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class SourceIngestionIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, expire_on_commit=False)
        self.temporary_directory = TemporaryDirectory()
        self.storage = LocalSourceStorage(
            Path(self.temporary_directory.name) / "originals"
        )
        self.project = Project(
            name="Source Ingestion Integration",
            split_policy=EpisodeSplitPolicy.SINGLE,
        )
        self.session.add(self.project)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.transaction.rollback()
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_real_postgresql_persists_source_lineage_and_pending_stages(self) -> None:
        content = _video_bytes()
        result = ingest_source(
            session=self.session,
            storage=self.storage,
            project_id=self.project.id,
            file_object=BytesIO(content),
            original_filename="camera-source.mp4",
            content_type="video/mp4",
        )

        source = self.session.get(SourceVideo, result.source_video_id)
        stages = self.session.scalars(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == result.source_video_id
            )
        ).all()

        self.assertIsNotNone(source)
        self.assertEqual(source.project_id, self.project.id)
        self.assertEqual(source.original_filename, "camera-source.mp4")
        self.assertEqual(source.storage_reference, result.resource_reference)
        self.assertEqual(source.fingerprint, sha256(content).hexdigest())
        self.assertEqual(source.fingerprint_algorithm, "sha256")
        self.assertEqual(source.processing_status, SourceVideoStatus.READY)
        self.assertTrue(self.storage.exists(source.storage_reference))
        self.assertFalse(Path(source.storage_reference).is_absolute())
        self.assertEqual({stage.stage for stage in stages}, set(ProcessingStageKind))
        self.assertEqual(
            {stage.status for stage in stages}, {ProcessingStageStatus.PENDING}
        )

    def test_real_postgresql_keeps_same_project_duplicates_as_separate_sources(self) -> None:
        results = [
            ingest_source(
                session=self.session,
                storage=self.storage,
                project_id=self.project.id,
                file_object=BytesIO(_video_bytes()),
                original_filename=f"source-{index}.mp4",
                content_type="video/mp4",
            )
            for index in range(2)
        ]

        sources = self.session.scalars(
            select(SourceVideo).where(SourceVideo.project_id == self.project.id)
        ).all()
        self.assertFalse(results[0].duplicate_fingerprint_in_project)
        self.assertTrue(results[1].duplicate_fingerprint_in_project)
        self.assertEqual(len(sources), 2)
        self.assertEqual(len({source.storage_reference for source in sources}), 2)


def _video_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypisompostgresql-fixture"
