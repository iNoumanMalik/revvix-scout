"""Deterministic fictional provider used by tests and local development."""

from datetime import UTC, datetime

from revvix_scout.providers.contracts import (
    DiscoveredBusiness,
    DiscoveryPage,
    DiscoveryQuery,
)


class FictionalAccountingProvider:
    key = "fictional_accounting_directory"
    is_live = False

    _records = (
        DiscoveredBusiness(
            provider_record_id="fictional-001",
            company_name="Northstar Ledger Ltd",
            domain="northstar-ledger.example.com",
            country_code="GB",
            region="England",
            industry="accounting",
            employee_count=14,
            legal_form="ltd",
            company_status="active",
            source_url="https://fixtures.invalid/northstar-ledger",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
        ),
        DiscoveredBusiness(
            provider_record_id="fictional-002",
            company_name="Oak & Quill Bookkeeping LLP",
            domain="oak-quill.example.org",
            country_code="GB",
            region="England",
            industry="bookkeeping",
            employee_count=8,
            legal_form="llp",
            company_status="active",
            source_url="https://fixtures.invalid/oak-quill",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
        ),
        DiscoveredBusiness(
            provider_record_id="fictional-003",
            company_name="Dormant Numbers Ltd",
            domain="dormant-numbers.example.net",
            country_code="GB",
            region="England",
            industry="accounting",
            employee_count=6,
            legal_form="ltd",
            company_status="dormant",
            source_url="https://fixtures.invalid/dormant-numbers",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
        ),
    )

    def estimate_units(self, query: DiscoveryQuery) -> int:
        return 1

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        offset = int(query.cursor or "0")
        end = min(offset + query.limit, len(self._records))
        candidates = self._records[offset:end]
        next_cursor = str(end) if end < len(self._records) else None
        return DiscoveryPage(candidates=candidates, next_cursor=next_cursor, actual_units=1)
