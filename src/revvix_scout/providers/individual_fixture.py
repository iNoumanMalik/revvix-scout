"""Fictional individual discovery adapter for local M4 development."""

from datetime import UTC, datetime

from revvix_scout.providers.individual_contracts import (
    DiscoveredProfessional,
    IndividualDiscoveryPage,
    IndividualDiscoveryQuery,
)


class FictionalProfessionalProvider:
    key = "fictional_professional_directory"
    is_live = False

    _records = (
        DiscoveredProfessional(
            provider_record_id="fictional-person-001",
            display_name="Avery North",
            professional_profile_url="https://professionals.invalid/avery-north",
            persona="consultant",
            country_code="GB",
            region="England",
            service_summary="Fictional operations consultancy.",
            has_professional_presence=True,
            has_business_relevance=True,
            source_url="https://fixtures.invalid/professionals/avery-north",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
            is_fictional=True,
        ),
        DiscoveredProfessional(
            provider_record_id="fictional-person-002",
            display_name="Jordan Reed",
            professional_profile_url="https://professionals.invalid/jordan-reed-creator",
            persona="content_creator",
            country_code="GB",
            region="England",
            service_summary="Fictional educational content business.",
            has_professional_presence=True,
            has_business_relevance=True,
            source_url="https://fixtures.invalid/professionals/jordan-reed-creator",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
            is_fictional=True,
        ),
        DiscoveredProfessional(
            provider_record_id="fictional-person-003",
            display_name="Jordan Reed",
            professional_profile_url="https://professionals.invalid/jordan-reed-educator",
            persona="educator",
            country_code="GB",
            region="England",
            service_summary="Separate fictional educator with the same display name.",
            has_professional_presence=True,
            has_business_relevance=True,
            source_url="https://fixtures.invalid/professionals/jordan-reed-educator",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
            is_fictional=True,
        ),
        DiscoveredProfessional(
            provider_record_id="fictional-person-004",
            display_name="Morgan Vale",
            professional_profile_url="https://professionals.invalid/morgan-vale-private",
            persona="consultant",
            country_code="GB",
            region="England",
            service_summary=None,
            has_professional_presence=False,
            has_business_relevance=False,
            source_url="https://fixtures.invalid/professionals/morgan-vale-private",
            observed_at=datetime(2026, 11, 1, tzinfo=UTC),
            is_fictional=True,
        ),
    )

    def estimate_units(self, query: IndividualDiscoveryQuery) -> int:
        return 1

    def discover(self, query: IndividualDiscoveryQuery) -> IndividualDiscoveryPage:
        offset = int(query.cursor or "0")
        end = min(offset + query.limit, len(self._records))
        return IndividualDiscoveryPage(
            candidates=self._records[offset:end],
            next_cursor=str(end) if end < len(self._records) else None,
            actual_units=1,
        )
