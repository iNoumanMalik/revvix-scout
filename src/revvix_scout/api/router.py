"""Versioned FastAPI routes for the M2A slice."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import (
    DiscoveryCandidateView,
    DiscoveryRunRequest,
    DiscoveryRunView,
    ImportSummary,
    LeadDetail,
    LeadPage,
)
from revvix_scout.application.discovery import (
    BudgetExceededError,
    DiscoveryError,
    ProviderDisabledError,
    execute_discovery,
)
from revvix_scout.application.imports import ImportContractError, import_business_csv
from revvix_scout.application.leads import (
    InvalidCursorError,
    LeadFilters,
    LeadNotFoundError,
    export_leads_csv,
    get_lead_detail,
    list_leads,
)
from revvix_scout.config import Settings, get_settings
from revvix_scout.db.models import DiscoveryCandidate, DiscoveryRun
from revvix_scout.db.session import get_db_session
from revvix_scout.providers.contracts import (
    DiscoveryQuery,
    ProviderNotRegisteredError,
    ProviderRegistry,
)
from revvix_scout.providers.fixture import FictionalAccountingProvider

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
provider_registry = ProviderRegistry((FictionalAccountingProvider(),))


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


@router.get("/v1/discovery-runs/{run_id}", response_model=DiscoveryRunView, tags=["discovery"])
def read_discovery_run(run_id: UUID, session: DbSession, settings: AppSettings) -> DiscoveryRunView:
    run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.id == run_id,
            DiscoveryRun.workspace_id == settings.default_workspace_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return _discovery_view(session, run)


def _discovery_view(session: Session, run: DiscoveryRun) -> DiscoveryRunView:
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
