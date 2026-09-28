import os
from unittest import TestCase, skipUnless

from backend.app.config import DatabaseSettings
from backend.app.database import check_database_connection, create_database_engine


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class PostgreSQLIntegrationTests(TestCase):
    def test_select_one_through_application_database_foundation(self) -> None:
        settings = DatabaseSettings.from_environment()
        engine = create_database_engine(settings)
        try:
            check_database_connection(engine)
        finally:
            engine.dispose()
