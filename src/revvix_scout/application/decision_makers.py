"""Provider-free M5 decision-maker discovery for qualified companies."""

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import DecisionMakerRoleView
from revvix_scout.application.usage import reserve_provider_budget, settle_provider_usage
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    BudgetReservation,
    Company,
    CompanyDomain,
    DecisionMakerCandidate,
    DiscoveryRun,
    Job,
    JobAttempt,
    Person,
    PersonCompanyRole,
    PersonProfile,
    ProviderConfig,
    Suppression,
)
from revvix_scout.domain.individuals import (
    normalize_person_name,
    normalize_profile_url,
    profile_suppression_hash,
)
from revvix_scout.domain.roles import score_decision_maker_role
from revvix_scout.providers.decision_maker_contracts import (
    DecisionMakerPage,
    DecisionMakerProviderRegistry,
    DecisionMakerQuery,
)


class DecisionMakerDiscoveryError(RuntimeError):
    pass


class DecisionMakerCollectionNotApprovedError(DecisionMakerDiscoveryError):
    pass


def promote_decision_maker_candidate(
    *, session: Session, settings: Settings, candidate_id: UUID
) -> DecisionMakerRoleView:
    """Promote one qualified fictional candidate into a person-company role."""

    candidate = session.scalar(
        select(DecisionMakerCandidate)
        .where(
            DecisionMakerCandidate.id == candidate_id,
            DecisionMakerCandidate.workspace_id == settings.default_workspace_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise DecisionMakerDiscoveryError("Decision-maker candidate not found")
    existing_role = session.scalar(
        select(PersonCompanyRole).where(PersonCompanyRole.source_candidate_id == candidate.id)
    )
    if existing_role is not None:
        person = session.get(Person, existing_role.person_id)
        if person is None:
            raise DecisionMakerDiscoveryError("Promoted person disappeared")
        return _role_view(existing_role, person)
    if candidate.status not in ("new", "duplicate") or candidate.role_score < 80:
        raise DecisionMakerDiscoveryError("Candidate is not eligible for promotion")

    now = datetime.now(UTC)
    suppression_targets = [
        Suppression.normalized_value_hash
        == profile_suppression_hash(candidate.normalized_profile_url)
    ]
    if candidate.duplicate_person_id is not None:
        suppression_targets.append(Suppression.person_id == candidate.duplicate_person_id)
    suppression = session.scalar(
        select(Suppression.id).where(
            Suppression.workspace_id == settings.default_workspace_id,
            Suppression.revoked_at.is_(None),
            Suppression.effective_at <= now,
            or_(Suppression.expires_at.is_(None), Suppression.expires_at > now),
            or_(*suppression_targets),
        )
    )
    if suppression is not None:
        raise DecisionMakerCollectionNotApprovedError("Decision-maker candidate is suppressed")

    person = (
        session.get(Person, candidate.duplicate_person_id)
        if candidate.duplicate_person_id is not None
        else None
    )
    if person is None:
        person = Person(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            display_name=candidate.display_name,
            normalized_name=candidate.normalized_name,
            country_code="GB",
            region="England",
            status="active",
            is_fictional=True,
            retention_expires_at=None,
            first_seen_at=candidate.observed_at,
            last_seen_at=candidate.observed_at,
        )
        session.add(person)
        session.flush()
        session.add(
            PersonProfile(
                id=uuid4(),
                workspace_id=settings.default_workspace_id,
                person_id=person.id,
                provider_key=candidate.provider_key,
                provider_record_id=candidate.provider_record_id,
                original_url=candidate.professional_profile_url,
                normalized_url=candidate.normalized_profile_url,
                verification_status="source_asserted",
                source_url=candidate.source_url,
                observed_at=candidate.observed_at,
            )
        )
    relationship = _relationship_type(candidate.title_normalized)
    role = PersonCompanyRole(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        person_id=person.id,
        company_id=candidate.company_id,
        source_candidate_id=candidate.id,
        title_original=candidate.title_original,
        title_normalized=candidate.title_normalized,
        seniority=candidate.seniority,
        department=candidate.department,
        relationship_type=relationship,
        is_current=candidate.is_current,
        started_on=None,
        ended_on=None,
        evidence_classification="provider_asserted",
        verification_status="source_asserted",
        observed_at=candidate.observed_at,
    )
    session.add(role)
    candidate.status = "promoted"
    candidate.duplicate_person_id = person.id
    session.commit()
    return _role_view(role, person)


def execute_decision_maker_discovery(
    *,
    session: Session,
    settings: Settings,
    registry: DecisionMakerProviderRegistry,
    company_id: UUID,
    provider_key: str,
    limit: int,
    idempotency_key: str,
) -> DiscoveryRun:
    """Run one fictional, company-scoped decision-maker research operation."""

    existing_job = session.scalar(
        select(Job).where(
            Job.workspace_id == settings.default_workspace_id,
            Job.job_type == "decision_maker_discovery",
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        run = session.scalar(select(DiscoveryRun).where(DiscoveryRun.job_id == existing_job.id))
        if run is None:
            raise DecisionMakerDiscoveryError("Existing decision-maker job has no run")
        return run

    company = session.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.workspace_id == settings.default_workspace_id,
        )
    )
    if company is None:
        raise DecisionMakerDiscoveryError("Company not found")
    domain = session.scalar(
        select(CompanyDomain.normalized_domain)
        .where(CompanyDomain.company_id == company.id)
        .order_by(CompanyDomain.domain_type, CompanyDomain.created_at)
        .limit(1)
    )
    if domain is None:
        raise DecisionMakerDiscoveryError("Company requires a verified domain before role research")

    provider = registry.get(provider_key)
    config = session.scalar(
        select(ProviderConfig).where(
            ProviderConfig.workspace_id == settings.default_workspace_id,
            ProviderConfig.provider_key == provider_key,
        )
    )
    if config is None or not config.enabled:
        raise DecisionMakerDiscoveryError("Decision-maker provider is disabled")
    if provider.is_live or config.live_calls_allowed:
        raise DecisionMakerCollectionNotApprovedError("Live decision-maker collection is disabled")
    if not bool(config.config_json.get("fictional_data_only")):
        raise DecisionMakerCollectionNotApprovedError("Provider must remain fictional-only")
    target_roles = tuple(str(role) for role in config.config_json.get("target_roles", ()))
    if not target_roles:
        raise DecisionMakerDiscoveryError("Decision-maker target roles are not configured")

    query = DecisionMakerQuery(company.id, company.display_name, domain, target_roles, limit)
    request_json = {
        "company_id": str(company.id),
        "company_name": company.display_name,
        "normalized_domain": domain,
        "target_roles": list(target_roles),
        "limit": limit,
    }
    fingerprint = _hash_json(
        {"discovery_kind": "decision_maker", "provider_key": provider_key, **request_json}
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
        job_type="decision_maker_discovery",
        idempotency_key=idempotency_key,
        status="running",
        input_json=request_json,
        max_attempts=1,
        next_attempt_at=now,
        started_at=now,
        worker_id="inline-decision-maker-api",
    )
    session.add(job)
    session.flush()
    run = DiscoveryRun(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        job_id=job.id,
        icp_version_id=settings.default_icp_version_id,
        provider_key=provider_key,
        pipeline_kind="business",
        discovery_kind="decision_maker",
        request_fingerprint=fingerprint,
        request_json=request_json,
        status="running",
        started_at=now,
    )
    session.add(run)
    session.flush()
    reservation = reserve_provider_budget(
        session=session,
        settings=settings,
        run=run,
        provider_key=provider_key,
        operation="decision_maker_discovery",
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
    session.commit()

    page: DecisionMakerPage | None = None
    failure: Exception | None = None
    try:
        page = provider.discover(query)
    except Exception as exc:
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
        raise DecisionMakerDiscoveryError("Decision-maker run state disappeared")
    run, job, attempt, reservation = (
        loaded_run,
        loaded_job,
        loaded_attempt,
        loaded_reservation,
    )
    if page is not None:
        try:
            with session.begin_nested():
                _persist_candidates(
                    session=session,
                    settings=settings,
                    run=run,
                    company=company,
                    page=page,
                    target_roles=target_roles,
                )
                session.flush()
        except Exception as exc:
            failure = exc
    if page is not None and failure is None:
        run.status = job.status = attempt.status = "succeeded"
        actual_units, outcome = page.actual_units, "succeeded"
    else:
        run.status = job.status = attempt.status = "failed"
        run.error_code = job.error_code = attempt.error_category = "processing"
        message = str(failure or "Unknown decision-maker failure")[:500]
        run.error_message = job.error_message = attempt.error_message = message
        actual_units, outcome = 0, "failed"
    run.completed_at = job.completed_at = attempt.completed_at = finished_at
    job.worker_id = None
    settle_provider_usage(
        session=session,
        settings=settings,
        run=run,
        reservation=reservation,
        operation="decision_maker_discovery",
        actual_units=actual_units,
        outcome=outcome,
        now=finished_at,
    )
    session.commit()
    return run


def _persist_candidates(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    company: Company,
    page: DecisionMakerPage,
    target_roles: tuple[str, ...],
) -> None:
    for value in page.candidates:
        if not value.is_fictional:
            raise DecisionMakerCollectionNotApprovedError("Non-fictional person returned")
        profile_url = normalize_profile_url(value.professional_profile_url)
        source_url = normalize_profile_url(value.source_url)
        profile_host = urlsplit(profile_url).hostname
        source_host = urlsplit(source_url).hostname
        if (
            profile_host is None
            or source_host is None
            or not profile_host.endswith(".invalid")
            or not source_host.endswith(".invalid")
        ):
            raise DecisionMakerCollectionNotApprovedError("Fixture URLs must use .invalid")
        score = score_decision_maker_role(value.title, target_roles)
        duplicate_person_id = session.scalar(
            select(PersonProfile.person_id).where(
                PersonProfile.workspace_id == settings.default_workspace_id,
                PersonProfile.normalized_url == profile_url,
            )
        )
        status = "duplicate" if duplicate_person_id is not None else score.status
        reason = "existing_profile_url" if duplicate_person_id is not None else score.reason
        session.add(
            DecisionMakerCandidate(
                workspace_id=settings.default_workspace_id,
                discovery_run_id=run.id,
                company_id=company.id,
                provider_key=run.provider_key,
                provider_record_id=value.provider_record_id,
                display_name=value.display_name.strip(),
                normalized_name=normalize_person_name(value.display_name),
                professional_profile_url=value.professional_profile_url,
                normalized_profile_url=profile_url,
                title_original=value.title.strip(),
                title_normalized=score.normalized_title,
                seniority=value.seniority,
                department=value.department,
                is_current=value.is_current,
                is_fictional=True,
                source_url=value.source_url,
                observed_at=value.observed_at.astimezone(UTC),
                role_score=score.score,
                role_maximum_score=score.maximum_score,
                status=status,
                rejection_reason=reason,
                duplicate_person_id=duplicate_person_id,
                qualification_json={
                    "matched_role": score.matched_role,
                    "configured_roles": list(target_roles),
                    "explanation": "Title matched against configured buyer roles.",
                },
                provenance_json={
                    "classification": "provider_asserted",
                    "fixture": True,
                    "source_url": value.source_url,
                },
            )
        )
        run.discovered_count += 1
        if status == "duplicate":
            run.duplicate_count += 1
        elif status == "rejected":
            run.rejected_count += 1


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _relationship_type(normalized_title: str) -> str:
    if "partner" in normalized_title:
        return "partner"
    if "director" in normalized_title:
        return "director"
    if "owner" in normalized_title:
        return "owner"
    return "employee"


def _role_view(role: PersonCompanyRole, person: Person) -> DecisionMakerRoleView:
    return DecisionMakerRoleView(
        id=role.id,
        candidate_id=role.source_candidate_id,
        person_id=role.person_id,
        company_id=role.company_id,
        display_name=person.display_name,
        title=role.title_original,
        relationship_type=role.relationship_type,
        is_current=role.is_current,
        evidence_classification=role.evidence_classification,
    )
