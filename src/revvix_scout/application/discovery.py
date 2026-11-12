"""Synchronous, bounded M3 discovery orchestration with pre-call budget reservation."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from revvix_scout.config import Settings
from revvix_scout.db.models import (
    BudgetPolicy,
    BudgetReservation,
    CompanyDomain,
    DiscoveryCandidate,
    DiscoveryRun,
    IcpVersion,
    Job,
    JobAttempt,
    ProviderConfig,
    ProviderUsageEvent,
)
from revvix_scout.domain.normalization import normalize_domain
from revvix_scout.providers.contracts import DiscoveryQuery, ProviderRegistry


class DiscoveryError(RuntimeError):
    pass


class ProviderDisabledError(DiscoveryError):
    pass


class BudgetExceededError(DiscoveryError):
    pass


def execute_discovery(
    *,
    session: Session,
    settings: Settings,
    registry: ProviderRegistry,
    provider_key: str,
    query: DiscoveryQuery,
    idempotency_key: str,
) -> DiscoveryRun:
    """Execute one page; repeated idempotency keys return the original run."""

    existing_job = session.scalar(
        select(Job).where(
            Job.workspace_id == settings.default_workspace_id,
            Job.job_type == "business_discovery",
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        run = session.scalar(select(DiscoveryRun).where(DiscoveryRun.job_id == existing_job.id))
        if run is None:
            raise DiscoveryError("Existing discovery job has no run")
        return run

    provider = registry.get(provider_key)
    icp_version = session.get(IcpVersion, settings.default_icp_version_id)
    if icp_version is None:
        raise DiscoveryError("Configured ICP version does not exist")
    config = session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == settings.default_workspace_id,
            ProviderConfig.provider_key == provider_key,
        )
    )
    if config is None or not config.enabled:
        raise ProviderDisabledError(f"Provider is disabled: {provider_key}")
    if provider.is_live and not config.live_calls_allowed:
        raise ProviderDisabledError(f"Live calls are not approved: {provider_key}")

    now = datetime.now(UTC)
    request_json = {
        "search_text": query.search_text,
        "country_code": query.country_code,
        "region": query.region,
        "limit": query.limit,
        "cursor": query.cursor,
    }
    fingerprint = _hash_json({"provider_key": provider_key, **request_json})
    existing_run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            DiscoveryRun.request_fingerprint == fingerprint,
        )
    )
    if existing_run is not None:
        return existing_run
    job = Job(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        job_type="business_discovery",
        idempotency_key=idempotency_key,
        status="running",
        input_json=request_json,
        started_at=now,
    )
    session.add(job)
    session.flush()
    run = DiscoveryRun(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        job_id=job.id,
        icp_version_id=settings.default_icp_version_id,
        provider_key=provider_key,
        request_fingerprint=fingerprint,
        request_json=request_json,
        status="running",
        started_at=now,
    )
    attempt = JobAttempt(
        id=uuid4(), job_id=job.id, attempt_number=1, status="running", started_at=now
    )
    session.add_all((run, attempt))
    session.flush()

    estimated_units = provider.estimate_units(query)
    reservation = _reserve_budget(
        session=session,
        settings=settings,
        run=run,
        provider_key=provider_key,
        estimated_units=estimated_units,
        now=now,
    )
    try:
        page = provider.discover(query)
        for candidate in page.candidates:
            normalized_domain = normalize_domain(candidate.domain)
            duplicate_company_id = None
            if normalized_domain:
                duplicate_company_id = session.scalar(
                    select(CompanyDomain.company_id).where(
                        CompanyDomain.workspace_id == settings.default_workspace_id,
                        CompanyDomain.normalized_domain == normalized_domain,
                    )
                )
            status, reason = _thin_eligibility(
                company_status=candidate.company_status,
                duplicate_company_id=duplicate_company_id,
                industry=candidate.industry,
                country_code=candidate.country_code,
                region=candidate.region,
                employee_count=candidate.employee_count,
                legal_form=candidate.legal_form,
                definition=icp_version.definition_json,
            )
            session.add(
                DiscoveryCandidate(
                    workspace_id=settings.default_workspace_id,
                    discovery_run_id=run.id,
                    provider_key=provider_key,
                    provider_record_id=candidate.provider_record_id,
                    candidate_fingerprint=_hash_json(
                        {"provider": provider_key, "record": candidate.provider_record_id}
                    ),
                    company_name=candidate.company_name,
                    normalized_domain=normalized_domain,
                    country_code=candidate.country_code,
                    region=candidate.region,
                    industry=candidate.industry,
                    employee_count=candidate.employee_count,
                    legal_form=candidate.legal_form,
                    company_status=candidate.company_status,
                    source_url=candidate.source_url,
                    observed_at=candidate.observed_at,
                    status=status,
                    rejection_reason=reason,
                    duplicate_company_id=duplicate_company_id,
                    provenance_json={
                        "classification": "provider_asserted",
                        "adapter_kind": config.adapter_kind,
                        "fixture": not provider.is_live,
                    },
                )
            )
            run.discovered_count += 1
            if status == "duplicate":
                run.duplicate_count += 1
            elif status == "rejected":
                run.rejected_count += 1
        run.next_cursor = page.next_cursor
        run.status = "succeeded"
        run.completed_at = datetime.now(UTC)
        job.status = "succeeded"
        job.completed_at = run.completed_at
        attempt.status = "succeeded"
        attempt.completed_at = run.completed_at
        _settle(
            session=session,
            settings=settings,
            run=run,
            reservation=reservation,
            actual_units=page.actual_units,
            outcome="succeeded",
            now=run.completed_at,
        )
    except Exception as exc:
        failed_at = datetime.now(UTC)
        run.status = job.status = "failed"
        run.error_code = job.error_code = "provider_execution_failed"
        run.error_message = job.error_message = str(exc)[:500]
        run.completed_at = job.completed_at = failed_at
        attempt.status = "failed"
        attempt.error_category = "provider"
        attempt.error_message = str(exc)[:500]
        attempt.completed_at = failed_at
        _settle(
            session=session,
            settings=settings,
            run=run,
            reservation=reservation,
            actual_units=estimated_units,
            outcome="failed",
            now=failed_at,
        )
    session.commit()
    return run


def _reserve_budget(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    provider_key: str,
    estimated_units: int,
    now: datetime,
) -> BudgetReservation:
    policy = session.scalar(
        select(BudgetPolicy)
        .where(
            BudgetPolicy.workspace_id == settings.default_workspace_id,
            BudgetPolicy.provider_key == provider_key,
            BudgetPolicy.operation == "business_discovery",
            BudgetPolicy.window_kind == "run",
            BudgetPolicy.enabled.is_(True),
        )
        .with_for_update()
    )
    if policy is None:
        raise BudgetExceededError("No enabled budget policy; default deny")
    already_reserved = session.scalar(
        select(func.coalesce(func.sum(BudgetReservation.reserved_units), 0)).where(
            BudgetReservation.discovery_run_id == run.id,
            BudgetReservation.status == "active",
        )
    )
    if int(already_reserved or 0) + estimated_units > policy.hard_limit_units:
        raise BudgetExceededError("Provider call would exceed the hard run budget")
    reservation = BudgetReservation(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        discovery_run_id=run.id,
        provider_key=provider_key,
        operation="business_discovery",
        reserved_units=estimated_units,
        status="active",
        reserved_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    session.add(reservation)
    session.flush()
    return reservation


def _settle(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    reservation: BudgetReservation,
    actual_units: int,
    outcome: str,
    now: datetime,
) -> None:
    reservation.status = "settled"
    reservation.settled_units = actual_units
    reservation.settled_at = now
    session.add(
        ProviderUsageEvent(
            workspace_id=settings.default_workspace_id,
            discovery_run_id=run.id,
            reservation_id=reservation.id,
            provider_key=run.provider_key,
            operation="business_discovery",
            outcome=outcome,
            estimated_units=reservation.reserved_units,
            actual_units=actual_units,
            unit_type="request",
            billable=False,
            occurred_at=now,
        )
    )


def _thin_eligibility(
    *,
    company_status: str | None,
    duplicate_company_id: UUID | None,
    industry: str | None,
    country_code: str | None,
    region: str | None,
    employee_count: int | None,
    legal_form: str | None,
    definition: dict[str, Any],
) -> tuple[str, str | None]:
    if duplicate_company_id is not None:
        return "duplicate", "existing_domain"
    allowed_statuses = set(definition["allowed_company_statuses"])
    if company_status not in allowed_statuses:
        return "rejected", "company_status_not_allowed"
    if industry not in set(definition["target_industries"]):
        return "rejected", "industry_not_targeted"
    if country_code not in set(definition["target_countries"]):
        return "rejected", "country_not_targeted"
    if region not in set(definition["target_regions"]):
        return "rejected", "region_not_targeted"
    if legal_form not in set(definition["preferred_legal_forms"]):
        return "needs_review", "legal_form_not_preferred"
    employee_range = definition["employee_range"]
    assert isinstance(employee_range, dict)
    if employee_count is None:
        return "needs_review", "employee_count_missing"
    if (
        not int(employee_range["preferred_min"])
        <= employee_count
        <= int(employee_range["preferred_max"])
    ):
        return "needs_review", "employee_count_outside_preferred_range"
    return "new", None


def _hash_json(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()
