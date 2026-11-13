"""Versioned FastAPI routes for provider-free business and individual slices."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import (
    DecisionMakerCandidateView,
    DecisionMakerRoleView,
    DecisionMakerRunRequest,
    DecisionMakerRunView,
    DiscoveryCandidateView,
    DiscoveryRunRequest,
    DiscoveryRunView,
    EnrichmentClaimView,
    EnrichmentRunRequest,
    EnrichmentRunView,
    EntityMatchRequest,
    EntityMatchReviewRequest,
    EntityMatchView,
    EntityMergeEventView,
    EntityUnmergeRequest,
    ImportSummary,
    IndividualCandidateView,
    IndividualDiscoveryRunRequest,
    IndividualDiscoveryRunView,
    IndividualLeadPage,
    IndividualReviewRequest,
    IndividualReviewResult,
    LeadDetail,
    LeadPage,
    ManualDiscoveryRequest,
    OpportunityAnalysisRunRequest,
    OpportunityAnalysisRunView,
    OpportunityHypothesisView,
    OpportunityReviewRequest,
    PersonSuppressionRequest,
    PersonSuppressionView,
)
from revvix_scout.application.decision_makers import (
    DecisionMakerCollectionNotApprovedError,
    DecisionMakerDiscoveryError,
    execute_decision_maker_discovery,
    promote_decision_maker_candidate,
)
from revvix_scout.application.discovery import (
    DiscoveryError,
    ProviderDisabledError,
    execute_discovery,
    process_discovery_run,
)
from revvix_scout.application.enrichment import (
    EnrichmentCollectionNotApprovedError,
    EnrichmentError,
    execute_enrichment,
)
from revvix_scout.application.entity_resolution import (
    EntityResolutionError,
    candidate_subject_ids,
    create_match_candidate,
    review_match_candidate,
    unmerge_entity_event,
)
from revvix_scout.application.imports import ImportContractError, import_business_csv
from revvix_scout.application.individual_discovery import (
    IndividualCollectionNotApprovedError,
    IndividualDiscoveryError,
    execute_individual_discovery,
)
from revvix_scout.application.individual_leads import (
    IndividualCandidateNotFoundError,
    IndividualReviewConflictError,
    IndividualSuppressedError,
    PersonNotFoundError,
    list_individual_leads,
    resolve_individual_candidate,
    suppress_person,
)
from revvix_scout.application.leads import (
    InvalidCursorError,
    LeadFilters,
    LeadNotFoundError,
    export_leads_csv,
    get_lead_detail,
    list_leads,
)
from revvix_scout.application.opportunities import (
    OpportunityAnalysisError,
    OpportunityAnalysisNotApprovedError,
    execute_opportunity_analysis,
    review_opportunity_hypothesis,
)
from revvix_scout.application.usage import BudgetExceededError
from revvix_scout.config import Settings, get_settings
from revvix_scout.db.models import (
    AiPromptDefinition,
    DecisionMakerCandidate,
    DiscoveryCandidate,
    DiscoveryRun,
    EnrichmentRun,
    EntityMatchCandidate,
    EntityMergeEvent,
    EvidenceClaim,
    IndividualDiscoveryCandidate,
    Job,
    JobAttempt,
    OpportunityAnalysisRun,
    OpportunityHypothesis,
    OpportunityHypothesisEvidence,
    SourceDocument,
)
from revvix_scout.db.session import get_db_session
from revvix_scout.providers.contracts import (
    DiscoveredBusiness,
    DiscoveryQuery,
    ProviderNotRegisteredError,
)
from revvix_scout.providers.csv_input import CsvDiscoveryContractError, CsvInputProvider
from revvix_scout.providers.decision_maker_contracts import (
    DecisionMakerProviderNotRegisteredError,
)
from revvix_scout.providers.enrichment_contracts import (
    EnrichmentProviderNotRegisteredError,
)
from revvix_scout.providers.individual_contracts import (
    IndividualDiscoveryQuery,
    IndividualProviderNotRegisteredError,
)
from revvix_scout.providers.opportunity_contracts import (
    OpportunityAnalysisProviderNotRegisteredError,
)
from revvix_scout.providers.registry import (
    create_decision_maker_provider_registry,
    create_enrichment_provider_registry,
    create_individual_provider_registry,
    create_opportunity_analysis_provider_registry,
    create_provider_registry,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
provider_registry = create_provider_registry()
individual_provider_registry = create_individual_provider_registry()
decision_maker_provider_registry = create_decision_maker_provider_registry()
enrichment_provider_registry = create_enrichment_provider_registry()
opportunity_analysis_provider_registry = create_opportunity_analysis_provider_registry()


@router.get("/health", tags=["system"])
def health(session: DbSession) -> dict[str, str]:
    """Verify that the API process can query PostgreSQL."""

    session.execute(text("select 1"))
    return {"status": "ok"}


@router.post("/v1/imports/business-csv", response_model=ImportSummary, tags=["imports"])
def import_businesses(
    file: Annotated[UploadFile, File(description="UTF-8 CSV using schema_version 1")],
    session: DbSession,
    settings: AppSettings,
) -> ImportSummary:
    """Import, deduplicate, evidence-link, and score business candidates."""

    try:
        content = file.file.read(settings.max_import_bytes + 1)
        return import_business_csv(
            session=session,
            settings=settings,
            filename=file.filename or "businesses.csv",
            content=content,
        )
    except ImportContractError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/leads", response_model=LeadPage, tags=["leads"])
def read_leads(
    session: DbSession,
    settings: AppSettings,
    disposition: Literal["qualified", "review", "unqualified", "disqualified"] | None = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> LeadPage:
    """List leads with stable cursor pagination."""

    try:
        return list_leads(
            session=session,
            settings=settings,
            filters=LeadFilters(disposition=disposition, min_score=min_score),
            limit=limit,
            cursor=cursor,
        )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/leads/export.csv", tags=["leads"])
def export_leads(
    session: DbSession,
    settings: AppSettings,
    disposition: Literal["qualified", "review", "unqualified", "disqualified"] | None = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
) -> Response:
    """Export allow-listed lead fields as a safe CSV file."""

    csv_content = export_leads_csv(
        session=session,
        settings=settings,
        filters=LeadFilters(disposition=disposition, min_score=min_score),
    )
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="revvix-scout-leads.csv"'},
    )


@router.get("/v1/leads/{lead_id}", response_model=LeadDetail, tags=["leads"])
def read_lead(lead_id: UUID, session: DbSession, settings: AppSettings) -> LeadDetail:
    """Read one lead with evidence and score explanation."""

    try:
        return get_lead_detail(session=session, settings=settings, lead_id=lead_id)
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Lead not found") from exc


@router.post("/v1/discovery-runs", response_model=DiscoveryRunView, tags=["discovery"])
def create_discovery_run(
    request: DiscoveryRunRequest, session: DbSession, settings: AppSettings
) -> DiscoveryRunView:
    """Run one bounded fictional-provider discovery page."""

    try:
        run = execute_discovery(
            session=session,
            settings=settings,
            registry=provider_registry,
            provider_key=request.provider_key,
            query=DiscoveryQuery(
                search_text=request.search_text,
                country_code=request.country_code.upper(),
                region=request.region,
                limit=request.limit,
                cursor=request.cursor,
            ),
            idempotency_key=request.idempotency_key,
        )
    except (ProviderDisabledError, ProviderNotRegisteredError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except DiscoveryError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _discovery_view(session, run)


@router.post("/v1/discovery-runs/manual", response_model=DiscoveryRunView, tags=["discovery"])
def create_manual_discovery_run(
    request: ManualDiscoveryRequest, session: DbSession, settings: AppSettings
) -> DiscoveryRunView:
    """Process allow-listed records supplied directly by an operator."""

    records = tuple(
        DiscoveredBusiness(
            provider_record_id=item.provider_record_id,
            company_name=item.company_name,
            domain=item.domain,
            country_code=item.country_code,
            region=item.region,
            industry=item.industry,
            employee_count=item.employee_count,
            legal_form=item.legal_form,
            company_status=item.company_status,
            source_url=str(item.source_url),
            observed_at=item.observed_at,
        )
        for item in request.records
    )
    return _execute_discovery_request(
        session=session,
        settings=settings,
        provider_key="manual_input",
        query=DiscoveryQuery(
            search_text="operator supplied records",
            limit=request.limit,
            cursor=request.cursor,
            seed_records=records,
        ),
        idempotency_key=request.idempotency_key,
    )


@router.post("/v1/discovery-runs/csv", response_model=DiscoveryRunView, tags=["discovery"])
def create_csv_discovery_run(
    file: Annotated[UploadFile, File(description="UTF-8 discovery CSV schema version 1")],
    session: DbSession,
    settings: AppSettings,
    idempotency_key: Annotated[str, Form(min_length=8, max_length=160)],
    limit: Annotated[int, Form(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Form(max_length=500)] = None,
) -> DiscoveryRunView:
    """Parse a strict CSV into allow-listed records and run the CSV adapter."""

    try:
        content = file.file.read(settings.max_import_bytes + 1)
        records = CsvInputProvider.parse(
            content,
            max_bytes=settings.max_import_bytes,
            max_rows=settings.max_import_rows,
        )
    except CsvDiscoveryContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _execute_discovery_request(
        session=session,
        settings=settings,
        provider_key="csv_input",
        query=DiscoveryQuery(
            search_text="CSV supplied records",
            limit=limit,
            cursor=cursor,
            seed_records=records,
        ),
        idempotency_key=idempotency_key,
    )


@router.post(
    "/v1/discovery-runs/{run_id}/resume", response_model=DiscoveryRunView, tags=["discovery"]
)
def resume_discovery_run(
    run_id: UUID, session: DbSession, settings: AppSettings
) -> DiscoveryRunView:
    """Claim a due queued attempt; not-yet-due and already-running runs are unchanged."""

    try:
        run = process_discovery_run(
            session=session,
            settings=settings,
            registry=provider_registry,
            run_id=run_id,
            worker_id="inline-resume-api",
        )
    except (ProviderDisabledError, ProviderNotRegisteredError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except DiscoveryError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _discovery_view(session, run)


@router.get("/v1/discovery-runs/{run_id}", response_model=DiscoveryRunView, tags=["discovery"])
def read_discovery_run(run_id: UUID, session: DbSession, settings: AppSettings) -> DiscoveryRunView:
    run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.id == run_id,
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            DiscoveryRun.pipeline_kind == "business",
            DiscoveryRun.discovery_kind == "company",
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return _discovery_view(session, run)


@router.post(
    "/v1/individual-discovery-runs",
    response_model=IndividualDiscoveryRunView,
    tags=["individual-discovery"],
)
def create_individual_discovery_run(
    request: IndividualDiscoveryRunRequest,
    session: DbSession,
    settings: AppSettings,
) -> IndividualDiscoveryRunView:
    """Run one bounded page against the fictional-only individual adapter."""

    try:
        run = execute_individual_discovery(
            session=session,
            settings=settings,
            registry=individual_provider_registry,
            provider_key=request.provider_key,
            query=IndividualDiscoveryQuery(
                search_text=request.search_text,
                country_code=request.country_code,
                region=request.region,
                limit=request.limit,
                cursor=request.cursor,
            ),
            idempotency_key=request.idempotency_key,
        )
    except IndividualProviderNotRegisteredError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IndividualCollectionNotApprovedError as exc:
        session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except IndividualDiscoveryError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _individual_discovery_view(session, run)


@router.get(
    "/v1/individual-discovery-runs/{run_id}",
    response_model=IndividualDiscoveryRunView,
    tags=["individual-discovery"],
)
def read_individual_discovery_run(
    run_id: UUID, session: DbSession, settings: AppSettings
) -> IndividualDiscoveryRunView:
    run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.id == run_id,
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            DiscoveryRun.pipeline_kind == "individual",
            DiscoveryRun.discovery_kind == "individual",
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Individual discovery run not found")
    return _individual_discovery_view(session, run)


@router.post(
    "/v1/individual-candidates/{candidate_id}/review",
    response_model=IndividualReviewResult,
    tags=["individual-discovery"],
)
def review_individual_candidate(
    candidate_id: UUID,
    request: IndividualReviewRequest,
    session: DbSession,
    settings: AppSettings,
) -> IndividualReviewResult:
    """Record one final human decision and optionally promote a fictional person lead."""

    try:
        return resolve_individual_candidate(
            session=session,
            settings=settings,
            candidate_id=candidate_id,
            request=request,
        )
    except (IndividualCandidateNotFoundError, PersonNotFoundError) as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndividualSuppressedError as exc:
        session.rollback()
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except IndividualReviewConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/v1/individual-leads",
    response_model=IndividualLeadPage,
    tags=["individual-leads"],
)
def read_individual_leads(session: DbSession, settings: AppSettings) -> IndividualLeadPage:
    """List fictional person-subject leads independently of business leads."""

    return list_individual_leads(session=session, settings=settings)


@router.post(
    "/v1/people/{person_id}/suppress",
    response_model=PersonSuppressionView,
    tags=["individual-leads"],
)
def create_person_suppression(
    person_id: UUID,
    request: PersonSuppressionRequest,
    session: DbSession,
    settings: AppSettings,
) -> PersonSuppressionView:
    """Suppress one person and disqualify their individual lead."""

    try:
        return suppress_person(
            session=session,
            settings=settings,
            person_id=person_id,
            reason_category=request.reason_category,
        )
    except PersonNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/v1/companies/{company_id}/decision-maker-runs",
    response_model=DecisionMakerRunView,
    tags=["decision-makers"],
)
def create_decision_maker_run(
    company_id: UUID,
    request: DecisionMakerRunRequest,
    session: DbSession,
    settings: AppSettings,
) -> DecisionMakerRunView:
    """Research fictional decision-maker roles with a separate provider budget."""

    try:
        run = execute_decision_maker_discovery(
            session=session,
            settings=settings,
            registry=decision_maker_provider_registry,
            company_id=company_id,
            provider_key=request.provider_key,
            limit=request.limit,
            idempotency_key=request.idempotency_key,
        )
    except DecisionMakerProviderNotRegisteredError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DecisionMakerCollectionNotApprovedError as exc:
        session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except DecisionMakerDiscoveryError as exc:
        session.rollback()
        status_code = 404 if str(exc) == "Company not found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _decision_maker_view(session, run)


@router.get(
    "/v1/decision-maker-runs/{run_id}",
    response_model=DecisionMakerRunView,
    tags=["decision-makers"],
)
def read_decision_maker_run(
    run_id: UUID, session: DbSession, settings: AppSettings
) -> DecisionMakerRunView:
    run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.id == run_id,
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            DiscoveryRun.pipeline_kind == "business",
            DiscoveryRun.discovery_kind == "decision_maker",
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Decision-maker run not found")
    return _decision_maker_view(session, run)


@router.post(
    "/v1/decision-maker-candidates/{candidate_id}/promote",
    response_model=DecisionMakerRoleView,
    tags=["decision-makers"],
)
def promote_decision_maker(
    candidate_id: UUID, session: DbSession, settings: AppSettings
) -> DecisionMakerRoleView:
    """Promote one qualified fictional candidate into a durable company role."""

    try:
        return promote_decision_maker_candidate(
            session=session, settings=settings, candidate_id=candidate_id
        )
    except DecisionMakerCollectionNotApprovedError as exc:
        session.rollback()
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except DecisionMakerDiscoveryError as exc:
        session.rollback()
        status_code = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post(
    "/v1/leads/{lead_id}/enrichment-runs",
    response_model=EnrichmentRunView,
    tags=["enrichment"],
)
def create_enrichment_run(
    lead_id: UUID,
    request: EnrichmentRunRequest,
    session: DbSession,
    settings: AppSettings,
) -> EnrichmentRunView:
    """Execute one budgeted fictional enrichment waterfall step."""

    try:
        run = execute_enrichment(
            session=session,
            settings=settings,
            registry=enrichment_provider_registry,
            lead_id=lead_id,
            idempotency_key=request.idempotency_key,
        )
    except EnrichmentProviderNotRegisteredError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EnrichmentCollectionNotApprovedError as exc:
        session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except EnrichmentError as exc:
        session.rollback()
        status_code = 404 if str(exc) == "Lead not found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _enrichment_view(session, run)


@router.get(
    "/v1/enrichment-runs/{run_id}",
    response_model=EnrichmentRunView,
    tags=["enrichment"],
)
def read_enrichment_run(
    run_id: UUID, session: DbSession, settings: AppSettings
) -> EnrichmentRunView:
    run = session.scalar(
        select(EnrichmentRun).where(
            EnrichmentRun.id == run_id,
            EnrichmentRun.workspace_id == settings.default_workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Enrichment run not found")
    return _enrichment_view(session, run)


@router.post(
    "/v1/leads/{lead_id}/opportunity-analysis-runs",
    response_model=OpportunityAnalysisRunView,
    tags=["opportunities"],
)
def create_opportunity_analysis_run(
    lead_id: UUID,
    request: OpportunityAnalysisRunRequest,
    session: DbSession,
    settings: AppSettings,
) -> OpportunityAnalysisRunView:
    """Execute one budgeted, fictional, evidence-grounded opportunity analysis."""

    try:
        run = execute_opportunity_analysis(
            session=session,
            settings=settings,
            registry=opportunity_analysis_provider_registry,
            lead_id=lead_id,
            provider_key=request.provider_key,
            idempotency_key=request.idempotency_key,
        )
    except OpportunityAnalysisProviderNotRegisteredError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OpportunityAnalysisNotApprovedError as exc:
        session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except OpportunityAnalysisError as exc:
        session.rollback()
        status_code = 404 if str(exc) == "Lead not found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _opportunity_analysis_view(session, run)


@router.get(
    "/v1/opportunity-analysis-runs/{run_id}",
    response_model=OpportunityAnalysisRunView,
    tags=["opportunities"],
)
def read_opportunity_analysis_run(
    run_id: UUID, session: DbSession, settings: AppSettings
) -> OpportunityAnalysisRunView:
    run = session.scalar(
        select(OpportunityAnalysisRun).where(
            OpportunityAnalysisRun.id == run_id,
            OpportunityAnalysisRun.workspace_id == settings.default_workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Opportunity analysis run not found")
    return _opportunity_analysis_view(session, run)


@router.post(
    "/v1/opportunity-hypotheses/{hypothesis_id}/review",
    response_model=OpportunityHypothesisView,
    tags=["opportunities"],
)
def review_opportunity(
    hypothesis_id: UUID,
    request: OpportunityReviewRequest,
    session: DbSession,
    settings: AppSettings,
) -> OpportunityHypothesisView:
    """Record one final human decision for an unverified AI hypothesis."""

    try:
        hypothesis = review_opportunity_hypothesis(
            session=session,
            settings=settings,
            hypothesis_id=hypothesis_id,
            decision=request.decision,
            reason=request.reason,
        )
    except OpportunityAnalysisError as exc:
        session.rollback()
        status_code = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _opportunity_hypothesis_view(session, hypothesis)


@router.post(
    "/v1/entity-match-candidates",
    response_model=EntityMatchView,
    tags=["entity-resolution"],
)
def create_entity_match(
    request: EntityMatchRequest,
    session: DbSession,
    settings: AppSettings,
) -> EntityMatchView:
    """Create a canonical review suggestion without automatically merging."""

    try:
        candidate = create_match_candidate(
            session=session,
            settings=settings,
            entity_kind=request.entity_kind,
            left_id=request.left_id,
            right_id=request.right_id,
            exact_stable_identifier=request.exact_stable_identifier,
            name_similarity=request.name_similarity,
        )
    except EntityResolutionError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _entity_match_view(session, candidate)


@router.post(
    "/v1/entity-match-candidates/{candidate_id}/review",
    response_model=EntityMatchView,
    tags=["entity-resolution"],
)
def review_entity_match(
    candidate_id: UUID,
    request: EntityMatchReviewRequest,
    session: DbSession,
    settings: AppSettings,
) -> EntityMatchView:
    """Reject a suggestion or record an operator-approved logical merge."""

    try:
        candidate = review_match_candidate(
            session=session,
            settings=settings,
            candidate_id=candidate_id,
            action=request.action,
            survivor_id=request.survivor_id,
            reason=request.reason,
        )
    except EntityResolutionError as exc:
        session.rollback()
        status_code = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _entity_match_view(session, candidate)


@router.post(
    "/v1/entity-merge-events/{event_id}/unmerge",
    response_model=EntityMatchView,
    tags=["entity-resolution"],
)
def unmerge_entity(
    event_id: UUID,
    request: EntityUnmergeRequest,
    session: DbSession,
    settings: AppSettings,
) -> EntityMatchView:
    """Reverse one logical merge with an append-only recovery event."""

    try:
        reversal = unmerge_entity_event(
            session=session,
            settings=settings,
            merge_event_id=event_id,
            reason=request.reason,
        )
    except EntityResolutionError as exc:
        session.rollback()
        status_code = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if reversal.match_candidate_id is None:
        raise HTTPException(status_code=409, detail="Unmerge event has no match candidate")
    candidate = session.get(EntityMatchCandidate, reversal.match_candidate_id)
    if candidate is None:
        raise HTTPException(status_code=409, detail="Unmerge candidate disappeared")
    return _entity_match_view(session, candidate)


def _discovery_view(session: Session, run: DiscoveryRun) -> DiscoveryRunView:
    job = session.get(Job, run.job_id)
    if job is None:
        raise DiscoveryError("Discovery run job not found")
    attempt_count = session.scalar(
        select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == job.id)
    )
    candidates = session.scalars(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.discovery_run_id == run.id)
        .order_by(DiscoveryCandidate.created_at, DiscoveryCandidate.id)
    ).all()
    return DiscoveryRunView(
        id=run.id,
        provider_key=run.provider_key,
        status=run.status,
        next_cursor=run.next_cursor,
        discovered_count=run.discovered_count,
        duplicate_count=run.duplicate_count,
        rejected_count=run.rejected_count,
        error_code=run.error_code,
        error_message=run.error_message,
        attempt_count=int(attempt_count or 0),
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at if run.status == "queued" else None,
        candidates=[
            DiscoveryCandidateView(
                id=item.id,
                provider_record_id=item.provider_record_id,
                company_name=item.company_name,
                normalized_domain=item.normalized_domain,
                country_code=item.country_code,
                region=item.region,
                industry=item.industry,
                employee_count=item.employee_count,
                legal_form=item.legal_form,
                company_status=item.company_status,
                source_url=item.source_url,
                observed_at=item.observed_at,
                status=item.status,
                rejection_reason=item.rejection_reason,
            )
            for item in candidates
        ],
    )


def _enrichment_view(session: Session, run: EnrichmentRun) -> EnrichmentRunView:
    rows = session.execute(
        select(EvidenceClaim, SourceDocument)
        .join(SourceDocument, SourceDocument.id == EvidenceClaim.source_document_id)
        .where(SourceDocument.enrichment_run_id == run.id)
        .order_by(EvidenceClaim.claim_type, EvidenceClaim.created_at)
    ).all()
    return EnrichmentRunView(
        id=run.id,
        lead_id=run.lead_id,
        plan_id=run.plan_id,
        status=run.status,
        current_step_order=run.current_step_order,
        completed_fields=list(run.completed_fields_json),
        stop_reason=run.stop_reason,
        claims=[
            EnrichmentClaimView(
                id=claim.id,
                claim_type=claim.claim_type,
                value=claim.value_json,
                normalized_value=claim.normalized_value,
                classification=claim.classification,
                confidence=claim.confidence,
                verification_status=claim.verification_status,
                review_status=claim.review_status,
                valid_until=claim.valid_until,
                source_url=document.canonical_url,
            )
            for claim, document in rows
        ],
    )


def _opportunity_analysis_view(
    session: Session, run: OpportunityAnalysisRun
) -> OpportunityAnalysisRunView:
    prompt = session.get(AiPromptDefinition, run.prompt_definition_id)
    if prompt is None:
        raise OpportunityAnalysisError("Opportunity prompt disappeared")
    hypotheses = session.scalars(
        select(OpportunityHypothesis)
        .where(OpportunityHypothesis.analysis_run_id == run.id)
        .order_by(OpportunityHypothesis.created_at, OpportunityHypothesis.id)
    ).all()
    return OpportunityAnalysisRunView(
        id=run.id,
        lead_id=run.lead_id,
        provider_key=run.provider_key,
        status=run.status,
        prompt_key=prompt.prompt_key,
        prompt_version=prompt.version,
        output_schema_version=prompt.output_schema_version,
        taxonomy_version=prompt.taxonomy_version,
        model_name=run.model_name,
        model_version=run.model_version,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        injection_detected=run.injection_detected,
        excluded_claim_ids=[UUID(item) for item in run.excluded_claim_ids_json],
        missing_fields=list(run.missing_fields_json),
        contradictions=list(run.contradictions_json),
        error_code=run.error_code,
        error_message=run.error_message,
        hypotheses=[_opportunity_hypothesis_view(session, item) for item in hypotheses],
    )


def _opportunity_hypothesis_view(
    session: Session, hypothesis: OpportunityHypothesis
) -> OpportunityHypothesisView:
    claim_ids = session.scalars(
        select(OpportunityHypothesisEvidence.evidence_claim_id)
        .where(OpportunityHypothesisEvidence.hypothesis_id == hypothesis.id)
        .order_by(OpportunityHypothesisEvidence.evidence_claim_id)
    ).all()
    return OpportunityHypothesisView(
        id=hypothesis.id,
        category=hypothesis.category,
        title=hypothesis.title,
        summary=hypothesis.summary,
        confidence=hypothesis.confidence,
        review_status=hypothesis.review_status,
        citation_claim_ids=list(claim_ids),
        missing_fields=list(hypothesis.missing_fields_json),
        contradictions=list(hypothesis.contradictions_json),
    )


def _entity_match_view(session: Session, candidate: EntityMatchCandidate) -> EntityMatchView:
    left_id, right_id = candidate_subject_ids(candidate)
    events = session.scalars(
        select(EntityMergeEvent)
        .where(EntityMergeEvent.match_candidate_id == candidate.id)
        .order_by(EntityMergeEvent.occurred_at, EntityMergeEvent.id)
    ).all()
    return EntityMatchView(
        id=candidate.id,
        entity_kind=candidate.entity_kind,
        left_id=left_id,
        right_id=right_id,
        match_basis=candidate.match_basis,
        score=candidate.score,
        status=candidate.status,
        explanation=str(candidate.features_json["explanation"]),
        reviewed_at=candidate.reviewed_at,
        events=[_merge_event_view(event) for event in events],
    )


def _merge_event_view(event: EntityMergeEvent) -> EntityMergeEventView:
    if event.entity_kind == "company":
        survivor_id, merged_id = event.survivor_company_id, event.merged_company_id
    else:
        survivor_id, merged_id = event.survivor_person_id, event.merged_person_id
    if survivor_id is None or merged_id is None:
        raise EntityResolutionError("Merge event subjects are incomplete")
    return EntityMergeEventView(
        id=event.id,
        action=event.action,
        survivor_id=survivor_id,
        merged_id=merged_id,
        reverses_event_id=event.reverses_event_id,
        reason=event.reason,
        occurred_at=event.occurred_at.astimezone(UTC),
    )


def _decision_maker_view(session: Session, run: DiscoveryRun) -> DecisionMakerRunView:
    candidates = session.scalars(
        select(DecisionMakerCandidate)
        .where(DecisionMakerCandidate.discovery_run_id == run.id)
        .order_by(DecisionMakerCandidate.created_at, DecisionMakerCandidate.id)
    ).all()
    if not candidates:
        company_id = UUID(str(run.request_json["company_id"]))
    else:
        company_id = candidates[0].company_id
    return DecisionMakerRunView(
        id=run.id,
        company_id=company_id,
        provider_key=run.provider_key,
        status=run.status,
        discovered_count=run.discovered_count,
        duplicate_count=run.duplicate_count,
        rejected_count=run.rejected_count,
        error_code=run.error_code,
        error_message=run.error_message,
        candidates=[
            DecisionMakerCandidateView(
                id=item.id,
                company_id=item.company_id,
                display_name=item.display_name,
                professional_profile_url=item.professional_profile_url,
                title=item.title_original,
                seniority=item.seniority,
                department=item.department,
                is_current=item.is_current,
                role_score=item.role_score,
                matched_role=item.qualification_json.get("matched_role"),
                qualification_explanation=str(item.qualification_json["explanation"]),
                status=item.status,
                rejection_reason=item.rejection_reason,
                source_url=item.source_url,
                observed_at=item.observed_at,
                evidence_classification=str(item.provenance_json["classification"]),
            )
            for item in candidates
        ],
    )


def _individual_discovery_view(session: Session, run: DiscoveryRun) -> IndividualDiscoveryRunView:
    job = session.get(Job, run.job_id)
    if job is None:
        raise IndividualDiscoveryError("Individual discovery run job not found")
    attempt_count = session.scalar(
        select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == job.id)
    )
    candidates = session.scalars(
        select(IndividualDiscoveryCandidate)
        .where(IndividualDiscoveryCandidate.discovery_run_id == run.id)
        .order_by(IndividualDiscoveryCandidate.created_at, IndividualDiscoveryCandidate.id)
    ).all()
    return IndividualDiscoveryRunView(
        id=run.id,
        provider_key=run.provider_key,
        status=run.status,
        next_cursor=run.next_cursor,
        discovered_count=run.discovered_count,
        duplicate_count=run.duplicate_count,
        rejected_count=run.rejected_count,
        error_code=run.error_code,
        error_message=run.error_message,
        attempt_count=int(attempt_count or 0),
        max_attempts=job.max_attempts,
        candidates=[
            IndividualCandidateView(
                id=item.id,
                provider_record_id=item.provider_record_id,
                display_name=item.display_name,
                professional_profile_url=item.professional_profile_url,
                normalized_profile_url=item.normalized_profile_url,
                persona=item.persona,
                country_code=item.country_code,
                region=item.region,
                service_summary=item.service_summary,
                has_professional_presence=item.has_professional_presence,
                has_business_relevance=item.has_business_relevance,
                is_fictional=item.is_fictional,
                source_url=item.source_url,
                observed_at=item.observed_at,
                status=item.status,
                disposition=item.disposition,
                score=item.score,
                maximum_score=item.maximum_score,
                rejection_reason=item.rejection_reason,
                possible_match_person_id=item.possible_match_person_id,
                duplicate_person_id=item.duplicate_person_id,
                evidence_classification=str(item.provenance_json["classification"]),
            )
            for item in candidates
        ],
    )


def _execute_discovery_request(
    *,
    session: Session,
    settings: Settings,
    provider_key: str,
    query: DiscoveryQuery,
    idempotency_key: str,
) -> DiscoveryRunView:
    try:
        run = execute_discovery(
            session=session,
            settings=settings,
            registry=provider_registry,
            provider_key=provider_key,
            query=query,
            idempotency_key=idempotency_key,
        )
    except (ProviderDisabledError, ProviderNotRegisteredError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        session.rollback()
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except DiscoveryError as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _discovery_view(session, run)
