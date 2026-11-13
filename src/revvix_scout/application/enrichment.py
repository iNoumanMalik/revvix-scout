"""M6 fictional enrichment execution with budgets and durable evidence."""

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from revvix_scout.application.usage import (
    reserve_enrichment_budget,
    settle_enrichment_usage,
)
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    BudgetReservation,
    CompanyDomain,
    CompanyEvidence,
    EnrichmentPlan,
    EnrichmentRun,
    EnrichmentStep,
    EvidenceClaim,
    Job,
    JobAttempt,
    Lead,
    LeadEvidence,
    PersonEvidence,
    PersonProfile,
    ProviderConfig,
    SourceDocument,
)
from revvix_scout.domain.enrichment import (
    ClaimSnapshot,
    WaterfallStepDefinition,
    select_next_waterfall_step,
)
from revvix_scout.providers.enrichment_contracts import (
    EnrichmentProviderRegistry,
    EnrichmentQuery,
    EnrichmentResult,
)


class EnrichmentError(RuntimeError):
    pass


class EnrichmentCollectionNotApprovedError(EnrichmentError):
    pass


def execute_enrichment(
    *,
    session: Session,
    settings: Settings,
    registry: EnrichmentProviderRegistry,
    lead_id: UUID,
    idempotency_key: str,
) -> EnrichmentRun:
    """Execute the next fictional enrichment step for one qualified lead."""

    existing_job = session.scalar(
        select(Job).where(
            Job.workspace_id == settings.default_workspace_id,
            Job.job_type == "lead_enrichment",
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        existing_run = session.scalar(
            select(EnrichmentRun).where(EnrichmentRun.job_id == existing_job.id)
        )
        if existing_run is None:
            raise EnrichmentError("Existing enrichment job has no run")
        return existing_run

    lead = session.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.workspace_id == settings.default_workspace_id,
        )
    )
    if lead is None:
        raise EnrichmentError("Lead not found")
    plan = session.scalar(
        select(EnrichmentPlan)
        .where(
            EnrichmentPlan.workspace_id == settings.default_workspace_id,
            EnrichmentPlan.icp_version_id == lead.icp_version_id,
            EnrichmentPlan.pipeline_kind == lead.pipeline_kind,
            EnrichmentPlan.status == "published",
        )
        .order_by(EnrichmentPlan.version.desc())
        .limit(1)
    )
    if plan is None:
        raise EnrichmentError("No published enrichment plan for lead")
    steps = session.scalars(
        select(EnrichmentStep)
        .where(EnrichmentStep.plan_id == plan.id)
        .order_by(EnrichmentStep.step_order)
    ).all()
    claims = session.scalars(
        select(EvidenceClaim)
        .join(LeadEvidence, LeadEvidence.evidence_claim_id == EvidenceClaim.id)
        .where(LeadEvidence.lead_id == lead.id)
    ).all()
    now = datetime.now(UTC)
    decision = select_next_waterfall_step(
        required_fields=tuple(plan.required_fields_json),
        claims=tuple(
            ClaimSnapshot(
                field=claim.claim_type,
                normalized_value=claim.normalized_value,
                retrieved_at=claim.retrieved_at,
                valid_until=claim.valid_until,
                verification_status=claim.verification_status,
                superseded=claim.review_status == "superseded",
            )
            for claim in claims
        ),
        steps=tuple(
            WaterfallStepDefinition(
                key=str(step.step_order),
                requested_fields=tuple(step.requested_fields_json),
                freshness_days=step.freshness_days,
                enabled=step.enabled,
            )
            for step in steps
        ),
        completed_step_keys=frozenset(),
        now=now,
    )
    job = Job(
        workspace_id=settings.default_workspace_id,
        job_type="lead_enrichment",
        idempotency_key=idempotency_key,
        status="running",
        input_json={"lead_id": str(lead.id), "plan_id": str(plan.id)},
        max_attempts=1,
        next_attempt_at=now,
        started_at=now,
        worker_id="inline-enrichment-api",
    )
    session.add(job)
    session.flush()
    run = EnrichmentRun(
        workspace_id=settings.default_workspace_id,
        lead_id=lead.id,
        plan_id=plan.id,
        job_id=job.id,
        status="running",
        started_at=now,
        completed_fields_json=[],
    )
    session.add(run)
    session.flush()
    if decision.action == "stop":
        run.status = job.status = "succeeded"
        run.stop_reason = decision.reason
        run.completed_at = job.completed_at = now
        job.worker_id = None
        session.commit()
        return run

    step = next((item for item in steps if str(item.step_order) == decision.step_key), None)
    if step is None:
        raise EnrichmentError("Selected enrichment step disappeared")
    provider = registry.get(step.provider_key)
    config = session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == settings.default_workspace_id,
            ProviderConfig.provider_key == step.provider_key,
        )
    )
    if config is None or not config.enabled:
        raise EnrichmentError("Enrichment provider is disabled")
    if provider.is_live or config.live_calls_allowed:
        raise EnrichmentCollectionNotApprovedError("Live enrichment is disabled")
    if not bool(config.config_json.get("fictional_data_only")):
        raise EnrichmentCollectionNotApprovedError("Provider must remain fictional-only")

    query = _build_query(session, lead, decision.requested_fields)
    run.current_step_order = step.step_order
    reservation = reserve_enrichment_budget(
        session=session,
        settings=settings,
        run=run,
        provider_key=step.provider_key,
        operation=step.operation,
        estimated_units=provider.estimate_units(query),
        now=now,
    )
    attempt = JobAttempt(
        job_id=job.id,
        attempt_number=1,
        status="running",
        retryable=False,
        started_at=now,
    )
    session.add(attempt)
    session.commit()

    result: EnrichmentResult | None = None
    failure: Exception | None = None
    try:
        result = provider.enrich(query)
        _validate_fixture_result(result)
    except Exception as exc:
        failure = exc

    loaded_run = session.get(EnrichmentRun, run.id)
    loaded_job = session.get(Job, job.id)
    loaded_attempt = session.get(JobAttempt, attempt.id)
    loaded_reservation = session.get(BudgetReservation, reservation.id)
    if (
        loaded_run is None
        or loaded_job is None
        or loaded_attempt is None
        or loaded_reservation is None
    ):
        raise EnrichmentError("Enrichment run state disappeared")
    run = loaded_run
    job = loaded_job
    attempt = loaded_attempt
    reservation = loaded_reservation
    conflicts: set[str] = set()
    if result is not None and failure is None:
        try:
            with session.begin_nested():
                conflicts = _persist_result(
                    session=session,
                    settings=settings,
                    run=run,
                    lead=lead,
                    result=result,
                    provider_key=step.provider_key,
                )
                session.flush()
        except Exception as exc:
            failure = exc

    finished_at = datetime.now(UTC)
    if result is None and failure is None:
        failure = EnrichmentError("Provider returned no enrichment result")
    actual_units = result.actual_units if result is not None else 0
    if failure is not None:
        run.status = job.status = attempt.status = "failed"
        run.stop_reason = "provider_or_persistence_failure"
        message = str(failure)[:500]
        job.error_code = attempt.error_category = "processing"
        job.error_message = attempt.error_message = message
        usage_outcome = "failed"
    else:
        assert result is not None
        returned_fields = {claim.claim_type for claim in result.claims}
        completed = sorted(returned_fields - conflicts)
        run.completed_fields_json = completed
        required = set(plan.required_fields_json)
        if conflicts:
            run.status = job.status = "partially_succeeded"
            run.stop_reason = "conflicting_claims"
            usage_outcome = "partial"
        elif required.issubset(set(completed)):
            run.status = job.status = "succeeded"
            run.stop_reason = result.stop_reason or "required_fields_satisfied"
            usage_outcome = "succeeded"
        else:
            run.status = job.status = "partially_succeeded"
            run.stop_reason = result.stop_reason or "provider_fields_incomplete"
            usage_outcome = "partial"
        attempt.status = "succeeded"
    run.completed_at = job.completed_at = attempt.completed_at = finished_at
    job.worker_id = None
    settle_enrichment_usage(
        session=session,
        settings=settings,
        run=run,
        reservation=reservation,
        provider_key=step.provider_key,
        operation=step.operation,
        actual_units=actual_units,
        outcome=usage_outcome,
        now=finished_at,
    )
    session.commit()
    return run


