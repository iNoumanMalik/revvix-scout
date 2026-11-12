"""Configurable deterministic qualification rules for the approved business ICP."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class Disposition(StrEnum):
    QUALIFIED = "qualified"
    REVIEW = "review"
    UNQUALIFIED = "unqualified"
    DISQUALIFIED = "disqualified"


@dataclass(frozen=True, slots=True)
class ScoreInput:
    industry: str | None
    employee_count: int | None
    country_code: str | None
    technology_need: str | None
    excluded_reason: str | None
    evidence_ids: dict[str, UUID]


@dataclass(frozen=True, slots=True)
class ScoreComponentResult:
    rule_key: str
    points: int
    maximum_points: int
    result: str
    explanation: str
    evidence_id: UUID | None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total_score: int
    maximum_score: int
    disposition: Disposition
    components: tuple[ScoreComponentResult, ...]
    missing_fields: tuple[str, ...]


ALGORITHM_VERSION = "business-icp-2"


def icp_definition() -> dict[str, Any]:
    """Return the approved England independent accounting-firm ICP."""

    return {
        "schema_version": 2,
        "algorithm_version": ALGORITHM_VERSION,
        "target_industries": ["accounting", "bookkeeping"],
        "target_countries": ["GB"],
        "target_regions": ["England"],
        "preferred_legal_forms": ["ltd", "llp"],
        "allowed_company_statuses": ["active"],
        "employee_range": {"preferred_min": 5, "preferred_max": 30, "review_max": 50},
        "technology_needs": [
            "manual_processes",
            "legacy_systems",
            "integration_gap",
            "data_ai_opportunity",
            "cloud_it_gap",
            "digital_experience",
        ],
        "weights": {"industry": 30, "company_size": 20, "region": 15, "technology_need": 35},
        "thresholds": {"qualified": 60, "review": 35},
        "disqualifiers": [
            "dormant",
            "duplicate",
            "major_chain",
            "unrelated",
            "insufficient_evidence",
        ],
        "outreach": {"human_approval_required": True, "individual_enabled": False},
    }


def score_business(value: ScoreInput, definition: dict[str, Any] | None = None) -> ScoreResult:
    """Score against a persisted definition; no filter or threshold is hardcoded."""

    rules = definition or icp_definition()
    weights = rules["weights"]
    components = (
        _categorical(
            "industry", value.industry, set(rules["target_industries"]), weights["industry"], value
        ),
        _company_size(value, rules),
        _categorical(
            "region", value.country_code, set(rules["target_countries"]), weights["region"], value
        ),
        _categorical(
            "technology_need",
            value.technology_need,
            set(rules["technology_needs"]),
            weights["technology_need"],
            value,
        ),
    )
    total = sum(component.points for component in components)
    missing = tuple(
        field
        for field, field_value in (
            ("industry", value.industry),
            ("employee_count", value.employee_count),
            ("country_code", value.country_code),
            ("technology_need", value.technology_need),
        )
        if field_value is None
    )
    thresholds = rules["thresholds"]
    if value.excluded_reason:
        disposition, total = Disposition.DISQUALIFIED, 0
    elif total >= thresholds["qualified"]:
        disposition = Disposition.QUALIFIED
    elif total >= thresholds["review"]:
        disposition = Disposition.REVIEW
    else:
        disposition = Disposition.UNQUALIFIED
    return ScoreResult(total, sum(weights.values()), disposition, components, missing)


def _categorical(
    rule_key: str, actual: str | None, targets: set[str], maximum: int, value: ScoreInput
) -> ScoreComponentResult:
    if actual is None:
        return _missing(rule_key, maximum)
    matched = actual in targets
    return ScoreComponentResult(
        rule_key=rule_key,
        points=maximum if matched else 0,
        maximum_points=maximum,
        result="target" if matched else "non_target",
        explanation=f"{rule_key} evaluated against ICP version configuration.",
        evidence_id=value.evidence_ids.get("country_code" if rule_key == "region" else rule_key),
    )


def _company_size(value: ScoreInput, rules: dict[str, Any]) -> ScoreComponentResult:
    maximum = int(rules["weights"]["company_size"])
    if value.employee_count is None:
        return _missing("company_size", maximum)
    limits = rules["employee_range"]
    if limits["preferred_min"] <= value.employee_count <= limits["preferred_max"]:
        points, result = maximum, "preferred"
    elif value.employee_count <= limits["review_max"]:
        points, result = maximum // 2, "review_range"
    else:
        points, result = 0, "outside_range"
    return ScoreComponentResult(
        "company_size",
        points,
        maximum,
        result,
        "Employee count evaluated against ICP version configuration.",
        value.evidence_ids.get("employee_count"),
    )


def _missing(rule_key: str, maximum: int) -> ScoreComponentResult:
    return ScoreComponentResult(
        rule_key,
        0,
        maximum,
        "missing",
        "No accepted evidence was supplied; missing values score zero.",
        None,
    )
