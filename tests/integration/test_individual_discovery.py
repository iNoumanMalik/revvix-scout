from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from revvix_scout.application.individual_discovery import (
    IndividualCollectionNotApprovedError,
    execute_individual_discovery,
)
from revvix_scout.config import get_settings
from revvix_scout.db.models import (
    Company,
    IndividualDiscoveryCandidate,
    IndividualReviewDecision,
    Lead,
    Person,
    PersonProfile,
    Suppression,
)
from revvix_scout.domain.individuals import normalize_person_name
from revvix_scout.providers.individual_contracts import (
    DiscoveredProfessional,
    IndividualDiscoveryPage,
    IndividualDiscoveryQuery,
    IndividualProviderRegistry,
)


def _request(idempotency_key: str) -> dict[str, object]:
    return {
        "provider_key": "fictional_professional_directory",
        "search_text": "fictional professional businesses",
        "country_code": "gb",
        "region": "England",
        "limit": 25,
        "idempotency_key": idempotency_key,
    }


def test_fictional_individual_pipeline_is_idempotent_and_keeps_common_names_separate(
    client: TestClient,
) -> None:
    first = client.post("/v1/individual-discovery-runs", json=_request("individual-run-001"))
    assert first.status_code == 200, first.text
    payload = first.json()

    assert payload["status"] == "succeeded"
    assert payload["discovered_count"] == 4
    assert payload["rejected_count"] == 1
    assert payload["duplicate_count"] == 0
    assert all(item["is_fictional"] for item in payload["candidates"])
    assert all(
        item["evidence_classification"] == "provider_asserted" for item in payload["candidates"]
    )
    rejected = next(item for item in payload["candidates"] if item["status"] == "rejected")
    assert rejected["rejection_reason"] == "professional_presence_missing"

    jordan_records = [
        item for item in payload["candidates"] if item["display_name"] == "Jordan Reed"
    ]
    assert len(jordan_records) == 2
    assert len({item["normalized_profile_url"] for item in jordan_records}) == 2
    assert all(item["status"] == "new" for item in jordan_records)
    assert all(item["duplicate_person_id"] is None for item in jordan_records)

    replay = client.post("/v1/individual-discovery-runs", json=_request("individual-run-001"))
    assert replay.status_code == 200
    assert replay.json()["id"] == payload["id"]
    assert client.get(f"/v1/discovery-runs/{payload['id']}").status_code == 404


def test_individual_pipeline_runs_when_business_provider_is_disabled(client: TestClient) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "update scout.provider_configs set enabled = false "
                "where provider_key = 'fictional_accounting_directory'"
            )
        )
    engine.dispose()

    response = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-isolation-001")
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"


