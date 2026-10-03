from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from unittest import TestCase, skipUnless

from sqlalchemy import delete, select

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import (
    EpisodeSplitPolicy,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate,
    SceneCandidate,
    SourceVideo,
)
from backend.app.services.scene_processing_state import (
    AUDIO_EVIDENCE,
    SceneWorkSpec,
    SceneWorkStateError,
    claim_scene_work,
    recover_stale_scene_work,
    start_scene_work_retry,
)


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class SceneProcessingStateIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())
        cls.factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.factory() as session:
            project = Project(name="Scene resume integration", split_policy=EpisodeSplitPolicy.SINGLE)
            source = SourceVideo(
                project=project,
                original_filename="source.mov",
                storage_reference="projects/integration/source.mov",
                fingerprint="scene-resume-source",
                fingerprint_algorithm="sha256",
            )
            session.add(project)
            session.commit()
            self.project_id = project.id
            self.source_id = source.id

    def tearDown(self) -> None:
        with self.factory() as session:
            work_ids = select(SceneAnalysisWorkItem.id).where(
                SceneAnalysisWorkItem.project_id == self.project_id
            )
            session.execute(
                delete(SceneAnalysisWorkResultCandidate).where(
                    SceneAnalysisWorkResultCandidate.work_item_id.in_(work_ids)
                )
            )
            session.execute(delete(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id.in_(work_ids)))
            session.execute(delete(SceneCandidate).where(SceneCandidate.source_video_id == self.source_id))
            session.execute(delete(SceneAnalysisWorkItem).where(SceneAnalysisWorkItem.project_id == self.project_id))
            session.execute(delete(SourceVideo).where(SourceVideo.project_id == self.project_id))
            session.execute(delete(Project).where(Project.id == self.project_id))
            session.commit()

    def test_postgresql_claim_blocks_duplicate_and_stale_retry_increments_attempt(self) -> None:
        spec = SceneWorkSpec(
            self.project_id,
            AUDIO_EVIDENCE,
            "source-input",
            "audio-config",
            "scene-resume-integration",
            "v0.1",
            self.source_id,
        )
        with self.factory() as first:
            work, _, created = claim_scene_work(first, spec)
            self.assertTrue(created)
            work_id = work.id
        with self.factory() as second:
            with self.assertRaisesRegex(SceneWorkStateError, "CONCURRENT_EXECUTION"):
                claim_scene_work(second, spec)
        with self.factory() as session:
            attempt = session.scalar(
                select(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id == work_id)
            )
            attempt.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
            session.commit()
            recover_stale_scene_work(
                session,
                work_id,
                stale_before=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            retry = start_scene_work_retry(session, work_id)
            self.assertEqual(retry.attempt_number, 2)
