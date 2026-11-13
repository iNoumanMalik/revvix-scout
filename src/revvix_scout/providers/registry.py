"""Application provider composition without vendor SDK leakage."""

from revvix_scout.providers.contracts import ProviderRegistry
from revvix_scout.providers.csv_input import CsvInputProvider
from revvix_scout.providers.decision_maker_contracts import DecisionMakerProviderRegistry
from revvix_scout.providers.decision_maker_fixture import FictionalDecisionMakerProvider
from revvix_scout.providers.enrichment_contracts import EnrichmentProviderRegistry
from revvix_scout.providers.enrichment_fixture import FictionalFirmographicEnrichmentProvider
from revvix_scout.providers.fixture import FictionalAccountingProvider
from revvix_scout.providers.individual_contracts import IndividualProviderRegistry
from revvix_scout.providers.individual_fixture import FictionalProfessionalProvider
from revvix_scout.providers.manual import ManualInputProvider
from revvix_scout.providers.opportunity_contracts import OpportunityAnalysisProviderRegistry
from revvix_scout.providers.opportunity_fixture import FictionalOpportunityAnalysisProvider


def create_provider_registry() -> ProviderRegistry:
    """Return the approved provider-free adapters for this application build."""

    return ProviderRegistry(
        (FictionalAccountingProvider(), ManualInputProvider(), CsvInputProvider())
    )


def create_individual_provider_registry() -> IndividualProviderRegistry:
    """Return the fictional-only M4 individual discovery adapter registry."""

    return IndividualProviderRegistry((FictionalProfessionalProvider(),))


def create_decision_maker_provider_registry() -> DecisionMakerProviderRegistry:
    """Return the fictional-only M5 decision-maker registry."""

    return DecisionMakerProviderRegistry((FictionalDecisionMakerProvider(),))


def create_enrichment_provider_registry() -> EnrichmentProviderRegistry:
    """Return the fictional, metadata-only M6 enrichment registry."""

    return EnrichmentProviderRegistry((FictionalFirmographicEnrichmentProvider(),))


def create_opportunity_analysis_provider_registry() -> OpportunityAnalysisProviderRegistry:
    """Return the no-tools, deterministic M7 fixture registry."""

    return OpportunityAnalysisProviderRegistry((FictionalOpportunityAnalysisProvider(),))
