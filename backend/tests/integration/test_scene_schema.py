from __future__ import annotations

from datetime import datetime, timezone
import os
from unittest import TestCase, skipUnless

from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import (
    EpisodeSplitPolicy,
    EventGroup,
    EventGroupMember,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SceneRelation,
    SceneRelationType,
    SourceVideo,
    SourceVideoStatus,
)


SCENE_TABLES = {
    "scene_candidates",
    "scene_evidences",
    "scene_relations",
    "event_groups",
    "event_group_members",
    "scene_analysis_work_items",
    "scene_analysis_attempts",
}


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class SceneSchemaIntegrationTests(TestCase):
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
                source_ids = select(SourceVideo.id).where(
                    SourceVideo.project_id == project_id
                )
                candidate_ids = select(SceneCandidate.id).where(
                    SceneCandidate.source_video_id.in_(source_ids)
                )
                work_ids = select(SceneAnalysisWorkItem.id).where(
                    SceneAnalysisWorkItem.project_id == project_id
                )
                group_ids = select(EventGroup.id).where(
                    EventGroup.project_id == project_id
                )
                session.execute(
                    delete(EventGroupMember).where(
                        EventGroupMember.event_group_id.in_(group_ids)
                    )
                )
                session.execute(
                    delete(SceneRelation).where(
                        SceneRelation.source_scene_candidate_id.in_(candidate_ids)
                    )
                )
                session.execute(
                    delete(SceneEvidence).where(
                        SceneEvidence.scene_candidate_id.in_(candidate_ids)
                    )
                )
                session.execute(
                    delete(SceneCandidate).where(
                        SceneCandidate.source_video_id.in_(source_ids)
                    )
                )
                session.execute(
                    delete(SceneAnalysisAttempt).where(
                        SceneAnalysisAttempt.work_item_id.in_(work_ids)
                    )
                )
                session.execute(
                    delete(SceneAnalysisWorkItem).where(
                        SceneAnalysisWorkItem.project_id == project_id
                    )
                )
                session.execute(
                    delete(EventGroup).where(EventGroup.project_id == project_id)
                )
                session.execute(
                    delete(SourceVideo).where(SourceVideo.project_id == project_id)
                )
                session.execute(delete(Project).where(Project.id == project_id))
            session.commit()

    def test_schema_constraints_foreign_keys_and_indexes_exist(self) -> None:
        inspector = inspect(self.engine)
        self.assertTrue(SCENE_TABLES <= set(inspector.get_table_names()))

        candidate_foreign_keys = _foreign_key_targets(inspector, "scene_candidates")
        self.assertEqual(
            candidate_foreign_keys,
            {
                (("source_video_id",), "source_videos"),
                (("analysis_work_item_id",), "scene_analysis_work_items"),
            },
        )
        relation_foreign_keys = _foreign_key_targets(inspector, "scene_relations")
        self.assertEqual(
            relation_foreign_keys,
            {
                (("source_scene_candidate_id",), "scene_candidates"),
                (("target_scene_candidate_id",), "scene_candidates"),
            },
        )

        relation_uniques = _unique_sets(inspector, "scene_relations")
        membership_uniques = _unique_sets(inspector, "event_group_members")
        attempt_uniques = _unique_sets(inspector, "scene_analysis_attempts")
        self.assertIn(
            ("source_scene_candidate_id", "target_scene_candidate_id", "relation_type"),
            relation_uniques,
        )
        self.assertIn(("event_group_id", "scene_candidate_id"), membership_uniques)
        self.assertIn(("work_item_id", "attempt_number"), attempt_uniques)

        expected_indexes = {
            "scene_candidates": {
                "ix_scene_candidates_source_video_id",
                "ix_scene_candidates_source_discovery",
                "ix_scene_candidates_source_interval",
            },
            "scene_evidences": {
                "ix_scene_evidences_candidate_id",
                "ix_scene_evidences_modality_type",
            },
            "scene_analysis_work_items": {
                "ix_scene_work_items_project_id",
                "ix_scene_work_items_source_work_type",
                "ix_scene_work_items_status",
            },
        }
        for table_name, expected in expected_indexes.items():
            actual = {item["name"] for item in inspector.get_indexes(table_name)}
            self.assertTrue(expected <= actual)

    def test_complete_scene_product_graph_survives_commit_and_reload(self) -> None:
        with self.factory() as session:
            project, source, work, first, second = _graph()
            session.add_all([project, source, work, first, second])
            session.flush()
            self.project_ids.append(project.id)
            evidence = SceneEvidence(
                scene_candidate=first,
                modality=SceneEvidenceModality.MEMO,
                evidence_type="USER_MEMO",
                start_seconds=10.0,
                end_seconds=15.0,
                confidence=0.9,
                payload={"memo_id": "opaque-memo-id"},
                producer="memo-guided-baseline",
                producer_version="v1",
                input_fingerprint="source-input",
            )
            relation = SceneRelation(
                source_scene_candidate=first,
                target_scene_candidate=second,
                relation_type=SceneRelationType.CONTINUATION,
                confidence=0.8,
                producer="relation-baseline",
                producer_version="v1",
            )
            group = EventGroup(
                project=project,
                label="Arrival",
                producer="grouping-baseline",
                producer_version="v1",
                members=[
                    EventGroupMember(scene_candidate=first),
                    EventGroupMember(scene_candidate=second),
                ],
            )
            attempt = SceneAnalysisAttempt(
                work_item=work,
                attempt_number=1,
                status=SceneAnalysisAttemptStatus.COMPLETED,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add_all([evidence, relation, group, attempt])
            session.commit()
            ids = (first.id, evidence.id, relation.id, group.id, work.id, attempt.id)

        with self.factory() as session:
            candidate = session.get(SceneCandidate, ids[0])
            evidence = session.get(SceneEvidence, ids[1])
            relation = session.get(SceneRelation, ids[2])
            group = session.get(EventGroup, ids[3])
            work = session.get(SceneAnalysisWorkItem, ids[4])
            attempt = session.get(SceneAnalysisAttempt, ids[5])
            self.assertEqual(candidate.discovery_method, SceneDiscoveryMethod.MEMO_GUIDED)
            self.assertEqual(evidence.payload, {"memo_id": "opaque-memo-id"})
            self.assertEqual(relation.target_scene_candidate_id, second.id)
            self.assertEqual(len(group.members), 2)
            self.assertEqual(work.source_video_id, source.id)
            self.assertEqual(attempt.attempt_number, 1)

    def test_postgresql_rejects_invalid_scene_rows_and_remains_usable(self) -> None:
        with self.factory() as session:
            project, source, work, first, second = _graph()
            session.add_all([project, source, work, first, second])
            session.commit()
            self.project_ids.append(project.id)

            invalid_rows = (
                SceneCandidate(
                    source_video_id=source.id,
                    start_seconds=5.0,
                    end_seconds=5.0,
                    discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                    input_fingerprint="invalid",
                ),
                SceneCandidate(
                    source_video_id=source.id,
                    start_seconds=5.0,
                    end_seconds=6.0,
                    discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                    confidence=-0.1,
                    input_fingerprint="invalid",
                ),
                SceneRelation(
                    source_scene_candidate_id=first.id,
                    target_scene_candidate_id=first.id,
                    relation_type=SceneRelationType.DUPLICATE,
                    producer="test",
                    producer_version="v1",
                ),
                SceneAnalysisAttempt(
                    work_item_id=work.id,
                    attempt_number=0,
                    status=SceneAnalysisAttemptStatus.RUNNING,
                    started_at=datetime.now(timezone.utc),
                ),
            )
            for row in invalid_rows:
                with self.assertRaises(IntegrityError):
                    with session.begin_nested():
                        session.add(row)
                        session.flush()

            relation = SceneRelation(
                source_scene_candidate_id=first.id,
                target_scene_candidate_id=second.id,
                relation_type=SceneRelationType.SAME_EVENT,
                producer="test",
                producer_version="v1",
            )
            session.add(relation)
            session.flush()
            for duplicate in (
                SceneRelation(
                    source_scene_candidate_id=first.id,
                    target_scene_candidate_id=second.id,
                    relation_type=SceneRelationType.SAME_EVENT,
                    producer="test",
                    producer_version="v1",
                ),
                EventGroupMember(
                    event_group=EventGroup(
                        project_id=project.id,
                        producer="test",
                        producer_version="v1",
                    ),
                    scene_candidate_id=first.id,
                ),
            ):
                if isinstance(duplicate, EventGroupMember):
                    session.add(duplicate)
                    session.flush()
                    second_membership = EventGroupMember(
                        event_group_id=duplicate.event_group_id,
                        scene_candidate_id=first.id,
                    )
                    with self.assertRaises(IntegrityError):
                        with session.begin_nested():
                            session.add(second_membership)
                            session.flush()
                else:
                    with self.assertRaises(IntegrityError):
                        with session.begin_nested():
                            session.add(duplicate)
                            session.flush()

            attempt = SceneAnalysisAttempt(
                work_item_id=work.id,
                attempt_number=1,
                status=SceneAnalysisAttemptStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            session.add(attempt)
            session.flush()
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(
                        SceneAnalysisAttempt(
                            work_item_id=work.id,
                            attempt_number=1,
                            status=SceneAnalysisAttemptStatus.RUNNING,
                            started_at=datetime.now(timezone.utc),
                        )
                    )
                    session.flush()

            self.assertEqual(session.scalar(select(Project.id).where(Project.id == project.id)), project.id)


def _graph():
    project = Project(name="Scene Integration", split_policy=EpisodeSplitPolicy.SINGLE)
    source = SourceVideo(
        project=project,
        original_filename="scene.mov",
        storage_reference="projects/scene/sources/opaque.mov",
        fingerprint="source-input",
        fingerprint_algorithm="sha256",
        duration_seconds=30.0,
        processing_status=SourceVideoStatus.COMPLETED,
    )
    work = SceneAnalysisWorkItem(
        project=project,
        source_video=source,
        work_type="MEMO_GUIDED_DISCOVERY",
        status=SceneAnalysisWorkStatus.COMPLETED,
        input_fingerprint="source-input",
        producer="memo-guided-baseline",
        producer_version="v1",
    )
    first = SceneCandidate(
        source_video=source,
        analysis_work_item=work,
        start_seconds=10.0,
        end_seconds=15.0,
        discovery_method=SceneDiscoveryMethod.MEMO_GUIDED,
        confidence=0.9,
        input_fingerprint="source-input",
        result_fingerprint="candidate-one",
    )
    second = SceneCandidate(
        source_video=source,
        start_seconds=15.0,
        end_seconds=20.0,
        discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
        input_fingerprint="source-input",
        result_fingerprint="candidate-two",
    )
    return project, source, work, first, second


def _foreign_key_targets(inspector, table_name: str):
    return {
        (tuple(item["constrained_columns"]), item["referred_table"])
        for item in inspector.get_foreign_keys(table_name)
    }


def _unique_sets(inspector, table_name: str):
    return {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints(table_name)
    }
