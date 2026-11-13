from datetime import UTC, datetime

import pytest

from revvix_scout.providers.contracts import DiscoveredBusiness, DiscoveryQuery
from revvix_scout.providers.csv_input import CsvDiscoveryContractError, CsvInputProvider
from revvix_scout.providers.manual import ManualInputProvider

HEADER = (
    "schema_version,provider_record_id,company_name,domain,country_code,region,industry,"
    "employee_count,legal_form,company_status,source_url,observed_at\n"
)
ROW = (
    "1,manual-1,Example Accountants,accountants.example.com,gb,England,accounting,12,Ltd,active,"
    "https://example.invalid/about,2026-11-01T10:00:00Z\n"
)


def _record(record_id: str) -> DiscoveredBusiness:
    return DiscoveredBusiness(
        provider_record_id=record_id,
        company_name=f"Company {record_id}",
        domain=f"{record_id}.invalid",
        country_code="GB",
        region="England",
        industry="accounting",
        employee_count=10,
        legal_form="Ltd",
        company_status="active",
        source_url=f"https://{record_id}.invalid/about",
        observed_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def test_manual_provider_pages_operator_supplied_records_without_usage() -> None:
    provider = ManualInputProvider()
    records = (_record("one"), _record("two"), _record("three"))

    first = provider.discover(DiscoveryQuery(search_text="manual", limit=2, seed_records=records))
    second = provider.discover(
        DiscoveryQuery(
            search_text="manual", limit=2, cursor=first.next_cursor, seed_records=records
        )
    )

    assert [item.provider_record_id for item in first.candidates] == ["one", "two"]
    assert [item.provider_record_id for item in second.candidates] == ["three"]
    assert first.next_cursor == "2"
    assert second.next_cursor is None
    assert first.actual_units == provider.estimate_units(DiscoveryQuery(search_text="manual")) == 0


def test_csv_provider_validates_and_normalizes_allow_listed_rows() -> None:
    records = CsvInputProvider.parse((HEADER + ROW).encode(), max_bytes=10_000, max_rows=10)

    assert len(records) == 1
    assert records[0].provider_record_id == "manual-1"
    assert records[0].country_code == "GB"
    assert records[0].observed_at.tzinfo is not None


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("company_name\nExample\n", "missing required columns"),
        (
            HEADER.rstrip("\n") + ",private_note\n" + ROW.rstrip("\n") + ",secret\n",
            "unexpected columns",
        ),
        (HEADER + ROW + ROW, "repeats provider_record_id"),
        (HEADER, "contains no data rows"),
    ],
)
def test_csv_provider_fails_closed_on_contract_errors(content: str, message: str) -> None:
    with pytest.raises(CsvDiscoveryContractError, match=message):
        CsvInputProvider.parse(content.encode(), max_bytes=10_000, max_rows=10)
