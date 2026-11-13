"""Vendor-neutral M7 structured-analysis contracts without provider SDK types."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from revvix_scout.domain.opportunities import AnalysisEvidence, OpportunityAnalysisDraft


@dataclass(frozen=True, slots=True)
class OpportunityAnalysisQuery:
    lead_id: UUID
    pipeline_kind: str
    prompt_key: str
    prompt_version: int
    output_schema_version: int
    taxonomy_version: int
    allowed_categories: tuple[str, ...]
    evidence: tuple[AnalysisEvidence, ...]


@dataclass(frozen=True, slots=True)
class OpportunityAnalysisResult:
    analysis: OpportunityAnalysisDraft
    model_name: str
    model_version: str
    prompt_tokens: int
    completion_tokens: int
    actual_units: int


class OpportunityAnalysisProvider(Protocol):
    key: str
    is_live: bool
    supports_tools: bool

    def estimate_units(self, query: OpportunityAnalysisQuery) -> int: ...

    def analyze(self, query: OpportunityAnalysisQuery) -> OpportunityAnalysisResult: ...


class OpportunityAnalysisProviderRegistry:
    def __init__(self, providers: tuple[OpportunityAnalysisProvider, ...]) -> None:
        self._providers = {provider.key: provider for provider in providers}
        if len(self._providers) != len(providers):
            raise ValueError("Duplicate opportunity-analysis provider key")

    def get(self, key: str) -> OpportunityAnalysisProvider:
        try:
            return self._providers[key]
        except KeyError as exc:
            raise OpportunityAnalysisProviderNotRegisteredError(key) from exc


class OpportunityAnalysisProviderNotRegisteredError(LookupError):
    pass
