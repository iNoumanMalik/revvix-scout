import os
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from revvix_scout.config import get_settings
from revvix_scout.db.models import UserProfile, WorkspaceMember
from revvix_scout.db.session import reset_database_caches
from revvix_scout.main import app


def test_supabase_token_is_mediated_by_active_workspace_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("SCOUT_DATABASE_URL")
    if database_url is None:
        pytest.fail("SCOUT_DATABASE_URL must point to an isolated PostgreSQL test database")
    external_user_id = UUID("00000000-0000-4000-8000-000000000099")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("truncate table scout.workspaces cascade"))
        connection.execute(
            text("delete from scout.user_profiles where user_id = :user_id"),
            {"user_id": external_user_id},
        )

    monkeypatch.setenv("SCOUT_AUTH_MODE", "supabase")
    monkeypatch.setenv("SCOUT_SUPABASE_URL", "http://127.0.0.1:54321")
    monkeypatch.setenv("SCOUT_SUPABASE_PUBLISHABLE_KEY", "fixture-publishable-key")
    get_settings.cache_clear()
    reset_database_caches()

    def verify_user(url: str, **kwargs: object) -> httpx.Response:
        assert url == "http://127.0.0.1:54321/auth/v1/user"
        assert kwargs["headers"] == {
            "apikey": "fixture-publishable-key",
            "authorization": "Bearer fixture-access-token",
        }
        return httpx.Response(
            200,
            json={"id": str(external_user_id), "is_anonymous": False},
        )

    monkeypatch.setattr(httpx, "get", verify_user)
    with TestClient(app) as supabase_client:
        settings = get_settings()
        with Session(engine) as session:
            session.add(UserProfile(user_id=external_user_id, display_name="Fixture Reviewer"))
            session.add(
                WorkspaceMember(
                    workspace_id=settings.default_workspace_id,
                    user_id=external_user_id,
                    role="reviewer",
                    status="active",
                )
            )
            session.commit()

        assert supabase_client.get("/v1/session").status_code == 401
        response = supabase_client.get(
            "/v1/session",
            headers={"authorization": "Bearer fixture-access-token"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "user_id": str(external_user_id),
            "workspace_id": str(settings.default_workspace_id),
            "role": "reviewer",
            "display_name": "Fixture Reviewer",
            "auth_mode": "supabase",
            "capabilities": ["read", "review"],
        }

    with engine.begin() as connection:
        connection.execute(
            text("delete from scout.user_profiles where user_id = :user_id"),
            {"user_id": external_user_id},
        )
    engine.dispose()
    get_settings.cache_clear()
    reset_database_caches()
