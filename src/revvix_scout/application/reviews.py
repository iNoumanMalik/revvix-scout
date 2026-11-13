"""Workspace-scoped read model for pending human review decisions."""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import ReviewQueueItem, ReviewQueuePage
from revvix_scout.application.entity_resolution import candidate_subject_ids
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    Company,
    EntityMatchCandidate,
    IndividualDiscoveryCandidate,
    Lead,
    OpportunityAnalysisRun,
    OpportunityHypothesis,
    Person,
)


def list_review_queue(*, session: Session, settings: Settings, limit: int) -> ReviewQueuePage:
    """Return newest-first review work without changing source records."""

    workspace_id = settings.default_workspace_id
    items: list[ReviewQueueItem] = []

    business_rows = session.execute(
        select(Lead, Company)
        .join(Company, Company.id == Lead.company_id)
        .where(
            Lead.workspace_id == workspace_id,
            Lead.pipeline_kind == "business",
            (Lead.disposition == "review") | (Company.match_status == "needs_review"),
        )
    ).all()
    for lead, company in business_rows:
        items.append(
            ReviewQueueItem(
                id=lead.id,
                kind="business_lead",
                title=company.display_name,
                summary="Business qualification or identity evidence requires operator review.",
                status=lead.disposition,
                created_at=lead.created_at,
                primary_subject_id=company.id,
                lead_id=lead.id,
                allowed_actions=["open_lead"],
            )
        )

    individual_candidates = session.scalars(
        select(IndividualDiscoveryCandidate).where(
            IndividualDiscoveryCandidate.workspace_id == workspace_id,
            IndividualDiscoveryCandidate.status == "needs_review",
        )
    ).all()
    for individual_candidate in individual_candidates:
        actions = ["promote_new", "reject"]
        if individual_candidate.possible_match_person_id is not None:
            actions.insert(1, "link_existing")
        items.append(
            ReviewQueueItem(
                id=individual_candidate.id,
                kind="individual_candidate",
                title=individual_candidate.display_name,
                summary=individual_candidate.service_summary
                or "Fictional individual candidate requires identity review.",
                status=individual_candidate.status,
                created_at=individual_candidate.created_at,
                primary_subject_id=individual_candidate.id,
                source_url=individual_candidate.source_url,
                score=float(individual_candidate.score),
                possible_match_person_id=individual_candidate.possible_match_person_id,
                allowed_actions=actions,
            )
        )

    entity_candidates = session.scalars(
        select(EntityMatchCandidate).where(
            EntityMatchCandidate.workspace_id == workspace_id,
            EntityMatchCandidate.status == "pending",
        )
    ).all()
    for entity_candidate in entity_candidates:
        left_id, right_id = candidate_subject_ids(entity_candidate)
        if entity_candidate.entity_kind == "company":
            left_company = session.get(Company, left_id)
            right_company = session.get(Company, right_id)
            if left_company is None or right_company is None:
                continue
            left_name, right_name = left_company.display_name, right_company.display_name
        else:
            left_person = session.get(Person, left_id)
            right_person = session.get(Person, right_id)
            if left_person is None or right_person is None:
                continue
            left_name, right_name = left_person.display_name, right_person.display_name
        items.append(
            ReviewQueueItem(
                id=entity_candidate.id,
                kind="entity_match",
                title=f"{left_name} ↔ {right_name}",
                summary=str(
                    entity_candidate.features_json.get("explanation", "Potential duplicate")
                ),
                status=entity_candidate.status,
                created_at=entity_candidate.created_at,
                primary_subject_id=left_id,
                secondary_subject_id=right_id,
                score=entity_candidate.score,
                allowed_actions=["merge_left", "merge_right", "reject"],
            )
        )

    hypothesis_rows = session.execute(
        select(OpportunityHypothesis, OpportunityAnalysisRun, Lead, Company)
        .join(
            OpportunityAnalysisRun,
            OpportunityAnalysisRun.id == OpportunityHypothesis.analysis_run_id,
        )
        .join(Lead, Lead.id == OpportunityAnalysisRun.lead_id)
        .join(Company, Company.id == Lead.company_id)
        .where(
            OpportunityHypothesis.workspace_id == workspace_id,
            OpportunityHypothesis.review_status == "unreviewed",
        )
    ).all()
    for hypothesis, _run, lead, company in hypothesis_rows:
        items.append(
            ReviewQueueItem(
                id=hypothesis.id,
                kind="opportunity_hypothesis",
                title=hypothesis.title,
                summary=f"{company.display_name}: {hypothesis.summary}",
                status=hypothesis.review_status,
                created_at=hypothesis.created_at,
                primary_subject_id=hypothesis.id,
                lead_id=lead.id,
                score=hypothesis.confidence,
                allowed_actions=["accept", "reject"],
            )
        )

    items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    counts = Counter(item.kind for item in items)
    return ReviewQueuePage(
        items=items[:limit], counts={kind: count for kind, count in counts.items()}
    )
