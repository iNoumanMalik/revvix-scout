from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from revvix_scout.config import get_settings
from revvix_scout.db.models import (
    Company,
    EntityMatchCandidate,
    EntityMergeEvent,
    EvidenceClaim,
    SourceDocument,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "businesses_v1.csv"


def _import_fixture(client: TestClient) -> None:
    response = client.post(
        "/v1/imports/business-csv",
        files={"file": ("businesses.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_import_evidence_uses_explicit_m6_metadata_and_review_state(
    client: TestClient,
) -> None:
    _import_fixture(client)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        document = session.scalar(select(SourceDocument).limit(1))
        claim = session.scalar(select(EvidenceClaim).limit(1))
        assert document is not None
        assert document.redaction_status == "metadata_only"
        assert document.license_policy_json == {
            "source": "csv_import",
            "raw_content_retained": False,
        }
        assert document.enrichment_run_id is None
        assert document.import_row_id is not None
        assert claim is not None
        assert claim.review_status == "unreviewed"
        assert claim.supersedes_claim_id is None
    engine.dispose()


def test_match_pairs_are_canonical_and_unmerge_requires_prior_event(
    client: TestClient,
) -> None:
    _import_fixture(client)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        companies = sorted(session.scalars(select(Company)).all(), key=lambda item: item.id)
        assert len(companies) >= 2
        left, right = companies[:2]
        candidate = EntityMatchCandidate(
            workspace_id=settings.default_workspace_id,
            entity_kind="company",
            left_company_id=left.id,
            right_company_id=right.id,
            match_basis="fuzzy",
            algorithm_version="entity-match-1",
            score=0.9,
            features_json={"normalized_name_similarity": 0.9},
            status="pending",
        )
        session.add(candidate)
        session.commit()

        session.add(
            EntityMergeEvent(
                workspace_id=settings.default_workspace_id,
                match_candidate_id=candidate.id,
                entity_kind="company",
                action="unmerge",
                survivor_company_id=left.id,
                merged_company_id=right.id,
                reverses_event_id=None,
                snapshot_json={"fixture": True},
                reason="Invalid fixture unmerge without a prior merge",
                actor_type="operator",
                occurred_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            EntityMatchCandidate(
                workspace_id=settings.default_workspace_id,
                entity_kind="company",
                left_company_id=right.id,
                right_company_id=left.id,
                match_basis="fuzzy",
                algorithm_version="entity-match-1",
                score=0.9,
                features_json={"normalized_name_similarity": 0.9},
                status="pending",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()
