from __future__ import annotations

import os
from unittest import TestCase, skipUnless

from sqlalchemy import delete, func, select

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import (
    EpisodeSplitPolicy,
    EventGroup,
    EventGroupMember,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisWorkItem,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneRelation,
    SceneRelationType,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.event_grouping import (
    EventGroupingError,
    persist_relation,
    process_event_grouping,
)


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class EventGroupingIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())
        cls.factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.project_ids = []

    def tearDown(self) -> None:
        with self.factory() as session:
            for project_id in self.project_ids:
                source_ids = select(SourceVideo.id).where(SourceVideo.project_id == project_id)
                candidate_ids = select(SceneCandidate.id).where(SceneCandidate.source_video_id.in_(source_ids))
                work_ids = select(SceneAnalysisWorkItem.id).where(SceneAnalysisWorkItem.project_id == project_id)
                group_ids = select(EventGroup.id).where(EventGroup.project_id == project_id)
                session.execute(delete(EventGroupMember).where(EventGroupMember.event_group_id.in_(group_ids)))
                session.execute(delete(SceneRelation).where(SceneRelation.source_scene_candidate_id.in_(candidate_ids)))
                session.execute(delete(SceneEvidence).where(SceneEvidence.scene_candidate_id.in_(candidate_ids)))
                session.execute(delete(SceneCandidate).where(SceneCandidate.source_video_id.in_(source_ids)))
                session.execute(delete(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id.in_(work_ids)))
                session.execute(delete(SceneAnalysisWorkItem).where(SceneAnalysisWorkItem.project_id == project_id))
                session.execute(delete(EventGroup).where(EventGroup.project_id == project_id))
                session.execute(delete(SourceVideo).where(SourceVideo.project_id == project_id))
                session.execute(delete(Project).where(Project.id == project_id))
            session.commit()

    def test_postgresql_grouping_is_durable_idempotent_and_incremental(self) -> None:
        with self.factory() as session:
            project = Project(name="Grouping integration", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project)
            session.flush()
            project_id = project.id
            self.project_ids.append(project_id)
            candidates = []
            for index in range(4):
                source = SourceVideo(
                    project_id=project.id,
                    original_filename=f"source-{index}.mov",
                    storage_reference=f"projects/integration/source-{index}.mov",
                    fingerprint="duplicate-source" if index < 2 else f"source-{index}",
                    fingerprint_algorithm="sha256",
                    duration_seconds=30,
                    processing_status=SourceVideoStatus.COMPLETED,
                )
                session.add(source)
                session.flush()
                candidate = SceneCandidate(
                    source_video_id=source.id,
                    start_seconds=10,
                    end_seconds=15,
                    discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                    input_fingerprint=f"input-{index}",
                    result_fingerprint=f"result-{index}",
                )
                session.add(candidate)
                session.flush()
                candidates.append(candidate)
            persist_relation(
                session, project.id, candidates[2].id, candidates[3].id,
                SceneRelationType.SAME_EVENT,
                producer="synthetic-integration-fixture", producer_version="v1",
            )
            session.commit()

            first = process_event_grouping(session, project_id)
            repeated = process_event_grouping(session, project_id)
            self.assertTrue(repeated.reused)
            self.assertEqual(session.scalar(select(func.count(SceneRelation.id))), 2)
            self.assertEqual(session.scalar(select(func.count(EventGroup.id))), 1)
            self.assertEqual(session.scalar(select(func.count(EventGroupMember.id))), 2)

            new_source = SourceVideo(
                project_id=project.id,
                original_filename="new.mov",
                storage_reference="projects/integration/new.mov",
                fingerprint="new-source",
                fingerprint_algorithm="sha256",
                duration_seconds=30,
                processing_status=SourceVideoStatus.COMPLETED,
            )
            session.add(new_source)
            session.flush()
            new_candidate = SceneCandidate(
                source_video_id=new_source.id,
                start_seconds=5,
                end_seconds=8,
                discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                input_fingerprint="new-input",
                result_fingerprint="new-result",
            )
            session.add(new_candidate)
            session.commit()
            incremental = process_event_grouping(
                session, project_id, focus_candidate_ids=(new_candidate.id,)
            )
            self.assertEqual(incremental.possible_pair_count, 4)
            self.assertIn(new_candidate.id, incremental.unassigned_candidate_ids)

            other_project = Project(name="Other", split_policy=EpisodeSplitPolicy.SINGLE)
            other_source = SourceVideo(
                project=other_project,
                original_filename="other.mov",
                storage_reference="projects/other/source.mov",
                fingerprint="other",
                fingerprint_algorithm="sha256",
                processing_status=SourceVideoStatus.COMPLETED,
            )
            other_candidate = SceneCandidate(
                source_video=other_source,
                start_seconds=1,
                end_seconds=2,
                discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                input_fingerprint="other",
            )
            session.add_all([other_project, other_source, other_candidate])
            session.flush()
            self.project_ids.append(other_project.id)
            with self.assertRaises(EventGroupingError):
                persist_relation(
                    session, project_id, candidates[0].id, other_candidate.id,
                    SceneRelationType.SAME_EVENT,
                    producer="test", producer_version="v1",
                )
            session.rollback()

        with self.factory() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count(EventGroup.id)).where(EventGroup.project_id == project_id)
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(SceneRelation.id))
                    .join(SceneCandidate, SceneRelation.source_scene_candidate_id == SceneCandidate.id)
                    .join(SourceVideo, SceneCandidate.source_video_id == SourceVideo.id)
                    .where(SourceVideo.project_id == project_id)
                ),
                2,
            )

    def test_postgresql_500_candidate_pair_reduction_does_not_materialize_all_pairs(self) -> None:
        with self.factory() as session:
            project = Project(name="Grouping scale", split_policy=EpisodeSplitPolicy.SINGLE)
            source = SourceVideo(
                project=project,
                original_filename="scale.mov",
                storage_reference="projects/integration/scale.mov",
                fingerprint="scale-source",
                fingerprint_algorithm="sha256",
                duration_seconds=1_000,
                processing_status=SourceVideoStatus.COMPLETED,
            )
            session.add_all([project, source])
            session.flush()
            self.project_ids.append(project.id)
            candidates = []
            for index in range(500):
                candidate = SceneCandidate(
                    source_video_id=source.id,
                    start_seconds=index * 1.5,
                    end_seconds=index * 1.5 + 1,
                    discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                    input_fingerprint=f"scale-input-{index}",
                    result_fingerprint=f"scale-result-{index}",
                )
                session.add(candidate)
                candidates.append(candidate)
            session.commit()

            result = process_event_grouping(session, project.id)
            self.assertEqual(result.candidate_count, 500)
            self.assertEqual(result.possible_pair_count, 124_750)
            self.assertEqual(result.retained_pair_count, 0)
            self.assertEqual(result.event_group_ids, ())
            self.assertEqual(len(result.unassigned_candidate_ids), 500)

            new_candidate = SceneCandidate(
                source_video_id=source.id,
                start_seconds=900,
                end_seconds=901,
                discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                input_fingerprint="scale-new-input",
                result_fingerprint="scale-new-result",
            )
            session.add(new_candidate)
            session.commit()
            incremental = process_event_grouping(
                session, project.id, focus_candidate_ids=(new_candidate.id,)
            )
            self.assertEqual(incremental.possible_pair_count, 500)
            self.assertEqual(incremental.retained_pair_count, 0)
