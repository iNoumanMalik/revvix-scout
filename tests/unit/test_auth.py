from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from revvix_scout.api.auth import SupabaseAuthVerifier


def test_supabase_verifier_uses_user_endpoint_and_rejects_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        return httpx.Response(
            200,
            json={
                "id": "00000000-0000-4000-8000-000000000099",
                "is_anonymous": False,
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    verifier = SupabaseAuthVerifier(
        url="http://127.0.0.1:54321",
        publishable_key="fixture-publishable-key",
    )
    identity = verifier.verify("fixture-access-token")

    assert identity.user_id == UUID("00000000-0000-4000-8000-000000000099")
    assert identity.is_anonymous is False
    assert captured == {
        "url": "http://127.0.0.1:54321/auth/v1/user",
        "headers": {
            "apikey": "fixture-publishable-key",
            "authorization": "Bearer fixture-access-token",
        },
    }


def test_supabase_verifier_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(401, json={"message": "invalid token"}),
    )
    verifier = SupabaseAuthVerifier(
        url="http://127.0.0.1:54321",
        publishable_key="fixture-publishable-key",
    )

    with pytest.raises(HTTPException) as error:
        verifier.verify("invalid-token")
    assert error.value.status_code == 401
