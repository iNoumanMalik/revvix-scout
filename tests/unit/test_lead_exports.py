import csv
import io
from datetime import UTC, datetime
from uuid import UUID

import pytest

from revvix_scout.application import leads
from revvix_scout.application.contracts import LeadListItem, LeadPage
from revvix_scout.application.leads import CsvExportProgress, LeadFilters, stream_leads_csv
from revvix_scout.config import Settings


def _lead(index: int, company_name: str) -> LeadListItem:
    return LeadListItem(
        id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        company_id=UUID(f"00000000-0000-4000-8001-{index:012d}"),
        company_name=company_name,
        normalized_domain=f"fixture-{index}.invalid",
        country_code="GB",
        industry="accounting",
        employee_count=10,
        match_status="resolved",
        disposition="qualified",
        score=90,
        created_at=datetime(2026, 11, 13, 12, index, tzinfo=UTC),
    )


def test_csv_stream_uses_bounded_keyset_pages_and_neutralizes_formulas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str | None]] = []
    pages = iter(
        (
            LeadPage(
                items=[_lead(1, "=FORMULA()"), _lead(2, "Fixture Two")],
                next_cursor="cursor-2",
            ),
            LeadPage(items=[_lead(3, "Fixture Three")], next_cursor=None),
        )
    )

    def fake_list_leads(**kwargs: object) -> LeadPage:
        calls.append((int(kwargs["limit"]), kwargs["cursor"]))  # type: ignore[arg-type]
        return next(pages)

    monkeypatch.setattr(leads, "list_leads", fake_list_leads)
    progress = CsvExportProgress()
    content = "".join(
        stream_leads_csv(
            session=object(),  # type: ignore[arg-type]
            settings=Settings(),
            filters=LeadFilters(),
            progress=progress,
            batch_size=2,
        )
    )

    rows = list(csv.DictReader(io.StringIO(content)))
    assert calls == [(2, None), (2, "cursor-2")]
    assert progress.row_count == 3
    assert len(rows) == 3
    assert rows[0]["company_name"] == "'=FORMULA()"


@pytest.mark.parametrize("batch_size", [0, 2_001])
def test_csv_stream_rejects_unbounded_batch_sizes(batch_size: int) -> None:
    progress = CsvExportProgress()
    with pytest.raises(ValueError, match="batch_size"):
        next(
            stream_leads_csv(
                session=object(),  # type: ignore[arg-type]
                settings=Settings(),
                filters=LeadFilters(),
                progress=progress,
                batch_size=batch_size,
            )
        )
