import pytest

from revvix_scout.domain.individuals import (
    IndividualScoreInput,
    InvalidProfileUrlError,
    individual_candidate_fingerprint,
    normalize_person_name,
    normalize_profile_url,
    profile_suppression_hash,
    score_individual,
)
from revvix_scout.providers.individual_contracts import IndividualDiscoveryQuery
from revvix_scout.providers.individual_fixture import FictionalProfessionalProvider


def test_profile_url_normalization_removes_tracking_but_preserves_identity_query() -> None:
    assert (
        normalize_profile_url(
            "HTTP://Professionals.Invalid:80/Avery-North/?utm_source=test&profile=42#bio"
        )
        == "https://professionals.invalid/Avery-North?profile=42"
    )


@pytest.mark.parametrize("value", ["", "professionals.invalid/person", "ftp://example.com/p"])
def test_profile_url_normalization_rejects_non_http_absolute_urls(value: str) -> None:
    with pytest.raises(InvalidProfileUrlError):
        normalize_profile_url(value)


def test_names_are_review_keys_not_identity_keys() -> None:
    first_url = normalize_profile_url("https://professionals.invalid/jordan-one")
    second_url = normalize_profile_url("https://professionals.invalid/jordan-two")
    assert normalize_person_name("Jordan Reed") == normalize_person_name(" JORDAN  REED ")
    assert individual_candidate_fingerprint(
        provider_key="fixture",
        provider_record_id="one",
        normalized_profile_url=first_url,
    ) != individual_candidate_fingerprint(
        provider_key="fixture",
        provider_record_id="two",
        normalized_profile_url=second_url,
    )


def test_profile_suppression_uses_stable_non_plaintext_key() -> None:
    normalized = normalize_profile_url("https://professionals.invalid/avery-north")
    value_hash = profile_suppression_hash(normalized)
    assert len(value_hash) == 64
    assert value_hash == profile_suppression_hash(normalized)
    assert "avery" not in value_hash


def test_fictional_individual_scores_deterministically() -> None:
    result = score_individual(
        IndividualScoreInput(
            persona="consultant",
            country_code="GB",
            region="England",
            has_professional_presence=True,
            has_business_relevance=True,
            is_fictional=True,
        )
    )
    assert (result.score, result.maximum_score) == (100, 100)
    assert (result.disposition, result.status, result.reason) == ("qualified", "new", None)


def test_nonfictional_candidate_fails_closed_even_when_other_rules_match() -> None:
    result = score_individual(
        IndividualScoreInput(
            persona="consultant",
            country_code="GB",
            region="England",
            has_professional_presence=True,
            has_business_relevance=True,
            is_fictional=False,
        )
    )
    assert result.score == 0
    assert result.disposition == "disqualified"
    assert result.reason == "live_personal_data_not_approved"


def test_missing_professional_presence_is_rejected() -> None:
    result = score_individual(
        IndividualScoreInput(
            persona="consultant",
            country_code="GB",
            region="England",
            has_professional_presence=False,
            has_business_relevance=False,
            is_fictional=True,
        )
    )
    assert result.status == "rejected"
    assert result.reason == "professional_presence_missing"


def test_fictional_provider_paginates_same_name_people_as_distinct_records() -> None:
    provider = FictionalProfessionalProvider()
    first = provider.discover(IndividualDiscoveryQuery(search_text="professionals", limit=2))
    second = provider.discover(
        IndividualDiscoveryQuery(search_text="professionals", limit=2, cursor=first.next_cursor)
    )
    records = first.candidates + second.candidates
    jordans = [record for record in records if record.display_name == "Jordan Reed"]

    assert len(records) == 4
    assert len(jordans) == 2
    assert jordans[0].professional_profile_url != jordans[1].professional_profile_url
    assert first.next_cursor == "2"
    assert second.next_cursor is None
    assert first.actual_units == provider.estimate_units(
        IndividualDiscoveryQuery(search_text="professionals")
    )
