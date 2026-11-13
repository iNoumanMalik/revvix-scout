"""Resumable M3 discovery orchestration with short claims and pre-call budgets."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select
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
from revvix_scout.providers.contracts import (
    DiscoveredBusiness,
    DiscoveryPage,
    DiscoveryQuery,
    ProviderExecutionError,
    ProviderRegistry,
)


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
    worker_id: str = "inline-api",
) -> DiscoveryRun:
    """Idempotently enqueue a run and process its first available attempt."""

    run = enqueue_discovery(
        session=session,
        settings=settings,
        registry=registry,
        provider_key=provider_key,
        query=query,
        idempotency_key=idempotency_key,
    )
    if run.status != "queued":
        return run
    return process_discovery_run(
        session=session,
        settings=settings,
        registry=registry,
        run_id=run.id,
        worker_id=worker_id,
    )


def enqueue_discovery(
    *,
    session: Session,
    settings: Settings,
    registry: ProviderRegistry,
    provider_key: str,
    query: DiscoveryQuery,
    idempotency_key: str,
) -> DiscoveryRun:
    """Persist a validated queued run without executing provider behavior."""

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
    _require_provider_enabled(
        session=session,
        settings=settings,
        provider_key=provider_key,
        is_live=provider.is_live,
    )
    if session.get(IcpVersion, settings.default_icp_version_id) is None:
        raise DiscoveryError("Configured ICP version does not exist")

    request_json = _query_to_json(query)
    fingerprint = _hash_json({"provider_key": provider_key, **request_json})
    existing_run = session.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            DiscoveryRun.request_fingerprint == fingerprint,
        )
    )
    if existing_run is not None:
        return existing_run

    now = datetime.now(UTC)
    job = Job(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        job_type="business_discovery",
        idempotency_key=idempotency_key,
        status="queued",
        input_json=request_json,
        max_attempts=3,
        next_attempt_at=now,
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
        status="queued",
    )
    session.add(run)
    session.commit()
    return run


def process_discovery_run(
    *,
    session: Session,
    settings: Settings,
    registry: ProviderRegistry,
    run_id: UUID,
    worker_id: str,
    now: datetime | None = None,
) -> DiscoveryRun:
    """Claim one due attempt, call outside the transaction, and settle durably."""

    claimed_at = now or datetime.now(UTC)
    claim = session.execute(
        select(DiscoveryRun, Job)
        .join(Job, Job.id == DiscoveryRun.job_id)
        .where(
            DiscoveryRun.id == run_id,
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            or_(
                and_(Job.status == "queued", Job.next_attempt_at <= claimed_at),
                and_(Job.status == "running", Job.lease_expires_at < claimed_at),
            ),
        )
        .with_for_update(of=Job, skip_locked=True)
    ).one_or_none()
    if claim is None:
        existing = session.get(DiscoveryRun, run_id)
        if existing is None or existing.workspace_id != settings.default_workspace_id:
            raise DiscoveryError("Discovery run not found")
        session.rollback()
        return existing

    run, job = cast(tuple[DiscoveryRun, Job], claim)
    provider = registry.get(run.provider_key)
    config = _require_provider_enabled(
        session=session,
        settings=settings,
        provider_key=run.provider_key,
        is_live=provider.is_live,
    )
    icp_version = session.get(IcpVersion, run.icp_version_id)
    if icp_version is None:
        raise DiscoveryError("Discovery run ICP version does not exist")
    definition = dict(icp_version.definition_json)
    query = _query_from_json(run.request_json)

    _recover_expired_attempts(session=session, job=job, run=run, now=claimed_at)
    attempt_number = (
        int(
            session.scalar(
                select(func.coalesce(func.max(JobAttempt.attempt_number), 0)).where(
                    JobAttempt.job_id == job.id
                )
            )
            or 0
        )
        + 1
    )
    if attempt_number > job.max_attempts:
        _mark_exhausted(job=job, run=run, now=claimed_at)
        session.commit()
        return run

    estimated_units = provider.estimate_units(query)
    reservation = _reserve_budget(
        session=session,
        settings=settings,
        run=run,
        provider_key=run.provider_key,
        estimated_units=estimated_units,
        now=claimed_at,
    )
    attempt = JobAttempt(
        id=uuid4(),
        job_id=job.id,
        attempt_number=attempt_number,
        status="running",
        retryable=False,
        started_at=claimed_at,
    )
    session.add(attempt)
    job.status = run.status = "running"
    job.worker_id = worker_id[:120]
    job.lease_expires_at = claimed_at + timedelta(minutes=5)
    job.started_at = job.started_at or claimed_at
    run.started_at = run.started_at or claimed_at
    job.error_code = job.error_message = None
    run.error_code = run.error_message = None
    adapter_kind = config.adapter_kind
    session.commit()

    page: DiscoveryPage | None = None
    provider_error: ProviderExecutionError | None = None
    processing_error: Exception | None = None
    try:
        page = provider.discover(query)
    except ProviderExecutionError as exc:
        provider_error = exc
    except Exception as exc:  # adapter bugs and malformed provider values fail permanently
        processing_error = exc

    finished_at = now or datetime.now(UTC)
    reloaded_run = session.get(DiscoveryRun, run_id)
    reloaded_job = session.get(
        Job, reloaded_run.job_id if reloaded_run is not None else UUID(int=0)
    )
    reloaded_attempt = session.get(JobAttempt, attempt.id)
    reloaded_reservation = session.get(BudgetReservation, reservation.id)
    if (
        reloaded_run is None
        or reloaded_job is None
        or reloaded_attempt is None
        or reloaded_reservation is None
    ):
        raise DiscoveryError("Claimed discovery state disappeared")
    run = reloaded_run
    job = reloaded_job
    attempt = reloaded_attempt
    reservation = reloaded_reservation

    if page is not None:
        try:
            # A malformed page must not leave a prefix of its candidates behind.
            with session.begin_nested():
                _persist_candidates(
                    session=session,
                    settings=settings,
                    run=run,
                    page=page,
                    definition=definition,
                    adapter_kind=adapter_kind,
                    is_fixture=adapter_kind == "fixture",
                )
                session.flush()
        except Exception as exc:
            processing_error = exc

    if page is not None and processing_error is None:
        _complete_success(
            session=session,
            settings=settings,
            run=run,
            job=job,
            attempt=attempt,
            reservation=reservation,
            page=page,
            now=finished_at,
        )
    else:
        _complete_failure(
            session=session,
            settings=settings,
            run=run,
            job=job,
            attempt=attempt,
            reservation=reservation,
            provider_error=provider_error,
            processing_error=processing_error,
            actual_units=page.actual_units if page is not None else 0,
            now=finished_at,
        )
    session.commit()
    return run


def process_next_discovery_run(
    *,
    session: Session,
    settings: Settings,
    registry: ProviderRegistry,
    worker_id: str,
    now: datetime | None = None,
) -> DiscoveryRun | None:
    """Claim and process the oldest due run, or return ``None`` when idle."""

    claimed_at = now or datetime.now(UTC)
    due_at = case(
        (Job.status == "running", Job.lease_expires_at),
        else_=Job.next_attempt_at,
    )
    run_id = session.scalar(
        select(DiscoveryRun.id)
        .join(Job, Job.id == DiscoveryRun.job_id)
        .where(
            DiscoveryRun.workspace_id == settings.default_workspace_id,
            or_(
                and_(Job.status == "queued", Job.next_attempt_at <= claimed_at),
                and_(Job.status == "running", Job.lease_expires_at < claimed_at),
            ),
        )
        .order_by(due_at, Job.created_at, Job.id)
        .limit(1)
        .with_for_update(of=Job, skip_locked=True)
    )
    if run_id is None:
        session.rollback()
        return None
    return process_discovery_run(
        session=session,
        settings=settings,
        registry=registry,
        run_id=run_id,
        worker_id=worker_id,
        now=claimed_at,
    )


def _require_provider_enabled(
    *, session: Session, settings: Settings, provider_key: str, is_live: bool
) -> ProviderConfig:
    config = session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == settings.default_workspace_id,
            ProviderConfig.provider_key == provider_key,
        )
    )
    if config is None or not config.enabled:
        raise ProviderDisabledError(f"Provider is disabled: {provider_key}")
    if is_live and not config.live_calls_allowed:
        raise ProviderDisabledError(f"Live calls are not approved: {provider_key}")
    return config


def _recover_expired_attempts(
    *, session: Session, job: Job, run: DiscoveryRun, now: datetime
) -> None:
    if job.status != "running" or job.lease_expires_at is None or job.lease_expires_at >= now:
        return
    attempts = session.scalars(
        select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.status == "running")
    ).all()
    for prior_attempt in attempts:
        prior_attempt.status = "failed"
        prior_attempt.retryable = True
        prior_attempt.error_category = "lease_expired"
        prior_attempt.error_message = "Worker lease expired before attempt settlement."
        prior_attempt.completed_at = now
    reservations = session.scalars(
        select(BudgetReservation).where(
            BudgetReservation.discovery_run_id == run.id,
            BudgetReservation.status == "active",
        )
    ).all()
    for prior_reservation in reservations:
        prior_reservation.status = "released"
        prior_reservation.settled_units = 0
        prior_reservation.settled_at = now


def _mark_exhausted(*, job: Job, run: DiscoveryRun, now: datetime) -> None:
    job.status = run.status = "failed"
    job.error_code = run.error_code = "attempts_exhausted"
    job.error_message = run.error_message = "Maximum discovery attempts exhausted."
    job.completed_at = run.completed_at = now
    job.worker_id = None
    job.lease_expires_at = None


def _persist_candidates(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    page: DiscoveryPage,
    definition: dict[str, Any],
    adapter_kind: str,
    is_fixture: bool,
) -> None:
    for candidate in page.candidates:
        existing = session.scalar(
            select(DiscoveryCandidate.id).where(
                DiscoveryCandidate.discovery_run_id == run.id,
                DiscoveryCandidate.provider_key == run.provider_key,
                DiscoveryCandidate.provider_record_id == candidate.provider_record_id,
            )
        )
        if existing is not None:
            continue
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
            definition=definition,
        )
        session.add(
            DiscoveryCandidate(
                workspace_id=settings.default_workspace_id,
                discovery_run_id=run.id,
                provider_key=run.provider_key,
                provider_record_id=candidate.provider_record_id,
                candidate_fingerprint=_hash_json(
                    {"provider": run.provider_key, "record": candidate.provider_record_id}
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
                    "classification": (
                        "operator_supplied"
                        if adapter_kind in {"manual", "csv"}
                        else "provider_asserted"
                    ),
                    "adapter_kind": adapter_kind,
                    "fixture": is_fixture,
                },
            )
        )
        run.discovered_count += 1
        if status == "duplicate":
            run.duplicate_count += 1
        elif status == "rejected":
            run.rejected_count += 1
    run.next_cursor = page.next_cursor


def _complete_success(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    job: Job,
    attempt: JobAttempt,
    reservation: BudgetReservation,
    page: DiscoveryPage,
    now: datetime,
) -> None:
    run.status = job.status = "succeeded"
    run.completed_at = job.completed_at = now
    job.worker_id = None
    job.lease_expires_at = None
    attempt.status = "succeeded"
    attempt.completed_at = now
    _settle(
        session=session,
        settings=settings,
        run=run,
        reservation=reservation,
        actual_units=page.actual_units,
        outcome="succeeded",
        now=now,
    )


def _complete_failure(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    job: Job,
    attempt: JobAttempt,
    reservation: BudgetReservation,
    provider_error: ProviderExecutionError | None,
    processing_error: Exception | None,
    actual_units: int,
    now: datetime,
) -> None:
    error = provider_error or processing_error or DiscoveryError("Unknown discovery failure")
    retryable = provider_error.retryable if provider_error is not None else False
    category = provider_error.category if provider_error is not None else "processing"
    attempt.status = "failed"
    attempt.retryable = retryable
    attempt.error_category = category
    attempt.error_message = str(error)[:500]
    attempt.completed_at = now
    job.worker_id = None
    job.lease_expires_at = None
    job.error_code = run.error_code = category
    job.error_message = run.error_message = str(error)[:500]
    _settle(
        session=session,
        settings=settings,
        run=run,
        reservation=reservation,
        actual_units=provider_error.actual_units if provider_error is not None else actual_units,
        outcome=(
            "failed"
            if (provider_error.actual_units if provider_error is not None else actual_units) == 0
            else "partial"
        ),
        now=now,
    )
    if retryable and attempt.attempt_number < job.max_attempts:
        job.status = run.status = "queued"
        job.next_attempt_at = now + timedelta(seconds=2 ** (attempt.attempt_number - 1))
        job.completed_at = run.completed_at = None
    else:
        job.status = run.status = "failed"
        job.completed_at = run.completed_at = now
        if retryable:
            job.error_code = run.error_code = "attempts_exhausted"
            job.error_message = run.error_message = (
                f"Maximum discovery attempts exhausted; last category: {category}."
            )


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
    active_units = session.scalar(
        select(func.coalesce(func.sum(BudgetReservation.reserved_units), 0)).where(
            BudgetReservation.discovery_run_id == run.id,
            BudgetReservation.status == "active",
        )
    )
    settled_units = session.scalar(
        select(func.coalesce(func.sum(ProviderUsageEvent.actual_units), 0)).where(
            ProviderUsageEvent.discovery_run_id == run.id
        )
    )
    if int(active_units or 0) + int(settled_units or 0) + estimated_units > policy.hard_limit_units:
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
        expires_at=now + timedelta(minutes=5),
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


def _query_to_json(query: DiscoveryQuery) -> dict[str, Any]:
    return {
        "search_text": query.search_text,
        "country_code": query.country_code,
        "region": query.region,
        "limit": query.limit,
        "cursor": query.cursor,
        "records": [
            {
                "provider_record_id": item.provider_record_id,
                "company_name": item.company_name,
                "domain": item.domain,
                "country_code": item.country_code,
                "region": item.region,
                "industry": item.industry,
                "employee_count": item.employee_count,
                "legal_form": item.legal_form,
                "company_status": item.company_status,
                "source_url": item.source_url,
                "observed_at": item.observed_at.isoformat(),
            }
            for item in query.seed_records
        ],
    }


def _query_from_json(value: dict[str, Any]) -> DiscoveryQuery:
    records = tuple(
        DiscoveredBusiness(
            provider_record_id=item["provider_record_id"],
            company_name=item["company_name"],
            domain=item.get("domain"),
            country_code=item.get("country_code"),
            region=item.get("region"),
            industry=item.get("industry"),
            employee_count=item.get("employee_count"),
            legal_form=item.get("legal_form"),
            company_status=item.get("company_status"),
            source_url=item["source_url"],
            observed_at=datetime.fromisoformat(item["observed_at"]),
        )
        for item in value.get("records", [])
    )
    return DiscoveryQuery(
        search_text=value["search_text"],
        country_code=value["country_code"],
        region=value["region"],
        limit=int(value["limit"]),
        cursor=value.get("cursor"),
        seed_records=records,
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
    if company_status not in set(definition["allowed_company_statuses"]):
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
    if not (
        int(employee_range["preferred_min"])
        <= employee_count
        <= int(employee_range["preferred_max"])
    ):
        return "needs_review", "employee_count_outside_preferred_range"
    return "new", None


def _hash_json(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()
