from unittest import TestCase

from sqlalchemy import CheckConstraint, JSON, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import (
    EditMemo,
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)


EXPECTED_TABLES = {
    "projects",
    "source_videos",
    "processing_stages",
    "transcripts",
    "edit_memos",
    "scene_candidates",
    "scene_evidences",
    "scene_relations",
    "event_groups",
    "event_group_members",
    "scene_analysis_work_items",
    "scene_analysis_attempts",
}


class ProductModelMetadataTests(TestCase):
    def test_metadata_contains_all_current_product_tables(self) -> None:
        self.assertEqual(set(Base.metadata.tables), EXPECTED_TABLES)
        for table_name in EXPECTED_TABLES:
            table = Base.metadata.tables[table_name]
            self.assertEqual([column.name for column in table.primary_key], ["id"])

    def test_required_foreign_keys_and_nullability(self) -> None:
        expected_foreign_keys = {
            "source_videos": {("project_id", "projects.id")},
            "processing_stages": {("source_video_id", "source_videos.id")},
            "transcripts": {("source_video_id", "source_videos.id")},
            "edit_memos": {
                ("source_video_id", "source_videos.id"),
                ("transcript_id", "transcripts.id"),
            },
        }
        for table_name, expected in expected_foreign_keys.items():
            table = Base.metadata.tables[table_name]
            actual = {
                (foreign_key.parent.name, foreign_key.target_fullname)
                for foreign_key in table.foreign_keys
            }
            self.assertEqual(actual, expected)
            for column_name, _ in expected:
                self.assertFalse(table.c[column_name].nullable)

        self.assertFalse(Base.metadata.tables["projects"].c.split_policy.nullable)
        self.assertFalse(Base.metadata.tables["transcripts"].c.segments.nullable)
        self.assertIsInstance(Base.metadata.tables["transcripts"].c.segments.type, JSON)

    def test_enum_values_are_stable_and_complete(self) -> None:
        self.assertEqual(
            {value.value for value in EpisodeSplitPolicy},
            {"SINGLE", "AUTO_SPLIT", "USER_CONFIRM_SPLIT"},
        )
        self.assertEqual(
            {value.value for value in ProcessingStageKind},
            {"PROBE", "AUDIO_EXTRACTION", "STT", "MEMO_DETECTION"},
        )
        self.assertEqual(
            {value.value for value in ProcessingStageStatus},
            {"PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED"},
        )
        self.assertEqual(
            {value.value for value in ProjectStatus},
            {
                "CREATED",
                "PROCESSING",
                "COMPLETED",
                "COMPLETED_WITH_WARNINGS",
                "FAILED",
            },
        )
        self.assertEqual(
            {value.value for value in SourceVideoStatus},
            {"REGISTERED", "READY", "PROCESSING", "COMPLETED", "FAILED"},
        )

    def test_relationships_exist_without_delete_cascade(self) -> None:
        self.assertEqual(Project.source_videos.property.back_populates, "project")
        self.assertEqual(
            SourceVideo.processing_stages.property.back_populates, "source_video"
        )
        self.assertEqual(SourceVideo.transcript.property.back_populates, "source_video")
        self.assertEqual(SourceVideo.edit_memos.property.back_populates, "source_video")
        self.assertEqual(Transcript.edit_memos.property.back_populates, "transcript")

        relationships = (
            Project.source_videos,
            SourceVideo.processing_stages,
            SourceVideo.transcript,
            SourceVideo.edit_memos,
            Transcript.edit_memos,
        )
        for relationship in relationships:
            self.assertNotIn("delete", relationship.property.cascade)
            self.assertNotIn("delete-orphan", relationship.property.cascade)

    def test_current_stage_and_transcript_uniqueness_are_declared(self) -> None:
        stage_unique = _unique_column_sets("processing_stages")
        transcript_unique = _unique_column_sets("transcripts")
        self.assertIn({"source_video_id", "stage"}, stage_unique)
        self.assertIn({"source_video_id"}, transcript_unique)

    def test_fingerprint_and_result_validity_fields_are_present(self) -> None:
        source_columns = set(Base.metadata.tables["source_videos"].c.keys())
        stage_columns = set(Base.metadata.tables["processing_stages"].c.keys())
        self.assertTrue({"fingerprint", "fingerprint_algorithm"} <= source_columns)
        self.assertTrue(
            {
                "input_fingerprint",
                "config_version",
                "tool_version",
                "result_version",
                "result_reference",
                "result_fingerprint",
            }
            <= stage_columns
        )

    def test_sensitive_payload_fields_are_not_in_schema(self) -> None:
        forbidden = {
            "password",
            "api_key",
            "auth_header",
            "raw_provider_response",
            "prompt",
            "video_binary",
            "audio_binary",
        }
        all_columns = {
            column.name
            for table in Base.metadata.tables.values()
            for column in table.columns
        }
        self.assertTrue(forbidden.isdisjoint(all_columns))

    def test_named_time_and_numeric_constraints_are_declared(self) -> None:
        constraint_names = {
            constraint.name
            for table in Base.metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertTrue(
            {
                "ck_projects_target_duration_positive",
                "ck_source_videos_duration_nonnegative",
                "ck_source_videos_fingerprint_pair",
                "ck_processing_stages_attempt_nonnegative",
                "ck_transcripts_language_probability_range",
                "ck_edit_memos_start_nonnegative",
                "ck_edit_memos_time_order",
                "ck_edit_memos_trigger_similarity_range",
            }
            <= constraint_names
        )


class ProductModelConstraintTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_duplicate_current_stage_is_rejected(self) -> None:
        with Session(self.engine) as session:
            source = _source()
            session.add(source)
            session.flush()
            session.add_all(
                [
                    ProcessingStage(
                        source_video_id=source.id,
                        stage=ProcessingStageKind.STT,
                        status=ProcessingStageStatus.PENDING,
                    ),
                    ProcessingStage(
                        source_video_id=source.id,
                        stage=ProcessingStageKind.STT,
                        status=ProcessingStageStatus.RUNNING,
                    ),
                ]
            )
            with self.assertRaises(IntegrityError):
                session.flush()

    def test_invalid_edit_memo_time_range_is_rejected(self) -> None:
        with Session(self.engine) as session:
            source = _source()
            transcript = Transcript(
                source_video=source,
                text="AI야 방금 장면 꼭 살려줘",
                language="ko",
                language_probability=1.0,
                segments=[],
            )
            session.add_all([source, transcript])
            session.flush()
            session.add(
                EditMemo(
                    source_video_id=source.id,
                    transcript_id=transcript.id,
                    start_seconds=5.0,
                    end_seconds=4.0,
                    transcript_text=transcript.text,
                    matched_trigger="AI야",
                    matched_reference="방금",
                    matched_action="살려줘",
                    trigger_match_type="normalized_exact",
                    trigger_similarity=1.0,
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()

    def test_incomplete_fingerprint_pair_is_rejected(self) -> None:
        with Session(self.engine) as session:
            source = _source()
            source.fingerprint = "fingerprint-value"
            source.fingerprint_algorithm = None
            session.add(source)
            with self.assertRaises(IntegrityError):
                session.flush()


def _unique_column_sets(table_name: str) -> list[set[str]]:
    table = Base.metadata.tables[table_name]
    return [
        {column.name for column in constraint.columns}
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]


def _source() -> SourceVideo:
    return SourceVideo(
        project=Project(
            name="Unit Test Project", split_policy=EpisodeSplitPolicy.SINGLE
        ),
        original_filename="source.mov",
        storage_reference="source/opaque-id",
        processing_status=SourceVideoStatus.REGISTERED,
    )
