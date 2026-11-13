"""Vendor-neutral M6 enrichment contracts with provenance and no SDK types."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EnrichmentQuery:
    lead_id: UUID
    pipeline_kind: str
    company_id: UUID | None
    person_id: UUID | None
    requested_fields: tuple[str, ...]
    canonical_domain: str | None = None
    canonical_profile_url: str | None = None


@dataclass(frozen=True, slots=True)
class EnrichedClaim:
    claim_type: str
    value: object
    normalized_value: str
    classification: str
    confidence: float
    verification_status: str
    observed_at: datetime
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class EnrichmentSource:
    provider_record_id: str
    canonical_url: str
    content_hash: str
    retrieved_at: datetime
    license_policy: dict[str, object]
    cache_expires_at: datetime | None
    metadata_only: bool


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    source: EnrichmentSource
    claims: tuple[EnrichedClaim, ...]
    actual_units: int
    stop_reason: str | None = None


class EnrichmentProvider(Protocol):
    key: str
    is_live: bool

    def estimate_units(self, query: EnrichmentQuery) -> int: ...

    def enrich(self, query: EnrichmentQuery) -> EnrichmentResult: ...


class EnrichmentProviderRegistry:
    def __init__(self, providers: tuple[EnrichmentProvider, ...]) -> None:
        self._providers = {provider.key: provider for provider in providers}
        if len(self._providers) != len(providers):
            raise ValueError("Duplicate enrichment provider key")

    def get(self, key: str) -> EnrichmentProvider:
        try:
            return self._providers[key]
        except KeyError as exc:
            raise EnrichmentProviderNotRegisteredError(key) from exc


class EnrichmentProviderNotRegisteredError(LookupError):
    pass
