"""Deterministic identity and qualification rules for individual discovery."""

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from revvix_scout.domain.normalization import normalize_company_name

_TRACKING_QUERY_KEYS = {"ref", "referrer", "source"}


class InvalidProfileUrlError(ValueError):
    """Raised when a professional profile URL cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class IndividualScoreInput:
    persona: str | None
    country_code: str | None
    region: str | None
    has_professional_presence: bool
    has_business_relevance: bool
    is_fictional: bool


@dataclass(frozen=True, slots=True)
class IndividualScoreResult:
    score: int
    maximum_score: int
    disposition: str
    status: str
    reason: str | None
    components: dict[str, int]


def normalize_profile_url(value: str) -> str:
    """Canonicalize an HTTP(S) professional profile without provider assumptions."""

    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise InvalidProfileUrlError("profile URL must be an absolute HTTP(S) URL")
    try:
        host = parsed.hostname.rstrip(".").casefold().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidProfileUrlError("profile URL contains an invalid hostname") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise InvalidProfileUrlError("profile URL contains an invalid port") from exc
    if port is not None and not (
        (parsed.scheme.casefold() == "http" and port == 80)
        or (parsed.scheme.casefold() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = "/" + "/".join(segment for segment in parsed.path.split("/") if segment)
    if path == "/":
        path = ""
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit(("https", host, path, query, ""))


def individual_candidate_fingerprint(
    *, provider_key: str, provider_record_id: str, normalized_profile_url: str
) -> str:
    material = "|".join((provider_key, provider_record_id, normalized_profile_url))
    return hashlib.sha256(material.encode()).hexdigest()


def profile_suppression_hash(normalized_profile_url: str) -> str:
    """Return a stable non-reversible lookup key for profile suppression."""

    return hashlib.sha256(normalized_profile_url.encode()).hexdigest()


def normalize_person_name(value: str) -> str:
    """Normalize a name for review search only; never use it as an exact identity key."""

    return normalize_company_name(value)


def development_individual_icp_definition() -> dict[str, Any]:
    """Return the fictional-only M4 development ICP, not a live collection approval."""

    return {
        "schema_version": 1,
        "algorithm_version": "individual-icp-dev-1",
        "collection_enabled": False,
        "fictional_data_only": True,
        "target_personas": [
            "business_coach",
            "consultant",
            "freelancer",
            "founder",
            "content_creator",
            "educator",
        ],
        "target_countries": ["GB"],
        "target_regions": ["England"],
        "weights": {
            "professional_presence": 35,
            "business_relevance": 35,
            "persona": 20,
            "geography": 10,
        },
        "thresholds": {"qualified": 80, "review": 60},
        "retention_days": {"unqualified": 90, "qualified_review": 180},
        "outreach": {"enabled": False, "human_approval_required": True},
    }


def score_individual(
    value: IndividualScoreInput, definition: dict[str, Any] | None = None
) -> IndividualScoreResult:
    """Score a fictional candidate while failing closed on live personal data."""

    rules = definition or development_individual_icp_definition()
    weights = rules["weights"]
    maximum = sum(int(weight) for weight in weights.values())
    components = {
        "professional_presence": (
            int(weights["professional_presence"]) if value.has_professional_presence else 0
        ),
        "business_relevance": (
            int(weights["business_relevance"]) if value.has_business_relevance else 0
        ),
        "persona": int(weights["persona"]) if value.persona in set(rules["target_personas"]) else 0,
        "geography": int(weights["geography"])
        if value.country_code in set(rules["target_countries"])
        and value.region in set(rules["target_regions"])
        else 0,
    }
    score = sum(components.values())
    if rules.get("fictional_data_only", True) and not value.is_fictional:
        return IndividualScoreResult(
            0,
            maximum,
            "disqualified",
            "rejected",
            "live_personal_data_not_approved",
            components,
        )
    if not value.has_professional_presence:
        return IndividualScoreResult(
            score,
            maximum,
            "disqualified",
            "rejected",
            "professional_presence_missing",
            components,
        )
    if not value.has_business_relevance:
        return IndividualScoreResult(
            score,
            maximum,
            "disqualified",
            "rejected",
            "business_relevance_missing",
            components,
        )
    thresholds = rules["thresholds"]
    if score >= int(thresholds["qualified"]):
        disposition, status = "qualified", "new"
    elif score >= int(thresholds["review"]):
        disposition, status = "review", "needs_review"
    else:
        disposition, status = "unqualified", "rejected"
    return IndividualScoreResult(score, maximum, disposition, status, None, components)
