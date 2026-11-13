"""Human-reviewed promotion and suppression for fictional M4 individual leads."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import (
    IndividualLeadPage,
    IndividualLeadView,
    IndividualReviewRequest,
    IndividualReviewResult,
    PersonSuppressionView,
)
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    IndividualDiscoveryCandidate,
    IndividualReviewDecision,
    Lead,
    Person,
    PersonProfile,
    Suppression,
)
from revvix_scout.domain.individuals import profile_suppression_hash


class IndividualWorkflowError(RuntimeError):
    pass


class IndividualCandidateNotFoundError(IndividualWorkflowError):
    pass


class IndividualReviewConflictError(IndividualWorkflowError):
    pass


class PersonNotFoundError(IndividualWorkflowError):
    pass


class IndividualSuppressedError(IndividualWorkflowError):
    pass


def resolve_individual_candidate(
    *,
    session: Session,
    settings: Settings,
    candidate_id: UUID,
    request: IndividualReviewRequest,
) -> IndividualReviewResult:
    """Apply one immutable operator decision to an individual candidate."""

    candidate = session.scalar(
        select(IndividualDiscoveryCandidate)
        .where(
            IndividualDiscoveryCandidate.id == candidate_id,
            IndividualDiscoveryCandidate.workspace_id == settings.default_workspace_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise IndividualCandidateNotFoundError(str(candidate_id))

    existing_decision = session.scalar(
        select(IndividualReviewDecision).where(
            IndividualReviewDecision.candidate_id == candidate.id,
            IndividualReviewDecision.reversed_at.is_(None),
        )
    )
    if existing_decision is not None:
        if existing_decision.action != request.action or (
            existing_decision.selected_person_id != request.person_id
            and request.action == "link_existing"
        ):
            raise IndividualReviewConflictError("Candidate already has a different final decision")
        return _review_result(session=session, candidate=candidate, decision=existing_decision)

    now = datetime.now(UTC)
    lead: Lead | None = None
    selected_person: Person | None = None
    if request.action == "promote_new":
        _require_promotable(candidate, allow_exact_duplicate=False)
        _require_profile_not_suppressed(
            session=session,
            settings=settings,
            normalized_profile_url=candidate.normalized_profile_url,
            now=now,
        )
        selected_person = Person(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            display_name=candidate.display_name,
            normalized_name=candidate.normalized_name,
            country_code=candidate.country_code,
            region=candidate.region,
            status="active",
            is_fictional=candidate.is_fictional,
            retention_expires_at=candidate.retention_expires_at,
            first_seen_at=candidate.observed_at,
            last_seen_at=candidate.observed_at,
        )
        session.add(selected_person)
        session.flush()
        _add_profile(session=session, candidate=candidate, person=selected_person)
        lead = _get_or_create_individual_lead(
            session=session,
            settings=settings,
            candidate=candidate,
            person=selected_person,
            now=now,
        )
        candidate.possible_match_person_id = None
        candidate.duplicate_person_id = selected_person.id
        candidate.status = "promoted"
        candidate.disposition = lead.disposition
        candidate.rejection_reason = None
    elif request.action == "link_existing":
        _require_promotable(candidate, allow_exact_duplicate=True)
        if (
            request.person_id is None
        ):  # validated at the HTTP boundary; keep application fail-closed
            raise IndividualReviewConflictError("Existing person ID is required")
        selected_person = session.scalar(
            select(Person)
            .where(
                Person.id == request.person_id,
                Person.workspace_id == settings.default_workspace_id,
            )
            .with_for_update()
        )
        if selected_person is None:
            raise PersonNotFoundError(str(request.person_id))
        _require_person_not_suppressed(
            session=session,
            settings=settings,
            person=selected_person,
            now=now,
        )
        _require_profile_not_suppressed(
            session=session,
            settings=settings,
            normalized_profile_url=candidate.normalized_profile_url,
            now=now,
        )
        _link_profile(session=session, candidate=candidate, person=selected_person)
        selected_person.last_seen_at = max(selected_person.last_seen_at, candidate.observed_at)
        lead = _get_or_create_individual_lead(
            session=session,
            settings=settings,
            candidate=candidate,
            person=selected_person,
            now=now,
        )
        candidate.possible_match_person_id = None
        candidate.duplicate_person_id = selected_person.id
        candidate.status = "promoted"
        candidate.disposition = lead.disposition
        candidate.rejection_reason = None
    elif request.action == "reject":
        if candidate.status in ("promoted", "rejected"):
            raise IndividualReviewConflictError("Candidate is already in a final state")
        candidate.status = "rejected"
        candidate.disposition = "disqualified"
        candidate.rejection_reason = "operator_rejected"
        candidate.possible_match_person_id = None
    else:
        if candidate.status == "promoted":
            raise IndividualReviewConflictError("Promoted candidates must be suppressed by person")
        _suppress_profile(
            session=session,
            settings=settings,
            normalized_profile_url=candidate.normalized_profile_url,
            reason_category="operator_suppressed",
            now=now,
        )
        candidate.status = "rejected"
        candidate.disposition = "disqualified"
        candidate.rejection_reason = "suppressed_profile"
        candidate.possible_match_person_id = None
        candidate.duplicate_person_id = None

    decision = IndividualReviewDecision(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        candidate_id=candidate.id,
        action=request.action,
        selected_person_id=selected_person.id if selected_person is not None else None,
        lead_id=lead.id if lead is not None else None,
        reason=request.reason.strip(),
        actor_type="operator",
        decided_at=now,
    )
    session.add(decision)
    session.commit()
    return _review_result(session=session, candidate=candidate, decision=decision)


def reverse_individual_review(
    *,
    session: Session,
    settings: Settings,
    candidate_id: UUID,
    actor_user_id: UUID,
    reason: str,
) -> IndividualDiscoveryCandidate:
    """Reopen a rejected candidate while preserving its prior decision as history."""

    candidate = session.scalar(
        select(IndividualDiscoveryCandidate)
        .where(
            IndividualDiscoveryCandidate.id == candidate_id,
            IndividualDiscoveryCandidate.workspace_id == settings.default_workspace_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise IndividualCandidateNotFoundError(str(candidate_id))
    decision = session.scalar(
        select(IndividualReviewDecision)
        .where(
            IndividualReviewDecision.candidate_id == candidate.id,
            IndividualReviewDecision.reversed_at.is_(None),
        )
        .with_for_update()
    )
    if decision is None:
        latest = session.scalar(
            select(IndividualReviewDecision)
            .where(IndividualReviewDecision.candidate_id == candidate.id)
            .order_by(
                IndividualReviewDecision.decided_at.desc(),
                IndividualReviewDecision.id.desc(),
            )
            .limit(1)
        )
        if (
            latest is not None
            and latest.reversed_at is not None
            and candidate.status == "needs_review"
        ):
            return candidate
        raise IndividualReviewConflictError("Candidate has no active review decision to reverse")
    if decision.action != "reject":
        raise IndividualReviewConflictError("Only plain rejection decisions can be safely reversed")

    now = datetime.now(UTC)
    decision.reversed_at = now
    decision.reversal_reason = reason.strip()
    decision.reversed_by_user_id = actor_user_id
    candidate.status = "needs_review"
    candidate.disposition = "review"
    candidate.rejection_reason = None
    session.commit()
    return candidate


def list_individual_leads(*, session: Session, settings: Settings) -> IndividualLeadPage:
    """List the workspace's fictional person-subject leads."""

    profile_url = (
        select(PersonProfile.normalized_url)
        .where(PersonProfile.person_id == Lead.person_id)
        .order_by(PersonProfile.created_at, PersonProfile.id)
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Lead, Person, profile_url)
        .join(Person, Person.id == Lead.person_id)
        .where(
            Lead.workspace_id == settings.default_workspace_id,
            Lead.pipeline_kind == "individual",
        )
        .order_by(Lead.created_at.desc(), Lead.id.desc())
    ).all()
    return IndividualLeadPage(
        items=[_lead_view(lead=lead, person=person, profile_url=url) for lead, person, url in rows]
    )