def _build_query(
    session: Session, lead: Lead, requested_fields: tuple[str, ...]
) -> EnrichmentQuery:
    domain = None
    profile = None
    if lead.company_id is not None:
        domain = session.scalar(
            select(CompanyDomain.normalized_domain)
            .where(CompanyDomain.company_id == lead.company_id)
            .order_by(CompanyDomain.domain_type, CompanyDomain.created_at)
            .limit(1)
        )
    if lead.person_id is not None:
        profile = session.scalar(
            select(PersonProfile.normalized_url)
            .where(PersonProfile.person_id == lead.person_id)
            .order_by(PersonProfile.created_at)
            .limit(1)
        )
    return EnrichmentQuery(
        lead_id=lead.id,
        pipeline_kind=lead.pipeline_kind,
        company_id=lead.company_id,
        person_id=lead.person_id,
        requested_fields=requested_fields,
        canonical_domain=domain,
        canonical_profile_url=profile,
    )


def _validate_fixture_result(result: EnrichmentResult) -> None:
    host = urlsplit(result.source.canonical_url).hostname
    if not result.source.metadata_only:
        raise EnrichmentCollectionNotApprovedError("Raw enrichment content is disabled")
    if host is None or not host.endswith(".invalid"):
        raise EnrichmentCollectionNotApprovedError("Fixture source must use .invalid")