def test_exact_profile_is_duplicate_but_same_name_only_requires_review(
    client: TestClient,
) -> None:
    settings = get_settings()
    observed_at = datetime(2026, 11, 1, tzinfo=UTC)
    exact_person_id = uuid4()
    ambiguous_person_id = uuid4()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        exact_person = Person(
            id=exact_person_id,
            workspace_id=settings.default_workspace_id,
            display_name="Avery North",
            normalized_name=normalize_person_name("Avery North"),
            country_code="GB",
            region="England",
            status="active",
            is_fictional=True,
            retention_expires_at=None,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        ambiguous_person = Person(
            id=ambiguous_person_id,
            workspace_id=settings.default_workspace_id,
            display_name="Jordan Reed",
            normalized_name=normalize_person_name("Jordan Reed"),
            country_code="GB",
            region="England",
            status="needs_review",
            is_fictional=True,
            retention_expires_at=None,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        session.add_all((exact_person, ambiguous_person))
        session.flush()
        session.add(
            PersonProfile(
                id=uuid4(),
                workspace_id=settings.default_workspace_id,
                person_id=exact_person.id,
                provider_key="fictional_professional_directory",
                provider_record_id="seed-avery",
                original_url="https://professionals.invalid/avery-north",
                normalized_url="https://professionals.invalid/avery-north",
                verification_status="source_asserted",
                source_url="https://fixtures.invalid/seed/avery-north",
                observed_at=observed_at,
            )
        )
        session.commit()

    response = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-resolution-001")
    )
    assert response.status_code == 200, response.text
    candidates = response.json()["candidates"]
    avery = next(item for item in candidates if item["display_name"] == "Avery North")
    jordans = [item for item in candidates if item["display_name"] == "Jordan Reed"]
    assert avery["status"] == "duplicate"
    assert avery["duplicate_person_id"] == str(exact_person_id)
    assert all(item["status"] == "needs_review" for item in jordans)
    assert all(item["possible_match_person_id"] == str(ambiguous_person_id) for item in jordans)
    assert all(item["duplicate_person_id"] is None for item in jordans)
    engine.dispose()


class _UnsafeIndividualProvider:
    key = "fictional_professional_directory"

    def __init__(
        self,
        *,
        is_live: bool,
        returns_real_person: bool = False,
        uses_nonfixture_url: bool = False,
    ) -> None:
        self.is_live = is_live
        self.returns_real_person = returns_real_person
        self.uses_nonfixture_url = uses_nonfixture_url
        self.calls = 0

    def estimate_units(self, query: IndividualDiscoveryQuery) -> int:
        return 1

    def discover(self, query: IndividualDiscoveryQuery) -> IndividualDiscoveryPage:
        self.calls += 1
        return IndividualDiscoveryPage(
            candidates=(
                DiscoveredProfessional(
                    provider_record_id="unsafe-001",
                    display_name="Test Fixture Person",
                    professional_profile_url=(
                        "https://example.com/test-fixture-person"
                        if self.uses_nonfixture_url
                        else "https://profiles.invalid/test-fixture-person"
                    ),
                    persona="consultant",
                    country_code="GB",
                    region="England",
                    service_summary="Test-only record.",
                    has_professional_presence=True,
                    has_business_relevance=True,
                    source_url="https://fixtures.invalid/unsafe-001",
                    observed_at=datetime(2026, 11, 1, tzinfo=UTC),
                    is_fictional=not self.returns_real_person,
                ),
            ),
            next_cursor=None,
            actual_units=1,
        )


def test_live_individual_provider_is_refused_before_execution(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _UnsafeIndividualProvider(is_live=True)
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        try:
            execute_individual_discovery(
                session=session,
                settings=settings,
                registry=IndividualProviderRegistry((provider,)),
                provider_key=provider.key,
                query=IndividualDiscoveryQuery(search_text="must not execute"),
                idempotency_key="individual-live-denied-001",
            )
        except IndividualCollectionNotApprovedError:
            pass
        else:
            raise AssertionError("live individual provider should be refused")
    engine.dispose()
    assert provider.calls == 0


def test_nonfictional_provider_output_is_not_persisted(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _UnsafeIndividualProvider(is_live=False, returns_real_person=True)
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        run = execute_individual_discovery(
            session=session,
            settings=settings,
            registry=IndividualProviderRegistry((provider,)),
            provider_key=provider.key,
            query=IndividualDiscoveryQuery(search_text="unsafe provider result"),
            idempotency_key="individual-output-denied-001",
        )
        count = session.scalar(
            select(func.count())
            .select_from(IndividualDiscoveryCandidate)
            .where(IndividualDiscoveryCandidate.discovery_run_id == run.id)
        )
        assert run.status == "failed"
        assert run.error_code == "processing"
        assert count == 0
    engine.dispose()
    assert provider.calls == 1


def test_fictional_provider_cannot_reference_nonfixture_domains(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _UnsafeIndividualProvider(is_live=False, uses_nonfixture_url=True)
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        run = execute_individual_discovery(
            session=session,
            settings=settings,
            registry=IndividualProviderRegistry((provider,)),
            provider_key=provider.key,
            query=IndividualDiscoveryQuery(search_text="nonfixture source"),
            idempotency_key="individual-source-denied-001",
        )
        count = session.scalar(
            select(func.count())
            .select_from(IndividualDiscoveryCandidate)
            .where(IndividualDiscoveryCandidate.discovery_run_id == run.id)
        )
        assert run.status == "failed"
        assert count == 0
    engine.dispose()


def test_operator_promotes_same_name_people_separately_and_leads_stay_isolated(
    client: TestClient,
) -> None:
    discovery = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-promotion-001")
    )
    assert discovery.status_code == 200, discovery.text
    jordans = [
        item for item in discovery.json()["candidates"] if item["display_name"] == "Jordan Reed"
    ]

    promoted = []
    for index, candidate in enumerate(jordans, start=1):
        response = client.post(
            f"/v1/individual-candidates/{candidate['id']}/review",
            json={
                "action": "promote_new",
                "reason": f"Operator confirmed distinct fictional profile {index}",
            },
        )
        assert response.status_code == 200, response.text
        promoted.append(response.json()["lead"])

    assert len({item["person_id"] for item in promoted}) == 2
    assert len({item["id"] for item in promoted}) == 2
    individual_leads = client.get("/v1/individual-leads")
    assert individual_leads.status_code == 200
    assert len(individual_leads.json()["items"]) == 2
    assert client.get("/v1/leads").json()["items"] == []


def test_operator_explicitly_links_profile_to_existing_person_idempotently(
    client: TestClient,
) -> None:
    discovery = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-link-001")
    ).json()
    jordans = [item for item in discovery["candidates"] if item["display_name"] == "Jordan Reed"]
    first = client.post(
        f"/v1/individual-candidates/{jordans[0]['id']}/review",
        json={"action": "promote_new", "reason": "Create first fictional Jordan"},
    )
    assert first.status_code == 200, first.text
    person_id = first.json()["lead"]["person_id"]
    lead_id = first.json()["lead"]["id"]

    request = {
        "action": "link_existing",
        "person_id": person_id,
        "reason": "Operator verified both fictional profiles belong together",
    }
    linked = client.post(f"/v1/individual-candidates/{jordans[1]['id']}/review", json=request)
    replay = client.post(f"/v1/individual-candidates/{jordans[1]['id']}/review", json=request)
    assert linked.status_code == replay.status_code == 200
    assert linked.json()["lead"]["id"] == replay.json()["lead"]["id"] == lead_id

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PersonProfile)
                .where(PersonProfile.person_id == person_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IndividualReviewDecision)
                .where(IndividualReviewDecision.candidate_id == jordans[1]["id"])
            )
            == 1
        )
    engine.dispose()


