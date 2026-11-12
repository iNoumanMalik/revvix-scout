from uuid import uuid4

import pytest

from revvix_scout.domain.normalization import (
    InvalidDomainError,
    fallback_company_fingerprint,
    normalize_company_name,
    normalize_domain,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://WWW.Example.CO.UK/path?q=1", "example.co.uk"),
        ("subdomain.example.com", "example.com"),
        ("https://bücher.de/catalog", "xn--bcher-kva.de"),
        ("  EXAMPLE.COM.  ", "example.com"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_domain(raw: str | None, expected: str | None) -> None:
    assert normalize_domain(raw) == expected


def test_rejects_non_registrable_domain() -> None:
    with pytest.raises(InvalidDomainError):
        normalize_domain("localhost")


def test_name_normalization_is_unicode_aware_and_deterministic() -> None:
    assert normalize_company_name("  ACME™   Consulting, LLC  ") == "acmetm consulting llc"


def test_no_domain_fingerprint_keeps_distinct_source_records_separate() -> None:
    normalized_name = normalize_company_name("Same Name LLC")
    first = fallback_company_fingerprint(
        normalized_name=normalized_name,
        country_code="US",
        source_record_id=str(uuid4()),
    )
    second = fallback_company_fingerprint(
        normalized_name=normalized_name,
        country_code="US",
        source_record_id=str(uuid4()),
    )
    assert first != second