def suppress_person(
    *,
    session: Session,
    settings: Settings,
    person_id: UUID,
    reason_category: str,
) -> PersonSuppressionView:
    """Suppress one person and immediately disqualify their individual lead."""

    person = session.scalar(
        select(Person)
        .where(
            Person.id == person_id,
            Person.workspace_id == settings.default_workspace_id,
        )
        .with_for_update()
    )
    if person is None:
        raise PersonNotFoundError(str(person_id))
    now = datetime.now(UTC)
    existing = _active_suppression(
        session=session,
        settings=settings,
        now=now,
        person_id=person.id,
    )
    if existing is None:
        stale = session.scalar(
            select(Suppression).where(
                Suppression.workspace_id == settings.default_workspace_id,
                Suppression.scope == "person",
                Suppression.person_id == person.id,
                Suppression.revoked_at.is_(None),
            )
        )
        if stale is not None:
            stale.revoked_at = now
            session.flush()
        existing = Suppression(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            scope="person",
            person_id=person.id,
            normalized_value_hash=None,
            reason_category=reason_category,
            source="privacy_request" if reason_category == "privacy_request" else "operator",
            effective_at=now,
        )
        session.add(existing)
    person.status = "suppressed"
    leads = session.scalars(
        select(Lead).where(
            Lead.workspace_id == settings.default_workspace_id,
            Lead.pipeline_kind == "individual",
            Lead.person_id == person.id,
        )
    ).all()
    for lead in leads:
        lead.stage = "suppressed"
        lead.disposition = "disqualified"
        lead.last_activity_at = now
    session.commit()
    return PersonSuppressionView(
        person_id=person.id,
        status=person.status,
        reason_category=existing.reason_category,
        effective_at=existing.effective_at,
    )


