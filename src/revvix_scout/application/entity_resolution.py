"""Review-first logical entity matching with reversible merge overlays."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from revvix_scout.config import Settings
from revvix_scout.db.models import (
    Company,
    EntityMatchCandidate,
    EntityMergeEvent,
    Person,
)
from revvix_scout.domain.enrichment import evaluate_match_signals


class EntityResolutionError(RuntimeError):
    pass


def create_match_candidate(
    *,
    session: Session,
    settings: Settings,
    entity_kind: str,
    left_id: UUID,
    right_id: UUID,
    exact_stable_identifier: bool,
    name_similarity: float,
) -> EntityMatchCandidate:
    """Create one canonical review suggestion without merging entities."""

    if left_id == right_id:
        raise EntityResolutionError("Match subjects must be distinct")
    if entity_kind == "company":
        _require_company(session, settings, left_id)
        _require_company(session, settings, right_id)
    elif entity_kind == "person":
        _require_person(session, settings, left_id)
        _require_person(session, settings, right_id)
    else:
        raise EntityResolutionError("Unsupported entity kind")
    canonical_left, canonical_right = sorted((left_id, right_id))
    existing = _find_pair(
        session,
        settings,
        entity_kind,
        canonical_left,
        canonical_right,
    )
    if existing is not None:
        return existing
    decision = evaluate_match_signals(
        exact_stable_identifier=exact_stable_identifier,
        name_similarity=name_similarity,
    )
    now = datetime.now(UTC)
    candidate = EntityMatchCandidate(
        workspace_id=settings.default_workspace_id,
        entity_kind=entity_kind,
        left_company_id=canonical_left if entity_kind == "company" else None,
        right_company_id=canonical_right if entity_kind == "company" else None,
        left_person_id=canonical_left if entity_kind == "person" else None,
        right_person_id=canonical_right if entity_kind == "person" else None,
        match_basis=decision.basis,
        algorithm_version="entity-match-1",
        score=decision.score,
        features_json={
            "exact_stable_identifier": exact_stable_identifier,
            "name_similarity": name_similarity,
            "explanation": decision.explanation,
        },
        status="pending" if decision.status == "pending_review" else "rejected",
        reviewed_at=None if decision.status == "pending_review" else now,
    )
    session.add(candidate)
    session.commit()
    return candidate


def review_match_candidate(
    *,
    session: Session,
    settings: Settings,
    candidate_id: UUID,
    action: str,
    survivor_id: UUID | None,
    reason: str,
) -> EntityMatchCandidate:
    """Reject a suggestion or record a non-destructive logical merge."""

    candidate = session.scalar(
        select(EntityMatchCandidate)
        .where(
            EntityMatchCandidate.id == candidate_id,
            EntityMatchCandidate.workspace_id == settings.default_workspace_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise EntityResolutionError("Match candidate not found")
    if action == "reject":
        if candidate.status == "merged":
            raise EntityResolutionError("Merged candidate must be unmerged before rejection")
        candidate.status = "rejected"
        candidate.reviewed_at = datetime.now(UTC)
        session.commit()
        return candidate
    if action != "merge" or survivor_id is None:
        raise EntityResolutionError("Invalid match review action")
    if candidate.status == "rejected":
        raise EntityResolutionError("Rejected candidate cannot be merged")
    if candidate.status == "merged":
        return candidate

    left_id, right_id = candidate_subject_ids(candidate)
    if survivor_id not in (left_id, right_id):
        raise EntityResolutionError("Survivor must be one of the match subjects")
    merged_id = right_id if survivor_id == left_id else left_id
    if candidate.entity_kind == "person":
        survivor = _require_person(session, settings, survivor_id)
        merged = _require_person(session, settings, merged_id)
        if survivor.status in {"suppressed", "deleted"} or merged.status in {
            "suppressed",
            "deleted",
        }:
            raise EntityResolutionError("Suppressed or deleted people cannot be merged")

    now = datetime.now(UTC)
    event = EntityMergeEvent(
        workspace_id=settings.default_workspace_id,
        match_candidate_id=candidate.id,
        entity_kind=candidate.entity_kind,
        action="merge",
        survivor_company_id=survivor_id if candidate.entity_kind == "company" else None,
        merged_company_id=merged_id if candidate.entity_kind == "company" else None,
        survivor_person_id=survivor_id if candidate.entity_kind == "person" else None,
        merged_person_id=merged_id if candidate.entity_kind == "person" else None,
        snapshot_json={
            "candidate_status_before": candidate.status,
            "logical_overlay": True,
            "references_rewritten": False,
        },
        reason=reason,
        actor_type="operator",
        occurred_at=now,
    )
    session.add(event)
    candidate.status = "merged"
    candidate.reviewed_at = now
    session.commit()
    return candidate


def unmerge_entity_event(
    *,
    session: Session,
    settings: Settings,
    merge_event_id: UUID,
    reason: str,
) -> EntityMergeEvent:
    """Append one reversal and restore the candidate to confirmed review state."""

    merge_event = session.scalar(
        select(EntityMergeEvent)
        .where(
            EntityMergeEvent.id == merge_event_id,
            EntityMergeEvent.workspace_id == settings.default_workspace_id,
            EntityMergeEvent.action == "merge",
        )
        .with_for_update()
    )
    if merge_event is None:
        raise EntityResolutionError("Merge event not found")
    existing = session.scalar(
        select(EntityMergeEvent).where(EntityMergeEvent.reverses_event_id == merge_event.id)
    )
    if existing is not None:
        return existing
    if merge_event.match_candidate_id is None:
        raise EntityResolutionError("Merge event has no match candidate")
    candidate = session.scalar(
        select(EntityMatchCandidate)
        .where(EntityMatchCandidate.id == merge_event.match_candidate_id)
        .with_for_update()
    )
    if candidate is None:
        raise EntityResolutionError("Merge candidate disappeared")
    now = datetime.now(UTC)
    reversal = EntityMergeEvent(
        workspace_id=settings.default_workspace_id,
        match_candidate_id=candidate.id,
        entity_kind=merge_event.entity_kind,
        action="unmerge",
        survivor_company_id=merge_event.survivor_company_id,
        merged_company_id=merge_event.merged_company_id,
        survivor_person_id=merge_event.survivor_person_id,
        merged_person_id=merge_event.merged_person_id,
        reverses_event_id=merge_event.id,
        snapshot_json={
            "restored_candidate_status": "confirmed",
            "logical_overlay_removed": True,
        },
        reason=reason,
        actor_type="operator",
        occurred_at=now,
    )
    session.add(reversal)
    candidate.status = "confirmed"
    candidate.reviewed_at = now
    session.commit()
    return reversal


def candidate_subject_ids(candidate: EntityMatchCandidate) -> tuple[UUID, UUID]:
    if candidate.entity_kind == "company":
        if candidate.left_company_id is None or candidate.right_company_id is None:
            raise EntityResolutionError("Company match subjects are incomplete")
        return candidate.left_company_id, candidate.right_company_id
    if candidate.left_person_id is None or candidate.right_person_id is None:
        raise EntityResolutionError("Person match subjects are incomplete")
    return candidate.left_person_id, candidate.right_person_id


def _require_company(
    session: Session,
    settings: Settings,
    subject_id: UUID,
) -> Company:
    subject = session.get(Company, subject_id)
    if subject is None or subject.workspace_id != settings.default_workspace_id:
        raise EntityResolutionError("Entity subject not found")
    return subject


def _require_person(
    session: Session,
    settings: Settings,
    subject_id: UUID,
) -> Person:
    subject = session.get(Person, subject_id)
    if subject is None or subject.workspace_id != settings.default_workspace_id:
        raise EntityResolutionError("Entity subject not found")
    return subject


def _find_pair(
    session: Session,
    settings: Settings,
    entity_kind: str,
    left_id: UUID,
    right_id: UUID,
) -> EntityMatchCandidate | None:
    conditions = (
        (
            EntityMatchCandidate.left_company_id == left_id,
            EntityMatchCandidate.right_company_id == right_id,
        )
        if entity_kind == "company"
        else (
            EntityMatchCandidate.left_person_id == left_id,
            EntityMatchCandidate.right_person_id == right_id,
        )
    )
    return session.scalar(
        select(EntityMatchCandidate).where(
            EntityMatchCandidate.workspace_id == settings.default_workspace_id,
            EntityMatchCandidate.entity_kind == entity_kind,
            *conditions,
        )
    )
