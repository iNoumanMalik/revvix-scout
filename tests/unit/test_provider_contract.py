from revvix_scout.providers.contracts import (
    DiscoveryQuery,
    ProviderNotRegisteredError,
    ProviderRegistry,
)
from revvix_scout.providers.fixture import FictionalAccountingProvider


def test_fixture_provider_contract_supports_cursor_pages() -> None:
    provider = FictionalAccountingProvider()
    first = provider.discover(DiscoveryQuery(search_text="accountants", limit=2))
    assert len(first.candidates) == 2
    assert first.next_cursor == "2"
    assert first.actual_units == provider.estimate_units(DiscoveryQuery(search_text="accountants"))

    second = provider.discover(
        DiscoveryQuery(search_text="accountants", limit=2, cursor=first.next_cursor)
    )
    assert len(second.candidates) == 1
    assert second.next_cursor is None
    assert not (
        {item.provider_record_id for item in first.candidates}
        & {item.provider_record_id for item in second.candidates}
    )


def test_registry_rejects_unknown_and_duplicate_provider_keys() -> None:
    registry = ProviderRegistry((FictionalAccountingProvider(),))
    try:
        registry.get("missing")
    except ProviderNotRegisteredError:
        pass
    else:
        raise AssertionError("unknown provider must fail closed")

    try:
        ProviderRegistry((FictionalAccountingProvider(), FictionalAccountingProvider()))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate provider keys must be rejected")
