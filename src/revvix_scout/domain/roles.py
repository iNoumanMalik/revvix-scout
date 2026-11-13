"""Deterministic, configurable M5 decision-maker role qualification."""

from dataclasses import dataclass

from revvix_scout.domain.normalization import normalize_company_name


@dataclass(frozen=True, slots=True)
class RoleScore:
    normalized_title: str
    score: int
    maximum_score: int
    matched_role: str | None
    status: str
    reason: str | None


def score_decision_maker_role(title: str, target_roles: tuple[str, ...]) -> RoleScore:
    """Explainably match a title against configured buyer roles."""

    normalized = normalize_company_name(title)
    normalized_targets = tuple(normalize_company_name(role) for role in target_roles)
    exact = next((role for role in normalized_targets if normalized == role), None)
    contained = next(
        (role for role in normalized_targets if role in normalized or normalized in role), None
    )
    matched = exact or contained
    if exact is not None:
        return RoleScore(normalized, 100, 100, exact, "new", None)
    if matched is not None:
        return RoleScore(normalized, 80, 100, matched, "new", None)
    return RoleScore(normalized, 0, 100, None, "rejected", "role_not_configured")
