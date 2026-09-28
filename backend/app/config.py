import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv
from sqlalchemy import URL


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = PROJECT_ROOT / ".env"


def load_environment() -> bool:
    """Load the project-root .env without overriding process variables."""
    return load_dotenv(dotenv_path=DOTENV_PATH, override=False)


class DatabaseConfigError(RuntimeError):
    """Raised when required database configuration is missing or invalid."""


@dataclass(frozen=True, repr=False)
class DatabaseSettings:
    """Validated PostgreSQL settings without exposing credentials in repr output."""

    host: str
    port: int
    database: str
    username: str
    password: str

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "DatabaseSettings":
        values = os.environ if environment is None else environment
        required_names = (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        )
        missing = [name for name in required_names if not values.get(name, "").strip()]
        if missing:
            raise DatabaseConfigError(
                "Required PostgreSQL settings are missing: " + ", ".join(missing)
            )

        port_value = values["POSTGRES_PORT"].strip()
        try:
            port = int(port_value)
        except ValueError as error:
            raise DatabaseConfigError("POSTGRES_PORT must be an integer.") from error
        if not 1 <= port <= 65535:
            raise DatabaseConfigError("POSTGRES_PORT must be between 1 and 65535.")

        return cls(
            host=values["POSTGRES_HOST"].strip(),
            port=port,
            database=values["POSTGRES_DB"].strip(),
            username=values["POSTGRES_USER"].strip(),
            password=values["POSTGRES_PASSWORD"],
        )

    @property
    def sqlalchemy_url(self) -> URL:
        """Build a PostgreSQL URL object whose string representation masks the password."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )

    def __repr__(self) -> str:
        return (
            "DatabaseSettings("
            f"host={self.host!r}, port={self.port!r}, database={self.database!r}, "
            f"username={self.username!r}, password='***')"
        )
