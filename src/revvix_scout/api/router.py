"""Versioned FastAPI routes for provider-free business and individual slices."""

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
from revvix_scout.application.usage import BudgetExceededError
from revvix_scout.config import Settings, get_settings
from revvix_scout.db.models import (
    DecisionMakerCandidate,
    DiscoveryCandidate,
    DiscoveryRun,
    IndividualDiscoveryCandidate,
    Job,
    JobAttempt,
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
from revvix_scout.providers.individual_contracts import (
    IndividualDiscoveryQuery,
    IndividualProviderNotRegisteredError,
)
from revvix_scout.providers.registry import (
    create_decision_maker_provider_registry,
    create_individual_provider_registry,
    create_provider_registry,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
provider_registry = create_provider_registry()
individual_provider_registry = create_individual_provider_registry()
decision_maker_provider_registry = create_decision_maker_provider_registry()


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
