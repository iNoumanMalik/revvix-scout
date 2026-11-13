"""Fictional, metadata-only M6 enrichment adapter."""

import hashlib
from datetime import UTC, datetime, timedelta

from revvix_scout.providers.enrichment_contracts import (
    EnrichedClaim,
    EnrichmentQuery,
    EnrichmentResult,
    EnrichmentSource,
)


class FictionalFirmographicEnrichmentProvider:
    key = "fictional_firmographic_enrichment"
    is_live = False

    def estimate_units(self, query: EnrichmentQuery) -> int:
        return 1

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult:
        if query.pipeline_kind != "business" or query.canonical_domain != "example.com":
            return _empty_result(query.canonical_domain or "unknown.invalid")
        retrieved_at = datetime(2026, 11, 13, 12, tzinfo=UTC)
        source_url = "https://fixtures.invalid/enrichment/example-accounting"
        available = {
            "employee_count": EnrichedClaim(
                "employee_count",
                14,
                "14",
                "provider_asserted",
                0.9,
                "source_asserted",
                datetime(2026, 11, 1, tzinfo=UTC),
                retrieved_at + timedelta(days=30),
            ),
            "industry": EnrichedClaim(
                "industry",
                "accounting",
                "accounting",
                "provider_asserted",
                0.95,
                "source_asserted",
                datetime(2026, 11, 1, tzinfo=UTC),
                retrieved_at + timedelta(days=90),
            ),
        }
        claims = tuple(available[field] for field in query.requested_fields if field in available)
        return EnrichmentResult(_source(source_url, retrieved_at), claims, actual_units=1)


def _empty_result(domain: str) -> EnrichmentResult:
    retrieved_at = datetime(2026, 11, 13, 12, tzinfo=UTC)
    source_url = f"https://fixtures.invalid/enrichment/{domain}"
    return EnrichmentResult(
        _source(source_url, retrieved_at), (), actual_units=1, stop_reason="not_found"
    )


def _source(url: str, retrieved_at: datetime) -> EnrichmentSource:
    return EnrichmentSource(
        provider_record_id=hashlib.sha256(url.encode()).hexdigest()[:24],
        canonical_url=url,
        content_hash=hashlib.sha256(f"metadata:{url}".encode()).hexdigest(),
        retrieved_at=retrieved_at,
        license_policy={"fixture": True, "raw_content_retained": False},
        cache_expires_at=retrieved_at + timedelta(days=14),
        metadata_only=True,
    )
