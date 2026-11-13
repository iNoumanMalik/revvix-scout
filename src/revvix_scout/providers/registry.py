"""Application provider composition without vendor SDK leakage."""

from revvix_scout.providers.contracts import ProviderRegistry
from revvix_scout.providers.csv_input import CsvInputProvider
from revvix_scout.providers.fixture import FictionalAccountingProvider
from revvix_scout.providers.individual_contracts import IndividualProviderRegistry
from revvix_scout.providers.individual_fixture import FictionalProfessionalProvider
from revvix_scout.providers.manual import ManualInputProvider


def create_provider_registry() -> ProviderRegistry:
    """Return the approved provider-free adapters for this application build."""

    return ProviderRegistry(
        (FictionalAccountingProvider(), ManualInputProvider(), CsvInputProvider())
    )


def create_individual_provider_registry() -> IndividualProviderRegistry:
    """Return the fictional-only M4 individual discovery adapter registry."""

    return IndividualProviderRegistry((FictionalProfessionalProvider(),))
