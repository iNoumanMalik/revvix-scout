"""Vendor-neutral discovery contracts. Provider SDK types must not cross this boundary."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DiscoveryQuery:
    search_text: str
    country_code: str = "GB"
    region: str = "England"
    limit: int = 25
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredBusiness:
    provider_record_id: str
    company_name: str
    domain: str | None
    country_code: str | None
    region: str | None
    industry: str | None
    employee_count: int | None
    legal_form: str | None
    company_status: str | None
    source_url: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    candidates: tuple[DiscoveredBusiness, ...]
    next_cursor: str | None
    actual_units: int


class DiscoveryProvider(Protocol):
    key: str
    is_live: bool

    def estimate_units(self, query: DiscoveryQuery) -> int:
        """Return units which must be reserved before execution."""

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        """Return one bounded page of candidates."""


class ProviderRegistry:
    def __init__(self, providers: tuple[DiscoveryProvider, ...]) -> None:
        self._providers: dict[str, DiscoveryProvider] = {}
        for provider in providers:
            if provider.key in self._providers:
                raise ValueError(f"Duplicate provider key: {provider.key}")
            self._providers[provider.key] = provider

    def get(self, provider_key: str) -> DiscoveryProvider:
        try:
            return self._providers[provider_key]
        except KeyError as exc:
            raise ProviderNotRegisteredError(provider_key) from exc


class ProviderNotRegisteredError(LookupError):
    pass


class ProviderExecutionError(RuntimeError):
    """Stable provider failure with retry classification."""

    def __init__(self, category: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
