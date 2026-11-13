from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session

from revvix_scout.application.enrichment import (
    EnrichmentCollectionNotApprovedError,
    execute_enrichment,
)
from revvix_scout.application.usage import BudgetExceededError, reserve_enrichment_budget
from revvix_scout.config import get_settings
from revvix_scout.db.models import (
    BudgetPolicy,
    BudgetReservation,
    EnrichmentRun,
    EvidenceClaim,
    LeadEvidence,
    ProviderUsageEvent,
)
from revvix_scout.providers.enrichment_contracts import (
    EnrichmentProviderRegistry,
    EnrichmentQuery,
    EnrichmentResult,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "businesses_v1.csv"


def _import_example_lead(client: TestClient) -> UUID:
    response = client.post(
        "/v1/imports/business-csv",
        files={"file": ("businesses.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    leads = client.get("/v1/leads").json()["items"]
    return UUID(next(item["id"] for item in leads if item["normalized_domain"] == "example.com"))


def _make_claims_stale(lead_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        claim_ids = select(LeadEvidence.evidence_claim_id).where(LeadEvidence.lead_id == lead_id)
        connection.execute(
            update(EvidenceClaim)
            .where(EvidenceClaim.id.in_(claim_ids))
            .values(retrieved_at=datetime(2020, 1, 1, tzinfo=UTC), valid_until=None)
        )
    engine.dispose()


def test_fresh_evidence_stops_waterfall_without_provider_usage(client: TestClient) -> None:
    lead_id = _import_example_lead(client)
    response = client.post(
        f"/v1/leads/{lead_id}/enrichment-runs",
        json={"idempotency_key": "fresh-enrichment-stop-001"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["stop_reason"] == "required_fields_satisfied"
    assert payload["current_step_order"] is None
    assert payload["claims"] == []

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProviderUsageEvent)) == 0
        assert session.scalar(select(func.count()).select_from(BudgetReservation)) == 0
    engine.dispose()


def test_stale_evidence_is_enriched_budgeted_and_conflicts_are_preserved(
    client: TestClient,
) -> None:
    lead_id = _import_example_lead(client)
    _make_claims_stale(lead_id)
    request = {"idempotency_key": "stale-enrichment-run-001"}
    response = client.post(f"/v1/leads/{lead_id}/enrichment-runs", json=request)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "partially_succeeded"
    assert payload["stop_reason"] == "conflicting_claims"
    assert payload["completed_fields"] == ["industry"]
    employee_claim = next(
        claim for claim in payload["claims"] if claim["claim_type"] == "employee_count"
    )
    assert employee_claim["verification_status"] == "conflicting"
    assert employee_claim["source_url"].startswith("https://fixtures.invalid/")

    replay = client.post(f"/v1/leads/{lead_id}/enrichment-runs", json=request)
    assert replay.status_code == 200
    assert replay.json()["id"] == payload["id"]

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        usage = session.scalar(
            select(ProviderUsageEvent).where(
                ProviderUsageEvent.enrichment_run_id == UUID(payload["id"])
            )
        )
        reservation = session.scalar(
            select(BudgetReservation).where(
                BudgetReservation.enrichment_run_id == UUID(payload["id"])
            )
        )
        assert usage is not None
        assert (usage.operation, usage.outcome, usage.actual_units) == (
            "firmographic_enrichment",
            "partial",
            1,
        )
        assert reservation is not None
        assert reservation.status == "settled"
        conflicts = session.scalars(
            select(EvidenceClaim)
            .join(LeadEvidence, LeadEvidence.evidence_claim_id == EvidenceClaim.id)
            .where(
                LeadEvidence.lead_id == lead_id,
                EvidenceClaim.claim_type == "employee_count",
            )
        ).all()
        assert len(conflicts) >= 2
        assert all(claim.verification_status == "conflicting" for claim in conflicts)
    engine.dispose()


def test_zero_enrichment_budget_blocks_before_provider_execution(client: TestClient) -> None:
    lead_id = _import_example_lead(client)
    _make_claims_stale(lead_id)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(
            update(BudgetPolicy)
            .where(BudgetPolicy.operation == "firmographic_enrichment")
            .values(hard_limit_units=0)
        )
    engine.dispose()

    response = client.post(
        f"/v1/leads/{lead_id}/enrichment-runs",
        json={"idempotency_key": "zero-enrichment-budget-001"},
    )
    assert response.status_code == 402
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(EnrichmentRun)) == 0
        assert session.scalar(select(func.count()).select_from(ProviderUsageEvent)) == 0
    engine.dispose()


class _FailingFixtureProvider:
    key = "fictional_firmographic_enrichment"
    is_live = False

    def estimate_units(self, query: EnrichmentQuery) -> int:
        return 1

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        raise RuntimeError("fixture provider unavailable")


class _LiveProvider:
    key = "fictional_firmographic_enrichment"
    is_live = True
    called = False

    def estimate_units(self, query: EnrichmentQuery) -> int:
        return 1

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        self.called = True
        raise AssertionError("live provider must not execute")


def test_provider_failure_still_settles_usage(client: TestClient) -> None:
    lead_id = _import_example_lead(client)
    _make_claims_stale(lead_id)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        run = execute_enrichment(
            session=session,
            settings=settings,
            registry=EnrichmentProviderRegistry((_FailingFixtureProvider(),)),
            lead_id=lead_id,
            idempotency_key="failed-enrichment-provider-001",
        )
        usage = session.scalar(
            select(ProviderUsageEvent).where(ProviderUsageEvent.enrichment_run_id == run.id)
        )
        reservation = session.scalar(
            select(BudgetReservation).where(BudgetReservation.enrichment_run_id == run.id)
        )
        assert run.status == "failed"
        assert usage is not None
        assert (usage.outcome, usage.actual_units) == ("failed", 0)
        assert reservation is not None
        assert reservation.status == "settled"
    engine.dispose()


def test_live_enrichment_provider_is_refused_before_execution(client: TestClient) -> None:
    lead_id = _import_example_lead(client)
    _make_claims_stale(lead_id)
    settings = get_settings()
    provider = _LiveProvider()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        with pytest.raises(EnrichmentCollectionNotApprovedError):
            execute_enrichment(
                session=session,
                settings=settings,
                registry=EnrichmentProviderRegistry((provider,)),
                lead_id=lead_id,
                idempotency_key="live-enrichment-refused-001",
            )
        session.rollback()
        assert provider.called is False
        assert session.scalar(select(func.count()).select_from(EnrichmentRun)) == 0
        assert session.scalar(select(func.count()).select_from(BudgetReservation)) == 0
    engine.dispose()


def test_concurrent_enrichment_reservations_respect_hard_cap(client: TestClient) -> None:
    lead_id = _import_example_lead(client)
    run_response = client.post(
        f"/v1/leads/{lead_id}/enrichment-runs",
        json={"idempotency_key": "concurrent-enrichment-budget-run-001"},
    )
    assert run_response.status_code == 200, run_response.text
    run_id = UUID(run_response.json()["id"])
    settings = get_settings()
    barrier = Barrier(2)

    def reserve_once() -> str:
        thread_engine = create_engine(settings.database_url)
        try:
            with Session(thread_engine) as session:
                run = session.get(EnrichmentRun, run_id)
                assert run is not None
                barrier.wait()
                try:
                    reserve_enrichment_budget(
                        session=session,
                        settings=settings,
                        run=run,
                        provider_key="fictional_firmographic_enrichment",
                        operation="firmographic_enrichment",
                        estimated_units=1,
                        now=datetime.now(UTC),
                    )
                    session.commit()
                    return "reserved"
                except BudgetExceededError:
                    session.rollback()
                    return "blocked"
        finally:
            thread_engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: reserve_once(), range(2)))
    assert outcomes == ["blocked", "reserved"]

    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        reservations = session.scalars(
            select(BudgetReservation).where(BudgetReservation.enrichment_run_id == run_id)
        ).all()
        assert len(reservations) == 1
        assert reservations[0].reserved_units == 1
    engine.dispose()
