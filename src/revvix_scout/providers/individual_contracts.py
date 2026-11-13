"""Vendor-neutral individual discovery contracts with no contact-data fields."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IndividualDiscoveryQuery:
    search_text: str
    country_code: str = "GB"
    region: str = "England"
    limit: int = 25
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredProfessional:
    provider_record_id: str
    display_name: str
    professional_profile_url: str
    persona: str | None
    country_code: str | None
    region: str | None
    service_summary: str | None
    has_professional_presence: bool
    has_business_relevance: bool
    source_url: str
    observed_at: datetime
    is_fictional: bool


@dataclass(frozen=True, slots=True)
class IndividualDiscoveryPage:
    candidates: tuple[DiscoveredProfessional, ...]
    next_cursor: str | None
    actual_units: int


class IndividualDiscoveryProvider(Protocol):
    key: str
    is_live: bool

    def estimate_units(self, query: IndividualDiscoveryQuery) -> int: ...

    def discover(self, query: IndividualDiscoveryQuery) -> IndividualDiscoveryPage: ...


class IndividualProviderRegistry:
    def __init__(self, providers: tuple[IndividualDiscoveryProvider, ...]) -> None:
        self._providers: dict[str, IndividualDiscoveryProvider] = {}
        for provider in providers:
            if provider.key in self._providers:
                raise ValueError(f"Duplicate individual provider key: {provider.key}")
            self._providers[provider.key] = provider

    def get(self, provider_key: str) -> IndividualDiscoveryProvider:
        try:
            return self._providers[provider_key]
        except KeyError as exc:
            raise IndividualProviderNotRegisteredError(provider_key) from exc


class IndividualProviderNotRegisteredError(LookupError):
    pass