def test_profile_suppression_blocks_rediscovery_without_storing_raw_profile(
    client: TestClient,
) -> None:
    first = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-profile-suppress-001")
    ).json()
    avery = next(item for item in first["candidates"] if item["display_name"] == "Avery North")
    suppressed = client.post(
        f"/v1/individual-candidates/{avery['id']}/review",
        json={"action": "suppress", "reason": "Test fictional profile suppression"},
    )
    assert suppressed.status_code == 200, suppressed.text
    assert suppressed.json()["rejection_reason"] == "suppressed_profile"

    second_request = _request("individual-profile-suppress-002")
    second_request["search_text"] = "different fictional query"
    second = client.post("/v1/individual-discovery-runs", json=second_request)
    assert second.status_code == 200, second.text
    rediscovered = next(
        item for item in second.json()["candidates"] if item["display_name"] == "Avery North"
    )
    assert rediscovered["status"] == "rejected"
    assert rediscovered["rejection_reason"] == "suppressed_profile"

    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        suppression = session.scalar(select(Suppression).where(Suppression.scope == "profile"))
        assert suppression is not None
        assert suppression.person_id is None
        assert suppression.normalized_value_hash is not None
        assert len(suppression.normalized_value_hash) == 64
        assert "avery" not in suppression.normalized_value_hash
        assert session.scalar(select(func.count()).select_from(Lead)) == 0
    engine.dispose()


def test_person_suppression_disqualifies_lead_and_blocks_exact_profile(
    client: TestClient,
) -> None:
    first = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-person-suppress-001")
    ).json()
    avery = next(item for item in first["candidates"] if item["display_name"] == "Avery North")
    promoted = client.post(
        f"/v1/individual-candidates/{avery['id']}/review",
        json={"action": "promote_new", "reason": "Promote fictional Avery"},
    )
    assert promoted.status_code == 200, promoted.text
    person_id = promoted.json()["lead"]["person_id"]

    suppression = client.post(
        f"/v1/people/{person_id}/suppress",
        json={"reason_category": "operator_suppressed"},
    )
    assert suppression.status_code == 200, suppression.text
    assert suppression.json()["status"] == "suppressed"
    lead = client.get("/v1/individual-leads").json()["items"][0]
    assert (lead["stage"], lead["disposition"], lead["person_status"]) == (
        "suppressed",
        "disqualified",
        "suppressed",
    )

    second_request = _request("individual-person-suppress-002")
    second_request["search_text"] = "another fictional query"
    second = client.post("/v1/individual-discovery-runs", json=second_request)
    rediscovered = next(
        item for item in second.json()["candidates"] if item["display_name"] == "Avery North"
    )
    assert rediscovered["status"] == "rejected"
    assert rediscovered["rejection_reason"] == "suppressed_person"


def test_database_rejects_lead_with_both_company_and_person_subjects(
    client: TestClient,
) -> None:
    discovery = client.post(
        "/v1/individual-discovery-runs", json=_request("individual-subject-check-001")
    ).json()
    avery = next(item for item in discovery["candidates"] if item["display_name"] == "Avery North")
    promoted = client.post(
        f"/v1/individual-candidates/{avery['id']}/review",
        json={"action": "promote_new", "reason": "Create fictional person lead"},
    ).json()

    settings = get_settings()
    now = datetime(2026, 11, 1, tzinfo=UTC)
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        company = Company(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            display_name="Fictional Ambiguous Company",
            normalized_name="fictional ambiguous company",
            country_code="GB",
            match_status="resolved",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(company)
        session.flush()
        lead = session.get(Lead, promoted["lead"]["id"])
        assert lead is not None
        lead.company_id = company.id
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()