def _require_promotable(
    candidate: IndividualDiscoveryCandidate, *, allow_exact_duplicate: bool
) -> None:
    allowed = {"new", "needs_review"}
    if allow_exact_duplicate:
        allowed.add("duplicate")
    if candidate.status not in allowed:
        raise IndividualReviewConflictError("Candidate is not eligible for promotion")
    if not candidate.is_fictional:
        raise IndividualReviewConflictError("Only fictional candidates can be promoted in M4")


def _lead_disposition(candidate: IndividualDiscoveryCandidate) -> str:
    if not candidate.has_professional_presence or not candidate.has_business_relevance:
        return "disqualified"
    if candidate.score >= 80:
        return "qualified"
    if candidate.score >= 60:
        return "review"
    return "unqualified"


def _get_or_create_individual_lead(
    *,
    session: Session,
    settings: Settings,
    candidate: IndividualDiscoveryCandidate,
    person: Person,
    now: datetime,
) -> Lead:
    lead = session.scalar(
        select(Lead).where(
            Lead.workspace_id == settings.default_workspace_id,
            Lead.icp_version_id == settings.individual_icp_version_id,
            Lead.pipeline_kind == "individual",
            Lead.person_id == person.id,
        )
    )
    disposition = _lead_disposition(candidate)
    if disposition == "disqualified":
        raise IndividualReviewConflictError("Rejected candidates cannot become leads")
    if lead is None:
        lead = Lead(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            company_id=None,
            person_id=person.id,
            icp_version_id=settings.individual_icp_version_id,
            pipeline_kind="individual",
            stage="qualified" if disposition == "qualified" else "review",
            disposition=disposition,
            first_seen_at=candidate.observed_at,
            last_activity_at=now,
        )
        session.add(lead)
        session.flush()
    return lead


def _add_profile(
    *, session: Session, candidate: IndividualDiscoveryCandidate, person: Person
) -> PersonProfile:
    profile = PersonProfile(
        id=uuid4(),
        workspace_id=candidate.workspace_id,
        person_id=person.id,
        provider_key=candidate.provider_key,
        provider_record_id=candidate.provider_record_id,
        original_url=candidate.professional_profile_url,
        normalized_url=candidate.normalized_profile_url,
        verification_status="source_asserted",
        source_url=candidate.source_url,
        observed_at=candidate.observed_at,
    )
    session.add(profile)
    session.flush()
    return profile


def _link_profile(
    *, session: Session, candidate: IndividualDiscoveryCandidate, person: Person
) -> PersonProfile:
    exact = session.scalar(
        select(PersonProfile).where(
            PersonProfile.workspace_id == candidate.workspace_id,
            PersonProfile.normalized_url == candidate.normalized_profile_url,
        )
    )
    if exact is not None:
        if exact.person_id != person.id:
            raise IndividualReviewConflictError("Profile URL belongs to a different person")
        return exact
    provider_record = session.scalar(
        select(PersonProfile).where(
            PersonProfile.workspace_id == candidate.workspace_id,
            PersonProfile.provider_key == candidate.provider_key,
            PersonProfile.provider_record_id == candidate.provider_record_id,
        )
    )
    if provider_record is not None:
        if provider_record.person_id != person.id:
            raise IndividualReviewConflictError("Provider record belongs to a different person")
        return provider_record
    return _add_profile(session=session, candidate=candidate, person=person)


