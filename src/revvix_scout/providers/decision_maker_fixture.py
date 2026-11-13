"""Fictional M5 decision-maker fixture adapter."""

from datetime import UTC, datetime
from typing import ClassVar

from revvix_scout.providers.decision_maker_contracts import (
    DecisionMakerPage,
    DecisionMakerQuery,
    DiscoveredDecisionMaker,
)


class FictionalDecisionMakerProvider:
    key = "fictional_decision_maker_directory"
    is_live = False

    _records: ClassVar[dict[str, tuple[DiscoveredDecisionMaker, ...]]] = {
        "example.com": (
            DiscoveredDecisionMaker(
                "example-dm-001",
                "Robin Mercer",
                "https://professionals.invalid/robin-mercer-example",
                "Managing Partner",
                "partner",
                "leadership",
                True,
                "https://fixtures.invalid/example-accounting/team/robin-mercer",
                datetime(2026, 11, 1, tzinfo=UTC),
                True,
            ),
            DiscoveredDecisionMaker(
                "example-dm-002",
                "Casey Rowan",
                "https://professionals.invalid/casey-rowan-example",
                "Practice Manager",
                "manager",
                "operations",
                True,
                "https://fixtures.invalid/example-accounting/team/casey-rowan",
                datetime(2026, 11, 1, tzinfo=UTC),
                True,
            ),
            DiscoveredDecisionMaker(
                "example-dm-003",
                "Taylor Finch",
                "https://professionals.invalid/taylor-finch-example",
                "Sales Manager",
                "manager",
                "sales",
                True,
                "https://fixtures.invalid/example-accounting/team/taylor-finch",
                datetime(2026, 11, 1, tzinfo=UTC),
                True,
            ),
        ),
        "oak-quill.example.org": (
            DiscoveredDecisionMaker(
                "oak-dm-001",
                "Morgan Ash",
                "https://professionals.invalid/morgan-ash-oak-quill",
                "Director",
                "director",
                "leadership",
                True,
                "https://fixtures.invalid/oak-quill/team/morgan-ash",
                datetime(2026, 11, 1, tzinfo=UTC),
                True,
            ),
        ),
    }

    def estimate_units(self, query: DecisionMakerQuery) -> int:
        return 1

    def discover(self, query: DecisionMakerQuery) -> DecisionMakerPage:
        return DecisionMakerPage(
            candidates=self._records.get(query.normalized_domain, ())[: query.limit],
            actual_units=1,
        )
