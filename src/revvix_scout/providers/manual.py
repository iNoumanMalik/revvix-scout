"""Provider-free adapter for operator-supplied, validated business records."""

from revvix_scout.providers.contracts import DiscoveryPage, DiscoveryQuery


class ManualInputProvider:
    key = "manual_input"
    is_live = False

    def estimate_units(self, query: DiscoveryQuery) -> int:
        return 0

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        offset = int(query.cursor or "0")
        end = min(offset + query.limit, len(query.seed_records))
        next_cursor = str(end) if end < len(query.seed_records) else None
        return DiscoveryPage(
            candidates=query.seed_records[offset:end],
            next_cursor=next_cursor,
            actual_units=0,
        )
