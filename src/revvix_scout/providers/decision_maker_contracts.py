"""Vendor-neutral M5 decision-maker discovery contracts without contact fields."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DecisionMakerQuery:
    company_id: UUID
    company_name: str
    normalized_domain: str
    target_roles: tuple[str, ...]
    limit: int = 25


@dataclass(frozen=True, slots=True)
class DiscoveredDecisionMaker:
    provider_record_id: str
    display_name: str
    professional_profile_url: str
    title: str
    seniority: str | None
    department: str | None
    is_current: bool
    source_url: str
    observed_at: datetime
    is_fictional: bool


@dataclass(frozen=True, slots=True)
class DecisionMakerPage:
    candidates: tuple[DiscoveredDecisionMaker, ...]
    actual_units: int


class DecisionMakerProvider(Protocol):
    key: str
    is_live: bool

    def estimate_units(self, query: DecisionMakerQuery) -> int: ...

    def discover(self, query: DecisionMakerQuery) -> DecisionMakerPage: ...


class DecisionMakerProviderRegistry:
    def __init__(self, providers: tuple[DecisionMakerProvider, ...]) -> None:
        self._providers = {provider.key: provider for provider in providers}
        if len(self._providers) != len(providers):
            raise ValueError("Duplicate decision-maker provider key")

    def get(self, key: str) -> DecisionMakerProvider:
        try:
            return self._providers[key]
        except KeyError as exc:
            raise DecisionMakerProviderNotRegisteredError(key) from exc


class DecisionMakerProviderNotRegisteredError(LookupError):
    pass