def _require_profile_not_suppressed(
    *,
    session: Session,
    settings: Settings,
    normalized_profile_url: str,
    now: datetime,
) -> None:
    suppression = _active_suppression(
        session=session,
        settings=settings,
        now=now,
        normalized_value_hash=profile_suppression_hash(normalized_profile_url),
    )
    if suppression is not None:
        raise IndividualSuppressedError("Profile is suppressed")


def _require_person_not_suppressed(
    *, session: Session, settings: Settings, person: Person, now: datetime
) -> None:
    if person.status == "suppressed" or _active_suppression(
        session=session,
        settings=settings,
        now=now,
        person_id=person.id,
    ):
        raise IndividualSuppressedError("Person is suppressed")
    if person.status == "deleted":
        raise IndividualReviewConflictError("Deleted people cannot be linked")


def _suppress_profile(
    *,
    session: Session,
    settings: Settings,
    normalized_profile_url: str,
    reason_category: str,
    now: datetime,
) -> Suppression:
    value_hash = profile_suppression_hash(normalized_profile_url)
    existing = _active_suppression(
        session=session,
        settings=settings,
        now=now,
        normalized_value_hash=value_hash,
    )
    if existing is not None:
        return existing
    stale = session.scalar(
        select(Suppression).where(
            Suppression.workspace_id == settings.default_workspace_id,
            Suppression.scope == "profile",
            Suppression.normalized_value_hash == value_hash,
            Suppression.revoked_at.is_(None),
        )
    )
    if stale is not None:
        stale.revoked_at = now
        session.flush()
    suppression = Suppression(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        scope="profile",
        person_id=None,
        normalized_value_hash=value_hash,
        reason_category=reason_category,
        source="operator",
        effective_at=now,
    )
    session.add(suppression)
    return suppression


def _active_suppression(
    *,
    session: Session,
    settings: Settings,
    now: datetime,
    person_id: UUID | None = None,
    normalized_value_hash: str | None = None,
) -> Suppression | None:
    if (person_id is None) == (normalized_value_hash is None):
        raise ValueError("Exactly one suppression target is required")
    target = (
        Suppression.person_id == person_id
        if person_id is not None
        else Suppression.normalized_value_hash == normalized_value_hash
    )
    return session.scalar(
        select(Suppression).where(
            Suppression.workspace_id == settings.default_workspace_id,
            target,
            Suppression.revoked_at.is_(None),
            Suppression.effective_at <= now,
            or_(Suppression.expires_at.is_(None), Suppression.expires_at > now),
        )
    )


def _review_result(
    *,
    session: Session,
    candidate: IndividualDiscoveryCandidate,
    decision: IndividualReviewDecision,
) -> IndividualReviewResult:
    lead_view = None
    if decision.lead_id is not None:
        row = session.execute(
            select(Lead, Person, PersonProfile.normalized_url)
            .join(Person, Person.id == Lead.person_id)
            .join(PersonProfile, PersonProfile.person_id == Person.id)
            .where(Lead.id == decision.lead_id)
            .order_by(PersonProfile.created_at, PersonProfile.id)
            .limit(1)
        ).one()
        lead_view = _lead_view(lead=row[0], person=row[1], profile_url=row[2])
    return IndividualReviewResult(
        candidate_id=candidate.id,
        action=decision.action,
        candidate_status=candidate.status,
        rejection_reason=candidate.rejection_reason,
        lead=lead_view,
    )


def _lead_view(*, lead: Lead, person: Person, profile_url: str) -> IndividualLeadView:
    return IndividualLeadView(
        id=lead.id,
        person_id=person.id,
        display_name=person.display_name,
        normalized_profile_url=profile_url,
        stage=lead.stage,
        disposition=lead.disposition,
        person_status=person.status,
        is_fictional=person.is_fictional,
        created_at=lead.created_at,
    )
