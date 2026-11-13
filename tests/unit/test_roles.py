from uuid import uuid4

from revvix_scout.domain.roles import score_decision_maker_role
from revvix_scout.providers.decision_maker_contracts import DecisionMakerQuery
from revvix_scout.providers.decision_maker_fixture import FictionalDecisionMakerProvider

TARGETS = ("Managing Partner", "Director", "Practice Manager")


def test_role_scoring_is_configurable_and_explainable() -> None:
    exact = score_decision_maker_role("Managing Partner", TARGETS)
    expanded = score_decision_maker_role("Operations Practice Manager", TARGETS)
    rejected = score_decision_maker_role("Sales Manager", TARGETS)
    assert (exact.score, exact.matched_role, exact.status) == (100, "managing partner", "new")
    assert (expanded.score, expanded.matched_role) == (80, "practice manager")
    assert (rejected.score, rejected.status, rejected.reason) == (
        0,
        "rejected",
        "role_not_configured",
    )


def test_fixture_is_company_scoped_and_contains_no_contact_fields() -> None:
    provider = FictionalDecisionMakerProvider()
    page = provider.discover(
        DecisionMakerQuery(
            company_id=uuid4(),
            company_name="Example Legal Automation",
            normalized_domain="example.com",
            target_roles=TARGETS,
        )
    )
    assert len(page.candidates) == 3
    assert all(item.is_fictional for item in page.candidates)
    assert all("@" not in repr(item) for item in page.candidates)
