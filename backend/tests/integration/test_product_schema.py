import os
from unittest import TestCase, skipUnless

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, DatabaseSettings
from backend.app.database import create_database_engine
from backend.app.models import (
    EditMemo,
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)


EXPECTED_PRODUCT_TABLES = {
    "projects",
    "source_videos",
    "processing_stages",
    "transcripts",
    "edit_memos",
}


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class ProductSchemaIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection)

    def tearDown(self) -> None:
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def test_database_is_at_alembic_head_with_product_tables(self) -> None:
        config = Config(PROJECT_ROOT / "alembic.ini")
        expected_head = ScriptDirectory.from_config(config).get_current_head()
        actual_revision = MigrationContext.configure(
            self.connection
        ).get_current_revision()
        table_names = set(inspect(self.connection).get_table_names())

        self.assertEqual(actual_revision, expected_head)
        self.assertTrue(EXPECTED_PRODUCT_TABLES <= table_names)

    def test_expected_foreign_keys_unique_rule_and_indexes_exist(self) -> None:
        inspector = inspect(self.connection)
        foreign_key_targets = {
            table_name: {
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            }
            for table_name in EXPECTED_PRODUCT_TABLES
        }
        self.assertIn((('project_id',), "projects"), foreign_key_targets["source_videos"])
        self.assertIn(
            (("source_video_id",), "source_videos"),
            foreign_key_targets["processing_stages"],
        )
        self.assertIn(
            (("source_video_id",), "source_videos"),
            foreign_key_targets["transcripts"],
        )
        self.assertEqual(
            foreign_key_targets["edit_memos"],
            {
                (("source_video_id",), "source_videos"),
                (("transcript_id",), "transcripts"),
            },
        )

        stage_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("processing_stages")
        }
        self.assertIn(("source_video_id", "stage"), stage_uniques)

        expected_indexes = {
            "projects": {"ix_projects_status"},
            "source_videos": {
                "ix_source_videos_project_id",
                "ix_source_videos_processing_status",
            },
            "processing_stages": {
                "ix_processing_stages_source_video_id",
                "ix_processing_stages_status",
            },
            "edit_memos": {
                "ix_edit_memos_source_video_id",
                "ix_edit_memos_transcript_id",
            },
        }
        for table_name, index_names in expected_indexes.items():
            actual_indexes = {
                index["name"] for index in inspector.get_indexes(table_name)
            }
            self.assertTrue(index_names <= actual_indexes)

    def test_basic_product_graph_can_be_inserted(self) -> None:
        project, source, stage, transcript, memo = _product_graph()
        self.session.add_all([project, source, stage, transcript, memo])
        self.session.flush()

        self.assertIsNotNone(project.id)
        self.assertEqual(source.project_id, project.id)
        self.assertEqual(stage.source_video_id, source.id)
        self.assertEqual(transcript.source_video_id, source.id)
        self.assertEqual(memo.transcript_id, transcript.id)

    def test_database_rejects_duplicate_stage_and_invalid_memo_range(self) -> None:
        project, source, stage, transcript, memo = _product_graph()
        self.session.add_all([project, source, stage, transcript, memo])
        self.session.flush()

        with self.assertRaises(IntegrityError):
            with self.session.begin_nested():
                self.session.add(
                    ProcessingStage(
                        source_video_id=source.id,
                        stage=stage.stage,
                        status=ProcessingStageStatus.RUNNING,
                    )
                )
                self.session.flush()

        with self.assertRaises(IntegrityError):
            with self.session.begin_nested():
                self.session.add(
                    EditMemo(
                        source_video_id=source.id,
                        transcript_id=transcript.id,
                        start_seconds=8.0,
                        end_seconds=7.0,
                        transcript_text="invalid",
                        matched_trigger="AI야",
                        matched_reference="방금",
                        matched_action="살려줘",
                        trigger_match_type="normalized_exact",
                        trigger_similarity=1.0,
                    )
                )
                self.session.flush()


def _product_graph() -> tuple[
    Project, SourceVideo, ProcessingStage, Transcript, EditMemo
]:
    project = Project(
        name="Integration Project", split_policy=EpisodeSplitPolicy.SINGLE
    )
    source = SourceVideo(
        project=project,
        original_filename="source.mov",
        storage_reference="sources/opaque-source-id",
        fingerprint="fixture-fingerprint",
        fingerprint_algorithm="test-fixture",
        duration_seconds=21.0,
        video_codec="hevc",
        audio_codec="aac",
        format_name="mov,mp4",
        width=1920,
        height=1080,
        fps=30.0,
        processing_status=SourceVideoStatus.READY,
    )
    stage = ProcessingStage(
        source_video=source,
        stage=ProcessingStageKind.STT,
        status=ProcessingStageStatus.COMPLETED,
        attempt_count=1,
        input_fingerprint="fixture-fingerprint",
        config_version="stt-config-v1",
        tool_version="faster-whisper-small",
        result_version="transcript-v1",
    )
    transcript = Transcript(
        source_video=source,
        text="AI야 방금 장면 꼭 살려줘",
        language="ko",
        language_probability=1.0,
        segments=[
            {
                "start_seconds": 15.8,
                "end_seconds": 18.72,
                "text": "AI야 방금 장면 꼭 살려줘",
                "words": [],
            }
        ],
    )
    memo = EditMemo(
        source_video=source,
        transcript=transcript,
        start_seconds=15.8,
        end_seconds=18.72,
        transcript_text="AI야 방금 장면 꼭 살려줘",
        matched_trigger="AI야",
        matched_reference="방금",
        matched_action="살려줘",
        trigger_match_type="normalized_exact",
        trigger_similarity=1.0,
    )
    return project, source, stage, transcript, memo
