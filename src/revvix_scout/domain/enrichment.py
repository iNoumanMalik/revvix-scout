"""Deterministic M6 waterfall, freshness, conflict, and match rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class ClaimSnapshot:
    field: str
    normalized_value: str
    retrieved_at: datetime
    valid_until: datetime | None = None
    verification_status: str = "source_asserted"
    superseded: bool = False


@dataclass(frozen=True, slots=True)
class WaterfallStepDefinition:
    key: str
    requested_fields: tuple[str, ...]
    freshness_days: int
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class WaterfallDecision:
    action: str
    step_key: str | None
    requested_fields: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ClaimConflict:
    field: str
    normalized_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchDecision:
    status: str
    basis: str
    score: float
    explanation: str


def select_next_waterfall_step(
    *,
    required_fields: tuple[str, ...],
    claims: tuple[ClaimSnapshot, ...],
    steps: tuple[WaterfallStepDefinition, ...],
    completed_step_keys: frozenset[str],
    now: datetime,
) -> WaterfallDecision:
    """Select the first step that can fill a missing or stale required field."""

    if not required_fields:
        return WaterfallDecision("stop", None, (), "no_required_fields")
    freshness_by_field: dict[str, int] = {}
    for step in steps:
        if not step.enabled:
            continue
        for field in step.requested_fields:
            freshness_by_field[field] = max(freshness_by_field.get(field, 0), step.freshness_days)
    fresh_fields = {
        claim.field
        for claim in claims
        if _claim_is_usable(claim)
        and _claim_is_fresh(
            claim,
            now=now,
            freshness_days=freshness_by_field.get(claim.field),
        )
    }
    missing = tuple(field for field in required_fields if field not in fresh_fields)
    if not missing:
        return WaterfallDecision("stop", None, (), "required_fields_satisfied")

    for step in steps:
        if not step.enabled or step.key in completed_step_keys:
            continue
        step_cutoff = now - timedelta(days=step.freshness_days)
        step_fresh = {
            claim.field
            for claim in claims
            if _claim_is_usable(claim)
            and claim.field in step.requested_fields
            and claim.retrieved_at >= step_cutoff
            and (claim.valid_until is None or claim.valid_until >= now)
        }
        requested = tuple(
            field for field in step.requested_fields if field in missing and field not in step_fresh
        )
        if requested:
            return WaterfallDecision("call", step.key, requested, "missing_or_stale_fields")
    return WaterfallDecision("stop", None, missing, "waterfall_exhausted")


def find_claim_conflicts(
    claims: tuple[ClaimSnapshot, ...], *, now: datetime
) -> tuple[ClaimConflict, ...]:
    """Return active fields with multiple provider or human-visible values."""

    values_by_field: dict[str, set[str]] = {}
    for claim in claims:
        if not _claim_is_usable(claim):
            continue
        if claim.valid_until is not None and claim.valid_until < now:
            continue
        values_by_field.setdefault(claim.field, set()).add(claim.normalized_value)
    return tuple(
        ClaimConflict(field, tuple(sorted(values)))
        for field, values in sorted(values_by_field.items())
        if len(values) > 1
    )


def evaluate_match_signals(
    *,
    exact_stable_identifier: bool,
    name_similarity: float,
) -> MatchDecision:
    """Require review for every suggestion; fuzzy names never auto-merge."""

    if exact_stable_identifier:
        return MatchDecision(
            "pending_review",
            "exact",
            1.0,
            "Stable canonical identifier matches; operator confirmation is required.",
        )
    if name_similarity >= 0.8:
        return MatchDecision(
            "pending_review",
            "fuzzy",
            name_similarity,
            "Name similarity is only a review signal and cannot merge entities.",
        )
    return MatchDecision("rejected", "fuzzy", name_similarity, "Similarity is below threshold.")


def _claim_is_usable(claim: ClaimSnapshot) -> bool:
    return not claim.superseded and claim.verification_status not in {"invalid", "conflicting"}


def _claim_is_fresh(claim: ClaimSnapshot, *, now: datetime, freshness_days: int | None) -> bool:
    if claim.valid_until is not None:
        return claim.valid_until >= now
    if freshness_days is None:
        return False
    return claim.retrieved_at >= now - timedelta(days=freshness_days)
