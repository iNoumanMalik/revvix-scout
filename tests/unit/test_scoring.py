from uuid import uuid4

from revvix_scout.domain.scoring import Disposition, ScoreInput, score_business


def test_target_business_scores_100_with_evidence_on_every_component() -> None:
    evidence = {
        "industry": uuid4(),
        "employee_count": uuid4(),
        "country_code": uuid4(),
        "technology_need": uuid4(),
    }
    result = score_business(
        ScoreInput(
            industry="accounting",
            employee_count=20,
            country_code="GB",
            technology_need="manual_processes",
            excluded_reason=None,
            evidence_ids=evidence,
        )
    )
    assert result.total_score == 100
    assert result.disposition is Disposition.QUALIFIED
    assert result.missing_fields == ()
    assert {component.evidence_id for component in result.components} == set(evidence.values())


def test_missing_values_score_zero_and_are_explained() -> None:
    result = score_business(
        ScoreInput(
            industry=None,
            employee_count=None,
            country_code=None,
            technology_need=None,
            excluded_reason=None,
            evidence_ids={},
        )
    )
    assert result.total_score == 0
    assert result.disposition is Disposition.UNQUALIFIED
    assert result.missing_fields == (
        "industry",
        "employee_count",
        "country_code",
        "technology_need",
    )
    assert all(component.result == "missing" for component in result.components)


def test_explicit_exclusion_is_a_hard_disqualifier() -> None:
    result = score_business(
        ScoreInput(
            industry="accounting",
            employee_count=50,
            country_code="GB",
            technology_need="integration_gap",
            excluded_reason="Existing Revvix customer",
            evidence_ids={},
        )
    )
    assert result.total_score == 0
    assert result.disposition is Disposition.DISQUALIFIED
