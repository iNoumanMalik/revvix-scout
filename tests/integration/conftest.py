import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from revvix_scout.config import get_settings
from revvix_scout.db.session import reset_database_caches
from revvix_scout.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    database_url = os.environ.get("SCOUT_DATABASE_URL")
    if database_url is None:
        pytest.fail("SCOUT_DATABASE_URL must point to an isolated PostgreSQL test database")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("truncate table scout.workspaces cascade"))
    engine.dispose()

    get_settings.cache_clear()
    reset_database_caches()
    with TestClient(app) as test_client:
        yield test_client
    reset_database_caches()
