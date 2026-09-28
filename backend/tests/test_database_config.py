from unittest import TestCase

from backend.app.config import DatabaseConfigError, DatabaseSettings


VALID_ENVIRONMENT = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "cutory",
    "POSTGRES_USER": "cutory",
    "POSTGRES_PASSWORD": "unit-test-secret",
}


class DatabaseSettingsTests(TestCase):
    def test_settings_are_loaded_from_environment(self) -> None:
        settings = DatabaseSettings.from_environment(VALID_ENVIRONMENT)

        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 5432)
        self.assertEqual(settings.database, "cutory")
        self.assertEqual(settings.username, "cutory")
        self.assertEqual(settings.password, "unit-test-secret")
        self.assertEqual(settings.sqlalchemy_url.drivername, "postgresql+psycopg")

    def test_missing_required_setting_fails_safely(self) -> None:
        environment = dict(VALID_ENVIRONMENT)
        del environment["POSTGRES_PASSWORD"]

        with self.assertRaisesRegex(DatabaseConfigError, "POSTGRES_PASSWORD") as raised:
            DatabaseSettings.from_environment(environment)

        self.assertNotIn("unit-test-secret", str(raised.exception))

    def test_invalid_port_fails_safely(self) -> None:
        for port in ("not-a-number", "0", "65536"):
            with self.subTest(port=port):
                environment = {**VALID_ENVIRONMENT, "POSTGRES_PORT": port}
                with self.assertRaises(DatabaseConfigError):
                    DatabaseSettings.from_environment(environment)

    def test_repr_and_url_string_mask_password(self) -> None:
        settings = DatabaseSettings.from_environment(VALID_ENVIRONMENT)

        self.assertNotIn("unit-test-secret", repr(settings))
        self.assertNotIn("unit-test-secret", str(settings.sqlalchemy_url))
        self.assertIn("***", repr(settings))
        self.assertIn("***", str(settings.sqlalchemy_url))