def _persist_result(
    *,
    session: Session,
    settings: Settings,
    run: EnrichmentRun,
    lead: Lead,
    result: EnrichmentResult,
    provider_key: str,
) -> set[str]:
    document = session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == settings.default_workspace_id,
            SourceDocument.content_hash == result.source.content_hash,
        )
    )
    if document is None:
        document = SourceDocument(
            workspace_id=settings.default_workspace_id,
            lead_id=lead.id,
            enrichment_run_id=run.id,
            source_name=provider_key,
            source_type="provider_record",
            provider_key=provider_key,
            source_record_id=result.source.provider_record_id,
            canonical_url=result.source.canonical_url,
            content_hash=result.source.content_hash,
            license_policy_json=result.source.license_policy,
            cache_expires_at=result.source.cache_expires_at,
            redaction_status="metadata_only",
            observed_at=min(
                (claim.observed_at for claim in result.claims), default=result.source.retrieved_at
            ),
            retrieved_at=result.source.retrieved_at,
        )
        session.add(document)
        session.flush()
    elif document.lead_id != lead.id:
        raise EnrichmentError("Cached enrichment source belongs to another lead")

    conflicts: set[str] = set()
    for value in result.claims:
        value_hash = hashlib.sha256(value.normalized_value.encode()).hexdigest()
        claim = session.scalar(
            select(EvidenceClaim).where(
                EvidenceClaim.source_document_id == document.id,
                EvidenceClaim.claim_type == value.claim_type,
                EvidenceClaim.value_hash == value_hash,
            )
        )
        if claim is None:
            claim = EvidenceClaim(
                workspace_id=settings.default_workspace_id,
                source_document_id=document.id,
                claim_type=value.claim_type,
                value_json=value.value,
                normalized_value=value.normalized_value,
                value_hash=value_hash,
                classification=value.classification,
                confidence=value.confidence,
                verification_status=value.verification_status,
                review_status="unreviewed",
                valid_until=value.valid_until,
                extractor_version="fictional-fixture-1",
                observed_at=value.observed_at,
                retrieved_at=result.source.retrieved_at,
            )
            session.add(claim)
            session.flush()
        _link_claim(session, settings, lead, claim)
        existing = session.scalars(
            select(EvidenceClaim)
            .join(LeadEvidence, LeadEvidence.evidence_claim_id == EvidenceClaim.id)
            .where(
                LeadEvidence.lead_id == lead.id,
                EvidenceClaim.claim_type == claim.claim_type,
                EvidenceClaim.id != claim.id,
                EvidenceClaim.review_status.notin_(("rejected", "superseded")),
                EvidenceClaim.verification_status != "invalid",
            )
        ).all()
        contradictory = [
            item for item in existing if item.normalized_value != claim.normalized_value
        ]
        if contradictory:
            conflicts.add(claim.claim_type)
            claim.verification_status = "conflicting"
            for item in contradictory:
                item.verification_status = "conflicting"
    return conflicts


def _link_claim(
    session: Session,
    settings: Settings,
    lead: Lead,
    claim: EvidenceClaim,
) -> None:
    if session.get(LeadEvidence, (lead.id, claim.id)) is None:
        session.add(LeadEvidence(lead_id=lead.id, evidence_claim_id=claim.id))
    if lead.company_id is not None:
        if session.get(CompanyEvidence, (lead.company_id, claim.id)) is None:
            session.add(
                CompanyEvidence(
                    workspace_id=settings.default_workspace_id,
                    company_id=lead.company_id,
                    evidence_claim_id=claim.id,
                )
            )
    elif (
        lead.person_id is not None
        and session.get(PersonEvidence, (lead.person_id, claim.id)) is None
    ):
        session.add(
            PersonEvidence(
                workspace_id=settings.default_workspace_id,
                person_id=lead.person_id,
                evidence_claim_id=claim.id,
            )
        )
