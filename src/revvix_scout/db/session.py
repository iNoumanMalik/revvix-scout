"""Database engine and session lifecycle."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from revvix_scout.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the application database engine once per process."""

    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the configured SQLAlchemy session factory."""

    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency providing one transactional session per request."""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_database_caches() -> None:
    """Dispose cached database state, primarily for isolated test configuration."""

    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
