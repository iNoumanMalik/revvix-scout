from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from revvix_scout.config import get_settings
from revvix_scout.db.models import Company, EntityMatchCandidate, EntityMergeEvent, EvidenceClaim

FIXTURE = Path(__file__).parents[1] / "fixtures" / "businesses_v1.csv"


def _company_ids(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/v1/imports/business-csv",
        files={"file": ("businesses.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        ids = sorted(str(value) for value in session.scalars(select(Company.id)).all())
    engine.dispose()
    assert len(ids) >= 2
    return ids[0], ids[1]


def test_logical_company_merge_is_idempotent_and_recoverable(client: TestClient) -> None:
    left_id, right_id = _company_ids(client)
    request = {
        "entity_kind": "company",
        "left_id": right_id,
        "right_id": left_id,
        "exact_stable_identifier": False,
        "name_similarity": 0.9,
    }
    created = client.post("/v1/entity-match-candidates", json=request)
    replay = client.post("/v1/entity-match-candidates", json=request)
    assert created.status_code == replay.status_code == 200
    candidate = created.json()
    assert replay.json()["id"] == candidate["id"]
    assert (candidate["left_id"], candidate["right_id"]) == (left_id, right_id)
    assert (candidate["status"], candidate["match_basis"]) == ("pending", "fuzzy")

    merged = client.post(
        f"/v1/entity-match-candidates/{candidate['id']}/review",
        json={
            "action": "merge",
            "survivor_id": left_id,
            "reason": "Operator confirmed fictional company identity",
        },
    )
    assert merged.status_code == 200, merged.text
    merged_payload = merged.json()
    assert merged_payload["status"] == "merged"
    assert len(merged_payload["events"]) == 1
    merge_event = merged_payload["events"][0]
    assert merge_event["action"] == "merge"

    unmerged = client.post(
        f"/v1/entity-merge-events/{merge_event['id']}/unmerge",
        json={"reason": "Operator reversed fictional logical merge"},
    )
    replay_unmerge = client.post(
        f"/v1/entity-merge-events/{merge_event['id']}/unmerge",
        json={"reason": "Operator reversed fictional logical merge"},
    )
    assert unmerged.status_code == replay_unmerge.status_code == 200
    restored = unmerged.json()
    assert restored["status"] == "confirmed"
    assert len(restored["events"]) == 2
    reversal = next(event for event in restored["events"] if event["action"] == "unmerge")
    assert reversal["reverses_event_id"] == merge_event["id"]
    assert replay_unmerge.json()["events"] == restored["events"]

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Company)) == 2
        assert session.scalar(select(func.count()).select_from(EvidenceClaim)) > 0
        event = session.get(EntityMergeEvent, reversal["id"])
        assert event is not None
        assert event.snapshot_json["logical_overlay_removed"] is True
    engine.dispose()


def test_rejected_match_cannot_be_merged(client: TestClient) -> None:
    left_id, right_id = _company_ids(client)
    candidate = client.post(
        "/v1/entity-match-candidates",
        json={
            "entity_kind": "company",
            "left_id": left_id,
            "right_id": right_id,
            "exact_stable_identifier": False,
            "name_similarity": 0.95,
        },
    ).json()
    rejected = client.post(
        f"/v1/entity-match-candidates/{candidate['id']}/review",
        json={"action": "reject", "reason": "Operator found distinct fictional companies"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    blocked = client.post(
        f"/v1/entity-match-candidates/{candidate['id']}/review",
        json={
            "action": "merge",
            "survivor_id": left_id,
            "reason": "Attempted invalid merge after rejection",
        },
    )
    assert blocked.status_code == 409

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        stored = session.get(EntityMatchCandidate, candidate["id"])
        assert stored is not None
        assert stored.status == "rejected"
        assert session.scalar(select(func.count()).select_from(EntityMergeEvent)) == 0
    engine.dispose()
