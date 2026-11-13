"""Fictional-only M4 individual discovery orchestration."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from revvix_scout.application.usage import reserve_provider_budget, settle_provider_usage
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    BudgetReservation,
    DiscoveryRun,
    IcpVersion,
    IndividualDiscoveryCandidate,
    Job,
    JobAttempt,
    Person,
    PersonProfile,
    ProviderConfig,
    Suppression,
)
from revvix_scout.domain.individuals import (
    IndividualScoreInput,
    individual_candidate_fingerprint,
    normalize_person_name,
    normalize_profile_url,
    profile_suppression_hash,
    score_individual,
)
from revvix_scout.providers.contracts import ProviderExecutionError
from revvix_scout.providers.individual_contracts import (
    IndividualDiscoveryPage,
    IndividualDiscoveryQuery,
    IndividualProviderRegistry,
)


class IndividualDiscoveryError(RuntimeError):
    pass


class IndividualCollectionNotApprovedError(IndividualDiscoveryError):
    pass


def execute_individual_discovery(
    *,
    session: Session,
    settings: Settings,
    registry: IndividualProviderRegistry,
    provider_key: str,
    query: IndividualDiscoveryQuery,
    idempotency_key: str,
) -> DiscoveryRun:
    """Execute one fictional page while live personal-data collection is disabled."""

    existing_job = session.scalar(
        select(Job).where(
            Job.workspace_id == settings.default_workspace_id,
            Job.job_type == "individual_discovery",
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        existing = session.scalar(
            select(DiscoveryRun).where(
                DiscoveryRun.job_id == existing_job.id,
                DiscoveryRun.pipeline_kind == "individual",
            )
        )
        if existing is None:
            raise IndividualDiscoveryError("Existing individual job has no run")
        return existing

    provider = registry.get(provider_key)
    config = session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == settings.default_workspace_id,
            ProviderConfig.provider_key == provider_key,
        )
    )
    if config is None or not config.enabled:
        raise IndividualDiscoveryError(f"Individual provider is disabled: {provider_key}")
    if provider.is_live or config.live_calls_allowed:
        raise IndividualCollectionNotApprovedError("Live individual collection is not approved")
    if not bool(config.config_json.get("fictional_data_only")):
        raise IndividualCollectionNotApprovedError(
            "Individual provider must be configured as fictional-data-only"
        )

    icp_version = session.get(IcpVersion, settings.individual_icp_version_id)
    if icp_version is None:
        raise IndividualDiscoveryError("Configured individual ICP version does not exist")
    definition = dict(icp_version.definition_json)
    if not bool(definition.get("fictional_data_only")) or bool(
        definition.get("collection_enabled")
    ):
        raise IndividualCollectionNotApprovedError(
            "Individual ICP must remain fictional-only with collection disabled"
        )

    request_json = _query_to_json(query)
    fingerprint = _hash_json(
        {"pipeline_kind": "individual", "provider_key": provider_key, **request_json}
    )
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
        job_type="individual_discovery",
        idempotency_key=idempotency_key,
        status="queued",
        input_json=request_json,
        max_attempts=1,
        next_attempt_at=now,
    )
    session.add(job)
    session.flush()
    run = DiscoveryRun(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        job_id=job.id,
        icp_version_id=icp_version.id,
        provider_key=provider_key,
        pipeline_kind="individual",
        request_fingerprint=fingerprint,
        request_json=request_json,
        status="queued",
    )
    session.add(run)
    session.commit()

    reservation = reserve_provider_budget(
        session=session,
        settings=settings,
        run=run,
        provider_key=provider_key,
        operation="individual_discovery",
        estimated_units=provider.estimate_units(query),
        now=now,
    )
    attempt = JobAttempt(
        id=uuid4(),
        job_id=job.id,
        attempt_number=1,
        status="running",
        retryable=False,
        started_at=now,
    )
    session.add(attempt)
    run.status = job.status = "running"
    run.started_at = job.started_at = now
    job.worker_id = "inline-individual-api"
    session.commit()

    page: IndividualDiscoveryPage | None = None
    failure: Exception | None = None
    actual_units = 0
    try:
        page = provider.discover(query)
        actual_units = page.actual_units
    except Exception as exc:  # provider boundary is untrusted even for fixtures
        failure = exc

    finished_at = datetime.now(UTC)
    loaded_run = session.get(DiscoveryRun, run.id)
    loaded_job = session.get(Job, job.id)
    loaded_attempt = session.get(JobAttempt, attempt.id)
    loaded_reservation = session.get(BudgetReservation, reservation.id)
    if (
        loaded_run is None
        or loaded_job is None
        or loaded_attempt is None
        or loaded_reservation is None
    ):
        raise IndividualDiscoveryError("Claimed individual discovery state disappeared")
    run = loaded_run
    job = loaded_job
    attempt = loaded_attempt
    reservation = loaded_reservation

    if page is not None:
        try:
            with session.begin_nested():
                _persist_candidates(
                    session=session,
                    settings=settings,
                    run=run,
                    page=page,
                    definition=definition,
                )
                session.flush()
        except Exception as exc:
            failure = exc

    if page is not None and failure is None:
        run.status = job.status = attempt.status = "succeeded"
        run.completed_at = job.completed_at = attempt.completed_at = finished_at
        job.worker_id = None
        settle_provider_usage(
            session=session,
            settings=settings,
            run=run,
            reservation=reservation,
            operation="individual_discovery",
            actual_units=actual_units,
            outcome="succeeded",
            now=finished_at,
        )
    else:
        category = failure.category if isinstance(failure, ProviderExecutionError) else "processing"
        charged_units = failure.actual_units if isinstance(failure, ProviderExecutionError) else 0
        run.status = job.status = attempt.status = "failed"
        run.completed_at = job.completed_at = attempt.completed_at = finished_at
        run.error_code = job.error_code = attempt.error_category = category
        safe_message = str(failure or "Unknown individual discovery failure")[:500]
        run.error_message = job.error_message = attempt.error_message = safe_message
        job.worker_id = None
        settle_provider_usage(
            session=session,
            settings=settings,
            run=run,
            reservation=reservation,
            operation="individual_discovery",
            actual_units=charged_units,
            outcome="partial" if charged_units else "failed",
            now=finished_at,
        )
    session.commit()
    return run


def _persist_candidates(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    page: IndividualDiscoveryPage,
    definition: dict[str, Any],
) -> None:
    for candidate in page.candidates:
        if not candidate.is_fictional:
            raise IndividualCollectionNotApprovedError(
                "Provider returned non-fictional personal data while collection is disabled"
            )
        provider_record_id = candidate.provider_record_id.strip()
        display_name = candidate.display_name.strip()
        if not provider_record_id or len(provider_record_id) > 160:
            raise IndividualDiscoveryError("Provider record ID is empty or too long")
        if not display_name or len(display_name) > 240:
            raise IndividualDiscoveryError("Individual display name is empty or too long")
        normalized_url = _require_fictional_url(
            candidate.professional_profile_url, field_name="professional profile URL"
        )
        _require_fictional_url(candidate.source_url, field_name="source URL")
        if len(candidate.professional_profile_url) > 1000 or len(candidate.source_url) > 2000:
            raise IndividualDiscoveryError("Individual source URL is too long")
        if candidate.service_summary is not None and len(candidate.service_summary) > 2000:
            raise IndividualDiscoveryError("Individual service summary is too long")
        if candidate.persona is not None and len(candidate.persona) > 80:
            raise IndividualDiscoveryError("Individual persona is too long")
        if candidate.region is not None and len(candidate.region) > 120:
            raise IndividualDiscoveryError("Individual region is too long")
        if candidate.observed_at.utcoffset() is None:
            raise IndividualDiscoveryError("Individual observation time must include a timezone")
        observed_at = candidate.observed_at.astimezone(UTC)
        country_code = candidate.country_code.upper() if candidate.country_code else None
        if country_code is not None and len(country_code) != 2:
            raise IndividualDiscoveryError("Individual country code must contain two characters")
        normalized_name = normalize_person_name(display_name)
        suppression_hash = profile_suppression_hash(normalized_url)
        evaluated_at = datetime.now(UTC)
        profile_is_suppressed = (
            session.scalar(
                select(Suppression.id).where(
                    Suppression.workspace_id == settings.default_workspace_id,
                    Suppression.scope == "profile",
                    Suppression.normalized_value_hash == suppression_hash,
                    Suppression.revoked_at.is_(None),
                    Suppression.effective_at <= evaluated_at,
                    or_(Suppression.expires_at.is_(None), Suppression.expires_at > evaluated_at),
                )
            )
            is not None
        )
        duplicate_match = session.execute(
            select(PersonProfile.person_id, Person.status)
            .join(Person, Person.id == PersonProfile.person_id)
            .where(
                PersonProfile.workspace_id == settings.default_workspace_id,
                PersonProfile.normalized_url == normalized_url,
            )
        ).one_or_none()
        duplicate_person_id = duplicate_match[0] if duplicate_match is not None else None
        active_person_suppression = (
            session.scalar(
                select(Suppression.id).where(
                    Suppression.workspace_id == settings.default_workspace_id,
                    Suppression.scope == "person",
                    Suppression.person_id == duplicate_person_id,
                    Suppression.revoked_at.is_(None),
                    Suppression.effective_at <= evaluated_at,
                    or_(Suppression.expires_at.is_(None), Suppression.expires_at > evaluated_at),
                )
            )
            if duplicate_person_id is not None
            else None
        )
        duplicate_person_is_suppressed = duplicate_match is not None and (
            duplicate_match[1] == "suppressed" or active_person_suppression is not None
        )
        possible_match_person_id = None
        if duplicate_person_id is None and not profile_is_suppressed:
            possible_match_person_id = session.scalar(
                select(Person.id)
                .where(
                    Person.workspace_id == settings.default_workspace_id,
                    Person.normalized_name == normalized_name,
                    Person.country_code == country_code,
                    Person.status.in_(("active", "needs_review")),
                )
                .order_by(Person.created_at, Person.id)
                .limit(1)
            )
        score = score_individual(
            IndividualScoreInput(
                persona=candidate.persona,
                country_code=country_code,
                region=candidate.region,
                has_professional_presence=candidate.has_professional_presence,
                has_business_relevance=candidate.has_business_relevance,
                is_fictional=candidate.is_fictional,
            ),
            definition,
        )
        status = score.status
        disposition = score.disposition
        reason = score.reason
        if profile_is_suppressed:
            status, disposition, reason = "rejected", "disqualified", "suppressed_profile"
            duplicate_person_id = None
        elif duplicate_person_is_suppressed:
            status, disposition, reason = "rejected", "disqualified", "suppressed_person"
        elif duplicate_person_id is not None:
            status, disposition, reason = "duplicate", "disqualified", "existing_profile_url"
        elif possible_match_person_id is not None:
            status, disposition, reason = "needs_review", "review", "possible_name_match"
        session.add(
            IndividualDiscoveryCandidate(
                workspace_id=settings.default_workspace_id,
                discovery_run_id=run.id,
                provider_key=run.provider_key,
                provider_record_id=provider_record_id,
                candidate_fingerprint=individual_candidate_fingerprint(
                    provider_key=run.provider_key,
                    provider_record_id=provider_record_id,
                    normalized_profile_url=normalized_url,
                ),
                display_name=display_name,
                normalized_name=normalized_name,
                professional_profile_url=candidate.professional_profile_url,
                normalized_profile_url=normalized_url,
                persona=candidate.persona,
                country_code=country_code,
                region=candidate.region,
                service_summary=candidate.service_summary,
                has_professional_presence=candidate.has_professional_presence,
                has_business_relevance=candidate.has_business_relevance,
                is_fictional=True,
                retention_expires_at=None,
                source_url=candidate.source_url,
                observed_at=observed_at,
                status=status,
                disposition=disposition,
                score=score.score,
                maximum_score=score.maximum_score,
                rejection_reason=reason,
                possible_match_person_id=possible_match_person_id,
                duplicate_person_id=duplicate_person_id,
                qualification_json={
                    "algorithm_version": definition["algorithm_version"],
                    "components": score.components,
                    "evidence": {
                        "professional_presence": {
                            "value": candidate.has_professional_presence,
                            "classification": "provider_asserted",
                            "source_url": candidate.source_url,
                            "observed_at": observed_at.isoformat(),
                        },
                        "business_relevance": {
                            "value": candidate.has_business_relevance,
                            "classification": "provider_asserted",
                            "source_url": candidate.source_url,
                            "observed_at": observed_at.isoformat(),
                        },
                    },
                },
                provenance_json={
                    "classification": "provider_asserted",
                    "adapter_kind": "fixture",
                    "fixture": True,
                    "contains_personal_data": False,
                },
            )
        )
        run.discovered_count += 1
        if status == "duplicate":
            run.duplicate_count += 1
        elif status == "rejected":
            run.rejected_count += 1
    run.next_cursor = page.next_cursor


def _query_to_json(query: IndividualDiscoveryQuery) -> dict[str, Any]:
    return {
        "search_text": query.search_text,
        "country_code": query.country_code,
        "region": query.region,
        "limit": query.limit,
        "cursor": query.cursor,
    }


def _require_fictional_url(value: str, *, field_name: str) -> str:
    normalized = normalize_profile_url(value)
    hostname = urlsplit(normalized).hostname
    if hostname is None or not hostname.endswith(".invalid"):
        raise IndividualCollectionNotApprovedError(
            f"Fictional-only {field_name} must use the reserved .invalid domain"
        )
    return normalized


def _hash_json(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()
