"""M7 provider-free opportunity analysis with grounding and human review."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from revvix_scout.application.usage import (
    reserve_opportunity_analysis_budget,
    settle_opportunity_analysis_usage,
)
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    AiPromptDefinition,
    BudgetReservation,
    EvidenceClaim,
    Job,
    JobAttempt,
    Lead,
    LeadEvidence,
    OpportunityAnalysisRun,
    OpportunityHypothesis,
    OpportunityHypothesisEvidence,
    OpportunityReviewDecision,
    ProviderConfig,
)
from revvix_scout.domain.opportunities import (
    AnalysisEvidence,
    OpportunityAnalysisDraft,
    partition_untrusted_evidence,
    validate_opportunity_analysis,
)
from revvix_scout.providers.opportunity_contracts import (
    OpportunityAnalysisProviderRegistry,
    OpportunityAnalysisQuery,
    OpportunityAnalysisResult,
)

OPERATION = "opportunity_analysis"


class OpportunityAnalysisError(RuntimeError):
    pass


class OpportunityAnalysisNotApprovedError(OpportunityAnalysisError):
    pass


def execute_opportunity_analysis(
    *,
    session: Session,
    settings: Settings,
    registry: OpportunityAnalysisProviderRegistry,
    lead_id: UUID,
    provider_key: str,
    idempotency_key: str,
) -> OpportunityAnalysisRun:
    """Run one grounded fictional analysis without changing deterministic scoring."""

    existing_job = session.scalar(
        select(Job).where(
            Job.workspace_id == settings.default_workspace_id,
            Job.job_type == "opportunity_analysis",
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        existing_run = session.scalar(
            select(OpportunityAnalysisRun).where(OpportunityAnalysisRun.job_id == existing_job.id)
        )
        if existing_run is None:
            raise OpportunityAnalysisError("Existing opportunity job has no run")
        return existing_run

    lead = session.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.workspace_id == settings.default_workspace_id,
        )
    )
    if lead is None:
        raise OpportunityAnalysisError("Lead not found")
    prompt = session.scalar(
        select(AiPromptDefinition)
        .where(
            AiPromptDefinition.workspace_id == settings.default_workspace_id,
            AiPromptDefinition.prompt_key == "opportunity-brief",
            AiPromptDefinition.status == "published",
        )
        .order_by(AiPromptDefinition.version.desc())
        .limit(1)
    )
    if prompt is None:
        raise OpportunityAnalysisError("No published opportunity prompt")
    claims = session.scalars(
        select(EvidenceClaim)
        .join(LeadEvidence, LeadEvidence.evidence_claim_id == EvidenceClaim.id)
        .where(
            LeadEvidence.lead_id == lead.id,
            EvidenceClaim.classification != "inferred",
            EvidenceClaim.verification_status != "invalid",
            EvidenceClaim.review_status.not_in(("rejected", "superseded")),
        )
        .order_by(EvidenceClaim.claim_type, EvidenceClaim.id)
    ).all()
    evidence = tuple(
        AnalysisEvidence(
            claim_id=claim.id,
            claim_type=claim.claim_type,
            normalized_value=claim.normalized_value,
            classification=claim.classification,
            verification_status=claim.verification_status,
        )
        for claim in claims
    )
    safety = partition_untrusted_evidence(evidence)
    fingerprint = _input_fingerprint(prompt, safety.safe_evidence)
    existing_input_run = session.scalar(
        select(OpportunityAnalysisRun).where(
            OpportunityAnalysisRun.workspace_id == settings.default_workspace_id,
            OpportunityAnalysisRun.lead_id == lead.id,
            OpportunityAnalysisRun.prompt_definition_id == prompt.id,
            OpportunityAnalysisRun.input_fingerprint == fingerprint,
        )
    )
    if existing_input_run is not None:
        return existing_input_run
    now = datetime.now(UTC)
    job = Job(
        workspace_id=settings.default_workspace_id,
        job_type="opportunity_analysis",
        idempotency_key=idempotency_key,
        status="running",
        input_json={"lead_id": str(lead.id), "prompt_definition_id": str(prompt.id)},
        max_attempts=1,
        next_attempt_at=now,
        started_at=now,
        worker_id="inline-opportunity-api",
    )
    session.add(job)
    session.flush()
    run = OpportunityAnalysisRun(
        workspace_id=settings.default_workspace_id,
        lead_id=lead.id,
        job_id=job.id,
        prompt_definition_id=prompt.id,
        provider_key=provider_key,
        input_fingerprint=fingerprint,
        evidence_snapshot_json=[str(item.claim_id) for item in safety.safe_evidence],
        excluded_claim_ids_json=[str(item) for item in safety.excluded_claim_ids],
        status="running",
        injection_detected=bool(safety.excluded_claim_ids),
        started_at=now,
    )
    session.add(run)
    session.flush()
    if not safety.safe_evidence:
        run.status = job.status = "succeeded"
        run.missing_fields_json = ["evidence"]
        run.completed_at = job.completed_at = now
        job.worker_id = None
        session.commit()
        return run

    provider = registry.get(provider_key)
    config = session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == settings.default_workspace_id,
            ProviderConfig.provider_key == provider_key,
        )
    )
    if config is None or not config.enabled:
        raise OpportunityAnalysisError("Opportunity-analysis provider is disabled")
    if provider.is_live or provider.supports_tools or config.live_calls_allowed:
        raise OpportunityAnalysisNotApprovedError("Live or tool-enabled AI analysis is disabled")
    if not bool(config.config_json.get("fictional_data_only")):
        raise OpportunityAnalysisNotApprovedError("AI analysis must remain fictional-only")
    categories = tuple(str(item) for item in prompt.taxonomy_json.get("categories", ()))
    query = OpportunityAnalysisQuery(
        lead_id=lead.id,
        pipeline_kind=lead.pipeline_kind,
        prompt_key=prompt.prompt_key,
        prompt_version=prompt.version,
        output_schema_version=prompt.output_schema_version,
        taxonomy_version=prompt.taxonomy_version,
        allowed_categories=categories,
        evidence=safety.safe_evidence,
    )
    reservation = reserve_opportunity_analysis_budget(
        session=session,
        settings=settings,
        run=run,
        provider_key=provider_key,
        operation=OPERATION,
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

    result: OpportunityAnalysisResult | None = None
    failure: Exception | None = None
    try:
        result = provider.analyze(query)
        validate_opportunity_analysis(
            result.analysis,
            evidence=safety.safe_evidence,
            allowed_categories=frozenset(categories),
        )
    except Exception as exc:
        failure = exc

    run = _required(session.get(OpportunityAnalysisRun, run.id), "Analysis run disappeared")
    job = _required(session.get(Job, job.id), "Analysis job disappeared")
    attempt = _required(session.get(JobAttempt, attempt.id), "Analysis attempt disappeared")
    reservation = _required(
        session.get(BudgetReservation, reservation.id), "Analysis reservation disappeared"
    )
    finished_at = datetime.now(UTC)
    if result is not None and failure is None:
        try:
            _persist_analysis(session, settings, run, result.analysis)
        except Exception as exc:
            failure = exc
    if failure is not None:
        run.status = job.status = attempt.status = "failed"
        run.error_code = job.error_code = attempt.error_category = "invalid_analysis"
        message = str(failure)[:500]
        run.error_message = job.error_message = attempt.error_message = message
        actual_units = result.actual_units if result is not None else 0
        outcome = "failed"
    else:
        if result is None:
            raise OpportunityAnalysisError("Provider returned no analysis result")
        run.status = job.status = attempt.status = "succeeded"
        run.model_name = result.model_name
        run.model_version = result.model_version
        run.prompt_tokens = result.prompt_tokens
        run.completion_tokens = result.completion_tokens
        run.missing_fields_json = list(result.analysis.missing_fields)
        run.contradictions_json = list(result.analysis.contradictions)
        actual_units = result.actual_units
        outcome = "succeeded"
    run.completed_at = job.completed_at = attempt.completed_at = finished_at
    job.worker_id = None
    settle_opportunity_analysis_usage(
        session=session,
        settings=settings,
        run=run,
        reservation=reservation,
        provider_key=provider_key,
        operation=OPERATION,
        actual_units=actual_units,
        outcome=outcome,
        now=finished_at,
    )
    session.commit()
    return run


def review_opportunity_hypothesis(
    *,
    session: Session,
    settings: Settings,
    hypothesis_id: UUID,
    decision: str,
    reason: str,
) -> OpportunityHypothesis:
    """Append one final operator review decision for an AI hypothesis."""

    hypothesis = session.scalar(
        select(OpportunityHypothesis)
        .where(
            OpportunityHypothesis.id == hypothesis_id,
            OpportunityHypothesis.workspace_id == settings.default_workspace_id,
        )
        .with_for_update()
    )
    if hypothesis is None:
        raise OpportunityAnalysisError("Opportunity hypothesis not found")
    if hypothesis.review_status != "unreviewed":
        raise OpportunityAnalysisError("Opportunity hypothesis already reviewed")
    if decision not in {"accept", "reject"}:
        raise OpportunityAnalysisError("Unsupported opportunity review decision")
    now = datetime.now(UTC)
    hypothesis.review_status = "accepted" if decision == "accept" else "rejected"
    session.add(
        OpportunityReviewDecision(
            workspace_id=settings.default_workspace_id,
            hypothesis_id=hypothesis.id,
            decision=decision,
            reason=reason,
            actor_type="operator",
            decided_at=now,
        )
    )
    session.commit()
    return hypothesis


def _persist_analysis(
    session: Session,
    settings: Settings,
    run: OpportunityAnalysisRun,
    analysis: OpportunityAnalysisDraft,
) -> None:
    for item in analysis.hypotheses:
        hypothesis = OpportunityHypothesis(
            workspace_id=settings.default_workspace_id,
            analysis_run_id=run.id,
            category=item.category,
            title=item.title,
            summary=item.summary,
            confidence=item.confidence,
            review_status="unreviewed",
            missing_fields_json=list(item.missing_fields),
            contradictions_json=list(item.contradictions),
        )
        session.add(hypothesis)
        session.flush()
        for claim_id in item.citation_claim_ids:
            session.add(
                OpportunityHypothesisEvidence(
                    hypothesis_id=hypothesis.id,
                    evidence_claim_id=claim_id,
                )
            )
    session.flush()


def _input_fingerprint(prompt: AiPromptDefinition, evidence: tuple[AnalysisEvidence, ...]) -> str:
    payload = {
        "prompt_hash": prompt.prompt_hash,
        "evidence": [
            {
                "id": str(item.claim_id),
                "type": item.claim_type,
                "value": item.normalized_value,
                "classification": item.classification,
                "verification": item.verification_status,
            }
            for item in evidence
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required[T](value: T | None, message: str) -> T:
    if value is None:
        raise OpportunityAnalysisError(message)
    return value
