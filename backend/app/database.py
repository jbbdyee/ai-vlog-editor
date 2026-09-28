from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import DatabaseSettings


class Base(DeclarativeBase):
    """Declarative metadata root for product models added in later v1 steps."""


class DatabaseConnectionError(RuntimeError):
    """Raised when PostgreSQL connectivity validation fails without leaking credentials."""


SessionFactory = sessionmaker[Session]


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Create the synchronous SQLAlchemy engine without opening a connection yet."""
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create the shared Session factory bound to the supplied engine."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_database_session(factory: SessionFactory) -> Generator[Session, None, None]:
    """Yield one Session and always close it; suitable for a future FastAPI dependency."""
    session = factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope(factory: SessionFactory) -> Iterator[Session]:
    """Commit a successful unit of work and roll it back when an exception occurs."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database_connection(engine: Engine) -> None:
    """Run the minimal PostgreSQL readiness query using an existing engine."""
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
    except (SQLAlchemyError, OSError):
        raise DatabaseConnectionError("Database connection check failed.") from None

    if result != 1:
        raise DatabaseConnectionError("Database connection check returned an invalid result.")
