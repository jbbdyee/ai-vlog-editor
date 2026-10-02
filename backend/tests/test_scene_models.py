from datetime import datetime, timezone
from unittest import TestCase

from sqlalchemy import CheckConstraint, JSON, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database import Base
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


class SceneModelMetadataTests(TestCase):
    def test_scene_tables_and_primary_keys_are_registered(self) -> None:
        self.assertTrue(SCENE_TABLES <= set(Base.metadata.tables))
        for table_name in SCENE_TABLES:
            self.assertEqual(
                [column.name for column in Base.metadata.tables[table_name].primary_key],
                ["id"],
            )

    def test_foreign_keys_and_required_fields_are_declared(self) -> None:
        expected = {
            "scene_candidates": {
                ("source_video_id", "source_videos.id"),
                ("analysis_work_item_id", "scene_analysis_work_items.id"),
            },
            "scene_evidences": {
                ("scene_candidate_id", "scene_candidates.id")
            },
            "scene_relations": {
                ("source_scene_candidate_id", "scene_candidates.id"),
                ("target_scene_candidate_id", "scene_candidates.id"),
            },
            "event_groups": {("project_id", "projects.id")},
            "event_group_members": {
                ("event_group_id", "event_groups.id"),
                ("scene_candidate_id", "scene_candidates.id"),
            },
            "scene_analysis_work_items": {
                ("project_id", "projects.id"),
                ("source_video_id", "source_videos.id"),
            },
            "scene_analysis_attempts": {
                ("work_item_id", "scene_analysis_work_items.id")
            },
        }
        for table_name, expected_keys in expected.items():
            table = Base.metadata.tables[table_name]
            actual = {
                (foreign_key.parent.name, foreign_key.target_fullname)
                for foreign_key in table.foreign_keys
            }
            self.assertEqual(actual, expected_keys)

        candidate = Base.metadata.tables["scene_candidates"]
        self.assertFalse(candidate.c.source_video_id.nullable)
        self.assertTrue(candidate.c.analysis_work_item_id.nullable)
        evidence = Base.metadata.tables["scene_evidences"]
        self.assertIsInstance(evidence.c.payload.type, JSON)
        self.assertTrue(evidence.c.start_seconds.nullable)
        self.assertTrue(evidence.c.end_seconds.nullable)

    def test_enum_values_match_the_reviewed_v2_scope(self) -> None:
        self.assertEqual(
            {item.value for item in SceneDiscoveryMethod},
            {"MEMO_GUIDED", "AUTONOMOUS"},
        )
        self.assertEqual(
            {item.value for item in SceneRelationType},
            {"SAME_EVENT", "CONTINUATION", "REACTION_TO", "DUPLICATE"},
        )
        self.assertNotIn("ALTERNATIVE", {item.value for item in SceneRelationType})
        self.assertEqual(
            {item.value for item in SceneAnalysisWorkStatus},
            {"PENDING", "RUNNING", "COMPLETED", "FAILED"},
        )

    def test_named_constraints_and_uniques_are_declared(self) -> None:
        check_names = {
            constraint.name
            for table_name in SCENE_TABLES
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertTrue(
            {
                "ck_scene_candidates_start_nonnegative",
                "ck_scene_candidates_time_order",
                "ck_scene_candidates_confidence_range",
                "ck_scene_evidences_interval_pair",
                "ck_scene_evidences_confidence_range",
                "ck_scene_relations_not_self",
                "ck_scene_relations_confidence_range",
                "ck_scene_attempts_number_positive",
            }
            <= check_names
        )
        self.assertIn(
            {"source_scene_candidate_id", "target_scene_candidate_id", "relation_type"},
            _unique_sets("scene_relations"),
        )
        self.assertIn(
            {"event_group_id", "scene_candidate_id"},
            _unique_sets("event_group_members"),
        )
        self.assertIn(
            {"work_item_id", "attempt_number"},
            _unique_sets("scene_analysis_attempts"),
        )

    def test_relationships_exist_without_delete_cascade(self) -> None:
        self.assertEqual(SceneCandidate.source_video.property.back_populates, "scene_candidates")
        self.assertEqual(SceneEvidence.scene_candidate.property.back_populates, "evidences")
        self.assertEqual(EventGroup.project.property.back_populates, "event_groups")
        self.assertEqual(EventGroupMember.event_group.property.back_populates, "members")
        self.assertEqual(
            SceneAnalysisAttempt.work_item.property.back_populates, "attempts"
        )
        relationships = (
            Project.event_groups,
            Project.scene_analysis_work_items,
            SourceVideo.scene_candidates,
            SourceVideo.scene_analysis_work_items,
            SceneCandidate.evidences,
            SceneCandidate.outgoing_relations,
            SceneCandidate.incoming_relations,
            SceneCandidate.event_group_memberships,
            EventGroup.members,
            SceneAnalysisWorkItem.attempts,
        )
        for relation in relationships:
            self.assertNotIn("delete", relation.property.cascade)
            self.assertNotIn("delete-orphan", relation.property.cascade)

    def test_no_premature_or_sensitive_scene_columns_exist(self) -> None:
        all_columns = {
            column.name
            for table_name in SCENE_TABLES
            for column in Base.metadata.tables[table_name].columns
        }
        forbidden = {
            "scene_unit_id",
            "scene_role",
            "candidate_priority",
            "quality_flag_id",
            "final_scene_id",
            "raw_provider_response",
            "prompt",
            "absolute_path",
            "video_binary",
            "audio_binary",
            "api_key",
        }
        self.assertTrue(forbidden.isdisjoint(all_columns))


class SceneModelConstraintTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_scene_product_graph_can_be_persisted(self) -> None:
        with Session(self.engine) as session:
            project, source, work_item, first, second = _scene_graph()
            evidence = SceneEvidence(
                scene_candidate=first,
                modality=SceneEvidenceModality.QUALITY,
                evidence_type="LONG_SILENCE",
                payload={"duration_seconds": 3.5},
                producer="quality-baseline",
                producer_version="v1",
            )
            relation = SceneRelation(
                source_scene_candidate=first,
                target_scene_candidate=second,
                relation_type=SceneRelationType.CONTINUATION,
                producer="relation-baseline",
                producer_version="v1",
            )
            group = EventGroup(
                project=project,
                producer="grouping-baseline",
                producer_version="v1",
                members=[EventGroupMember(scene_candidate=first)],
            )
            attempt = SceneAnalysisAttempt(
                work_item=work_item,
                attempt_number=1,
                status=SceneAnalysisAttemptStatus.COMPLETED,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add_all([source, evidence, relation, group, attempt])
            session.commit()

            self.assertEqual(first.source_video_id, source.id)
            self.assertEqual(evidence.payload["duration_seconds"], 3.5)
            self.assertEqual(group.members[0].scene_candidate_id, first.id)
            self.assertEqual(attempt.work_item_id, work_item.id)

    def test_candidate_invalid_interval_and_confidence_are_rejected(self) -> None:
        with Session(self.engine) as session:
            source = _source()
            session.add(source)
            session.flush()
            for start, end, confidence in ((5.0, 5.0, None), (1.0, 2.0, 1.1)):
                with self.assertRaises(IntegrityError):
                    with session.begin_nested():
                        session.add(
                            SceneCandidate(
                                source_video_id=source.id,
                                start_seconds=start,
                                end_seconds=end,
                                discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                                confidence=confidence,
                                input_fingerprint="input",
                            )
                        )
                        session.flush()

    def test_self_and_duplicate_relations_are_rejected(self) -> None:
        with Session(self.engine) as session:
            _, source, _, first, second = _scene_graph()
            session.add(source)
            session.flush()
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(
                        SceneRelation(
                            source_scene_candidate_id=first.id,
                            target_scene_candidate_id=first.id,
                            relation_type=SceneRelationType.SAME_EVENT,
                            producer="test",
                            producer_version="v1",
                        )
                    )
                    session.flush()

            relation = SceneRelation(
                source_scene_candidate_id=first.id,
                target_scene_candidate_id=second.id,
                relation_type=SceneRelationType.REACTION_TO,
                producer="test",
                producer_version="v1",
            )
            session.add(relation)
            session.flush()
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(
                        SceneRelation(
                            source_scene_candidate_id=first.id,
                            target_scene_candidate_id=second.id,
                            relation_type=SceneRelationType.REACTION_TO,
                            producer="test",
                            producer_version="v1",
                        )
                    )
                    session.flush()

    def test_duplicate_membership_and_attempt_number_are_rejected(self) -> None:
        with Session(self.engine) as session:
            project, source, work_item, first, _ = _scene_graph()
            group = EventGroup(
                project=project,
                producer="test",
                producer_version="v1",
            )
            session.add_all([source, group])
            session.flush()
            session.add(EventGroupMember(event_group=group, scene_candidate=first))
            session.flush()
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(
                        EventGroupMember(event_group_id=group.id, scene_candidate_id=first.id)
                    )
                    session.flush()

            now = datetime.now(timezone.utc)
            session.add(
                SceneAnalysisAttempt(
                    work_item=work_item,
                    attempt_number=1,
                    status=SceneAnalysisAttemptStatus.RUNNING,
                    started_at=now,
                )
            )
            session.flush()
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(
                        SceneAnalysisAttempt(
                            work_item_id=work_item.id,
                            attempt_number=1,
                            status=SceneAnalysisAttemptStatus.RUNNING,
                            started_at=now,
                        )
                    )
                    session.flush()


def _unique_sets(table_name: str) -> list[set[str]]:
    return [
        {column.name for column in constraint.columns}
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    ]


def _source() -> SourceVideo:
    return SourceVideo(
        project=Project(name="Scene Project", split_policy=EpisodeSplitPolicy.SINGLE),
        original_filename="source.mov",
        storage_reference="projects/scene/sources/source.mov",
        processing_status=SourceVideoStatus.COMPLETED,
    )


def _scene_graph():
    source = _source()
    project = source.project
    work_item = SceneAnalysisWorkItem(
        project=project,
        source_video=source,
        work_type="MEMO_GUIDED_DISCOVERY",
        status=SceneAnalysisWorkStatus.COMPLETED,
        input_fingerprint="source-input",
        producer="scene-baseline",
        producer_version="v1",
    )
    first = SceneCandidate(
        source_video=source,
        analysis_work_item=work_item,
        start_seconds=10.0,
        end_seconds=15.0,
        discovery_method=SceneDiscoveryMethod.MEMO_GUIDED,
        input_fingerprint="source-input",
    )
    second = SceneCandidate(
        source_video=source,
        start_seconds=15.0,
        end_seconds=18.0,
        discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
        input_fingerprint="source-input",
    )
    return project, source, work_item, first, second
