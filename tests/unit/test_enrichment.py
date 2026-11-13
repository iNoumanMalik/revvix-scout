from datetime import UTC, datetime, timedelta
from uuid import uuid4

from revvix_scout.domain.enrichment import (
    ClaimSnapshot,
    WaterfallStepDefinition,
    evaluate_match_signals,
    find_claim_conflicts,
    select_next_waterfall_step,
)
from revvix_scout.providers.enrichment_contracts import EnrichmentQuery
from revvix_scout.providers.enrichment_fixture import FictionalFirmographicEnrichmentProvider

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def test_waterfall_skips_fresh_fields_and_stops_when_satisfied() -> None:
    steps = (
        WaterfallStepDefinition("free", ("industry", "employee_count"), 30),
        WaterfallStepDefinition("fallback", ("employee_count",), 7),
    )
    claims = (ClaimSnapshot("industry", "accounting", NOW, NOW + timedelta(days=30)),)
    decision = select_next_waterfall_step(
        required_fields=("industry", "employee_count"),
        claims=claims,
        steps=steps,
        completed_step_keys=frozenset(),
        now=NOW,
    )
    assert (decision.action, decision.step_key, decision.requested_fields) == (
        "call",
        "free",
        ("employee_count",),
    )
    complete = select_next_waterfall_step(
        required_fields=("industry",),
        claims=claims,
        steps=steps,
        completed_step_keys=frozenset(),
        now=NOW,
    )
    assert (complete.action, complete.reason) == ("stop", "required_fields_satisfied")


def test_waterfall_moves_to_fallback_then_reports_exhaustion() -> None:
    steps = (
        WaterfallStepDefinition("free", ("industry",), 30),
        WaterfallStepDefinition("fallback", ("industry",), 30),
    )
    fallback = select_next_waterfall_step(
        required_fields=("industry",),
        claims=(),
        steps=steps,
        completed_step_keys=frozenset({"free"}),
        now=NOW,
    )
    assert (fallback.action, fallback.step_key) == ("call", "fallback")
    exhausted = select_next_waterfall_step(
        required_fields=("industry",),
        claims=(),
        steps=steps,
        completed_step_keys=frozenset({"free", "fallback"}),
        now=NOW,
    )
    assert (exhausted.action, exhausted.reason) == ("stop", "waterfall_exhausted")


def test_stale_and_conflicting_claims_remain_visible_but_do_not_satisfy_goal() -> None:
    claims = (
        ClaimSnapshot("employee_count", "12", NOW - timedelta(days=60), NOW - timedelta(days=1)),
        ClaimSnapshot("employee_count", "20", NOW, NOW + timedelta(days=30)),
        ClaimSnapshot(
            "employee_count",
            "99",
            NOW,
            NOW + timedelta(days=30),
            verification_status="conflicting",
        ),
    )
    conflicts = find_claim_conflicts(claims, now=NOW)
    assert conflicts == ()
    decision = select_next_waterfall_step(
        required_fields=("employee_count",),
        claims=claims,
        steps=(WaterfallStepDefinition("free", ("employee_count",), 30),),
        completed_step_keys=frozenset(),
        now=NOW,
    )
    assert decision.reason == "required_fields_satisfied"

    stale_only = select_next_waterfall_step(
        required_fields=("employee_count",),
        claims=(claims[0],),
        steps=(WaterfallStepDefinition("free", ("employee_count",), 30),),
        completed_step_keys=frozenset(),
        now=NOW,
    )
    assert (stale_only.action, stale_only.requested_fields) == ("call", ("employee_count",))


def test_active_different_values_are_reported_as_conflicts() -> None:
    claims = (
        ClaimSnapshot("industry", "accounting", NOW),
        ClaimSnapshot("industry", "bookkeeping", NOW),
    )
    conflict = find_claim_conflicts(claims, now=NOW)[0]
    assert conflict.field == "industry"
    assert conflict.normalized_values == ("accounting", "bookkeeping")


def test_exact_and_fuzzy_matches_both_require_review() -> None:
    exact = evaluate_match_signals(exact_stable_identifier=True, name_similarity=1.0)
    fuzzy = evaluate_match_signals(exact_stable_identifier=False, name_similarity=0.92)
    rejected = evaluate_match_signals(exact_stable_identifier=False, name_similarity=0.3)
    assert (exact.status, exact.basis) == ("pending_review", "exact")
    assert (fuzzy.status, fuzzy.basis) == ("pending_review", "fuzzy")
    assert rejected.status == "rejected"


def test_fixture_is_metadata_only_and_returns_requested_fictional_claims() -> None:
    provider = FictionalFirmographicEnrichmentProvider()
    result = provider.enrich(
        EnrichmentQuery(
            lead_id=uuid4(),
            pipeline_kind="business",
            company_id=uuid4(),
            person_id=None,
            requested_fields=("employee_count",),
            canonical_domain="example.com",
        )
    )
    assert result.source.metadata_only is True
    assert result.source.canonical_url.startswith("https://fixtures.invalid/")
    assert [claim.claim_type for claim in result.claims] == ["employee_count"]
    assert not hasattr(result, "raw_content")
