from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from revvix_scout.config import get_settings
from revvix_scout.db.models import Company

FIXTURE = Path(__file__).parents[1] / "fixtures" / "businesses_v1.csv"


def test_review_queue_combines_domains_and_removes_resolved_items(
    client: TestClient,
) -> None:
    imported = client.post(
        "/v1/imports/business-csv",
        files={"file": ("businesses.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert imported.status_code == 200, imported.text

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        company_ids = sorted(session.scalars(select(Company.id)).all())
    engine.dispose()

    match = client.post(
        "/v1/entity-match-candidates",
        json={
            "entity_kind": "company",
            "left_id": str(company_ids[0]),
            "right_id": str(company_ids[1]),
            "exact_stable_identifier": False,
            "name_similarity": 0.9,
        },
    )
    assert match.status_code == 200, match.text

    response = client.get("/v1/review-queue")
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["counts"] == {"business_lead": 1, "entity_match": 1}
    assert {item["kind"] for item in page["items"]} == {
        "business_lead",
        "entity_match",
    }
    duplicate = next(item for item in page["items"] if item["kind"] == "entity_match")
    assert duplicate["allowed_actions"] == ["merge_left", "merge_right", "reject"]
    assert duplicate["primary_subject_id"] in {str(value) for value in company_ids}
    assert duplicate["secondary_subject_id"] in {str(value) for value in company_ids}

    rejected = client.post(
        f"/v1/entity-match-candidates/{match.json()['id']}/review",
        json={"action": "reject", "reason": "Operator confirmed distinct fictional firms"},
    )
    assert rejected.status_code == 200, rejected.text
    remaining = client.get("/v1/review-queue").json()
    assert remaining["counts"] == {"business_lead": 1}
    assert all(item["kind"] != "entity_match" for item in remaining["items"])


def test_review_queue_limit_is_validated(client: TestClient) -> None:
    assert client.get("/v1/review-queue", params={"limit": 0}).status_code == 422
    assert client.get("/v1/review-queue", params={"limit": 501}).status_code == 422
