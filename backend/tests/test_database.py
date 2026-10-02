from unittest import TestCase
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.config import DatabaseSettings
from backend.app.database import (
    Base,
    DatabaseConnectionError,
    check_database_connection,
    create_database_engine,
    create_session_factory,
    get_database_session,
    session_scope,
)
import backend.app.models  # noqa: F401  # Register current product metadata.


class DatabaseFoundationTests(TestCase):
    def test_postgresql_engine_is_created_without_connecting(self) -> None:
        settings = DatabaseSettings(
            host="127.0.0.1",
            port=5432,
            database="cutory",
            username="cutory",
            password="unit-test-secret",
        )

        engine = create_database_engine(settings)
        try:
            self.assertEqual(engine.dialect.name, "postgresql")
            self.assertTrue(engine.pool._pre_ping)
            self.assertNotIn("unit-test-secret", str(engine.url))
        finally:
            engine.dispose()

    def test_session_factory_and_connection_check_work_without_postgresql(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        factory = create_session_factory(engine)
        try:
            with factory() as session:
                self.assertIsInstance(session, Session)
            check_database_connection(engine)
        finally:
            engine.dispose()

    def test_database_session_generator_always_closes_session(self) -> None:
        session = Mock(spec=Session)
        factory = Mock(return_value=session)
        dependency = get_database_session(factory)

        self.assertIs(next(dependency), session)
        with self.assertRaises(StopIteration):
            next(dependency)

        session.close.assert_called_once_with()

    def test_session_scope_commits_success_and_rolls_back_failure(self) -> None:
        successful = Mock(spec=Session)
        with session_scope(Mock(return_value=successful)):
            pass
        successful.commit.assert_called_once_with()
        successful.rollback.assert_not_called()
        successful.close.assert_called_once_with()

        failed = Mock(spec=Session)
        with self.assertRaisesRegex(RuntimeError, "unit of work failed"):
            with session_scope(Mock(return_value=failed)):
                raise RuntimeError("unit of work failed")
        failed.commit.assert_not_called()
        failed.rollback.assert_called_once_with()
        failed.close.assert_called_once_with()

    def test_connection_failure_is_safe_and_does_not_expose_credentials(self) -> None:
        engine = Mock()
        engine.connect.side_effect = SQLAlchemyError(
            "driver failure involving unit-test-secret"
        )

        with self.assertRaises(DatabaseConnectionError) as raised:
            check_database_connection(engine)

        self.assertEqual(str(raised.exception), "Database connection check failed.")
        self.assertNotIn("unit-test-secret", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_foundation_metadata_contains_current_product_tables(self) -> None:
        self.assertEqual(
            set(Base.metadata.tables),
            {
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
            },
        )
