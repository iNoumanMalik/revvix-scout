from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from revvix_scout.config import get_settings
from revvix_scout.db.models import PersonCompanyRole, ProviderUsageEvent

FIXTURE = Path(__file__).parents[1] / "fixtures" / "businesses_v1.csv"


def _import_company(client: TestClient) -> str:
    response = client.post(
        "/v1/imports/business-csv",
        files={"file": ("businesses.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    leads = client.get("/v1/leads").json()["items"]
    return next(item["company_id"] for item in leads if item["normalized_domain"] == "example.com")


def test_decision_maker_research_is_company_scoped_explainable_and_idempotent(
    client: TestClient,
) -> None:
    company_id = _import_company(client)
    request = {"idempotency_key": "decision-maker-run-001", "limit": 25}
    first = client.post(f"/v1/companies/{company_id}/decision-maker-runs", json=request)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["status"] == "succeeded"
    assert payload["discovered_count"] == 3
    assert payload["rejected_count"] == 1
    assert {item["title"] for item in payload["candidates"] if item["status"] == "new"} == {
        "Managing Partner",
        "Practice Manager",
    }
    assert {item["matched_role"] for item in payload["candidates"] if item["status"] == "new"} == {
        "managing partner",
        "practice manager",
    }
    assert all(item["qualification_explanation"] for item in payload["candidates"])
    assert all(
        item["source_url"].startswith("https://fixtures.invalid/") for item in payload["candidates"]
    )
    rejected = next(item for item in payload["candidates"] if item["status"] == "rejected")
    assert rejected["rejection_reason"] == "role_not_configured"
    assert all(
        item["evidence_classification"] == "provider_asserted" for item in payload["candidates"]
    )
    replay = client.post(f"/v1/companies/{company_id}/decision-maker-runs", json=request)
    assert replay.json()["id"] == payload["id"]
    assert client.get(f"/v1/discovery-runs/{payload['id']}").status_code == 404


def test_company_can_preserve_multiple_current_and_historical_decision_makers(
    client: TestClient,
) -> None:
    company_id = _import_company(client)
    run = client.post(
        f"/v1/companies/{company_id}/decision-maker-runs",
        json={"idempotency_key": "decision-maker-promote-001"},
    ).json()
    promoted = []
    for item in run["candidates"]:
        if item["status"] == "new":
            response = client.post(f"/v1/decision-maker-candidates/{item['id']}/promote")
            assert response.status_code == 200, response.text
            promoted.append(response.json())
    assert len(promoted) == 2
    assert len({item["person_id"] for item in promoted}) == 2
    assert {item["relationship_type"] for item in promoted} == {"partner", "employee"}

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        roles = session.scalars(
            select(PersonCompanyRole).where(PersonCompanyRole.company_id == company_id)
        ).all()
        usage = session.scalar(
            select(ProviderUsageEvent).where(ProviderUsageEvent.discovery_run_id == run["id"])
        )
        assert len(roles) == 2
        assert all(role.is_current for role in roles)
        assert usage is not None
        assert usage.operation == "decision_maker_discovery"
        historical = next(role for role in roles if role.relationship_type == "employee")
        historical.is_current = False
        historical.started_on = datetime(2020, 1, 1, tzinfo=UTC)
        historical.ended_on = datetime(2025, 12, 31, tzinfo=UTC)
        session.commit()
        persisted = session.scalars(
            select(PersonCompanyRole).where(PersonCompanyRole.company_id == company_id)
        ).all()
        assert sum(role.is_current for role in persisted) == 1
        assert sum(not role.is_current for role in persisted) == 1
        assert next(role for role in persisted if not role.is_current).ended_on is not None
    engine.dispose()


def test_decision_maker_budget_is_independent_from_company_discovery(
    client: TestClient,
) -> None:
    company_id = _import_company(client)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "update scout.budget_policies set hard_limit_units = 0 "
                "where operation = 'decision_maker_discovery'"
            )
        )
    engine.dispose()

    blocked = client.post(
        f"/v1/companies/{company_id}/decision-maker-runs",
        json={"idempotency_key": "decision-maker-zero-budget-001"},
    )
    assert blocked.status_code == 402
    company_discovery = client.post(
        "/v1/discovery-runs",
        json={
            "search_text": "accountants",
            "idempotency_key": "company-budget-still-available-001",
        },
    )
    assert company_discovery.status_code == 200, company_discovery.text


def test_unrelated_profile_suppression_does_not_block_candidate_promotion(
    client: TestClient,
) -> None:
    individual = client.post(
        "/v1/individual-discovery-runs",
        json={
            "provider_key": "fictional_professional_directory",
            "search_text": "fictional professional businesses",
            "country_code": "gb",
            "region": "England",
            "limit": 25,
            "idempotency_key": "unrelated-profile-suppression-001",
        },
    ).json()
    avery = next(item for item in individual["candidates"] if item["display_name"] == "Avery North")
    suppressed = client.post(
        f"/v1/individual-candidates/{avery['id']}/review",
        json={"action": "suppress", "reason": "Unrelated fictional profile"},
    )
    assert suppressed.status_code == 200, suppressed.text

    company_id = _import_company(client)
    run = client.post(
        f"/v1/companies/{company_id}/decision-maker-runs",
        json={"idempotency_key": "decision-maker-after-unrelated-suppression-001"},
    ).json()
    candidate = next(item for item in run["candidates"] if item["status"] == "new")
    promoted = client.post(f"/v1/decision-maker-candidates/{candidate['id']}/promote")
    assert promoted.status_code == 200, promoted.text
