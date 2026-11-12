import csv
import io
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

FIXTURE = Path(__file__).parents[1] / "fixtures" / "businesses_v1.csv"


def _import_fixture(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/imports/business-csv",
        files={"file": ("businesses.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_checks_postgres(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_partial_import_deduplicates_and_is_idempotent(client: TestClient) -> None:
    first = _import_fixture(client)
    assert first["status"] == "partially_succeeded"
    assert first["total_rows"] == 4
    assert first["succeeded_rows"] == 3
    assert first["failed_rows"] == 1
    assert first["duplicate_rows"] == 1
    assert first["idempotent_replay"] is False
    assert len(first["errors"]) == 1
    assert first["errors"][0]["row_number"] == 5
    assert first["errors"][0]["source_record_id"] == "biz-broken"
    assert first["errors"][0]["code"] == "validation_error"
    assert first["errors"][0]["message"].startswith("observed_at:")

    replay = _import_fixture(client)
    assert replay["import_job_id"] == first["import_job_id"]
    assert replay["idempotent_replay"] is True
    assert replay["succeeded_rows"] == 3

    page = client.get("/v1/leads").json()
    assert len(page["items"]) == 2
    by_name = {item["company_name"]: item for item in page["items"]}
    assert by_name["Example Legal Automation"]["normalized_domain"] == "example.com"
    assert by_name["Example Legal Automation"]["score"] == 100
    assert by_name["No Domain Consulting"]["match_status"] == "needs_review"


def test_lead_detail_links_each_accepted_component_to_evidence(client: TestClient) -> None:
    _import_fixture(client)
    leads = client.get("/v1/leads", params={"min_score": 100}).json()["items"]
    example_lead = next(
        lead for lead in leads if lead["company_name"] == "Example Legal Automation"
    )
    detail = client.get(f"/v1/leads/{example_lead['id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["score_detail"]["icp_version_id"]
    assert payload["score_detail"]["algorithm_version"] == "business-icp-2"
    assert len(payload["evidence"]) == 8
    assert all(
        component["evidence_claim_ids"]
        for component in payload["score_detail"]["components"]
        if component["result"] != "missing"
    )
    assert all(item["classification"] == "provider_asserted" for item in payload["evidence"])


def test_cursor_pagination_and_filtering(client: TestClient) -> None:
    _import_fixture(client)
    first = client.get("/v1/leads", params={"limit": 1}).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"]

    second = client.get("/v1/leads", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert client.get("/v1/leads", params={"cursor": "altered"}).status_code == 400

    qualified = client.get("/v1/leads", params={"disposition": "qualified"}).json()
    assert len(qualified["items"]) == 2


def test_csv_export_is_allow_listed_and_neutralizes_formulas(client: TestClient) -> None:
    malicious = (
        FIXTURE.read_text().splitlines()[0]
        + "\n"
        + (
            '1,biz-formula,"=HYPERLINK(""https://evil.invalid"",""click"")",formula.com,'
            "US,20,software,integration_gap,,https://directory.example.org/formula,"
            "2026-10-01T10:00:00Z\n"
        )
    )
    imported = client.post(
        "/v1/imports/business-csv",
        files={"file": ("formula.csv", malicious.encode(), "text/csv")},
    )
    assert imported.status_code == 200, imported.text

    response = client.get("/v1/leads/export.csv")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["company_name"].startswith("'=HYPERLINK")
    assert set(rows[0]) == {
        "lead_id",
        "company_name",
        "domain",
        "country_code",
        "industry",
        "employee_count",
        "match_status",
        "disposition",
        "score",
        "created_at",
    }


def test_file_contract_errors_do_not_create_partial_jobs(client: TestClient) -> None:
    response = client.post(
        "/v1/imports/business-csv",
        files={"file": ("bad.csv", b"company_name\nAcme\n", "text/csv")},
    )
    assert response.status_code == 422
    assert "missing required columns" in response.json()["detail"]
    assert client.get("/v1/leads").json()["items"] == []


def test_fictional_discovery_is_bounded_idempotent_and_rejects_dormant(client: TestClient) -> None:
    request = {
        "provider_key": "fictional_accounting_directory",
        "search_text": "independent accounting firms",
        "country_code": "GB",
        "region": "England",
        "limit": 25,
        "idempotency_key": "test-discovery-001",
    }
    first = client.post("/v1/discovery-runs", json=request)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["status"] == "succeeded"
    assert payload["discovered_count"] == 3
    assert payload["rejected_count"] == 1
    assert {item["status"] for item in payload["candidates"]} == {"new", "rejected"}
    assert (
        next(item for item in payload["candidates"] if item["status"] == "rejected")[
            "rejection_reason"
        ]
        == "company_status_not_allowed"
    )

    replay = client.post("/v1/discovery-runs", json=request)
    assert replay.status_code == 200
    assert replay.json()["id"] == payload["id"]


def test_unknown_provider_is_denied_without_a_call(client: TestClient) -> None:
    response = client.post(
        "/v1/discovery-runs",
        json={
            "provider_key": "not_configured",
            "search_text": "accountants",
            "idempotency_key": "test-unknown-provider",
        },
    )
    assert response.status_code == 409


def test_hard_budget_blocks_before_provider_execution(client: TestClient) -> None:
    engine = create_engine(os.environ["SCOUT_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "update scout.budget_policies set hard_limit_units = 0 "
                "where provider_key = 'fictional_accounting_directory'"
            )
        )
    engine.dispose()
    response = client.post(
        "/v1/discovery-runs",
        json={
            "search_text": "accountants",
            "idempotency_key": "test-zero-budget-policy",
        },
    )
    assert response.status_code == 402
    assert "hard run budget" in response.json()["detail"]


def test_discovery_deduplicates_existing_domain_before_enrichment(client: TestClient) -> None:
    _import_fixture(client)
    response = client.post(
        "/v1/discovery-runs",
        json={
            "search_text": "accountants",
            "idempotency_key": "test-domain-deduplication",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["duplicate_count"] == 1
    duplicate = next(item for item in payload["candidates"] if item["status"] == "duplicate")
    assert duplicate["normalized_domain"] == "example.com"
    assert duplicate["rejection_reason"] == "existing_domain"
