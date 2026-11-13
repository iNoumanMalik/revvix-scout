"""Strict CSV adapter that retains only allow-listed, validated candidate fields."""

import csv
import io
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, Field, ValidationError, field_validator

from revvix_scout.providers.contracts import DiscoveredBusiness, DiscoveryPage, DiscoveryQuery

CSV_COLUMNS = {
    "schema_version",
    "provider_record_id",
    "company_name",
    "domain",
    "country_code",
    "region",
    "industry",
    "employee_count",
    "legal_form",
    "company_status",
    "source_url",
    "observed_at",
}


class CsvDiscoveryContractError(ValueError):
    pass


class _CsvRow(BaseModel):
    schema_version: Literal["1"]
    provider_record_id: Annotated[str, Field(min_length=1, max_length=160)]
    company_name: Annotated[str, Field(min_length=1, max_length=240)]
    domain: Annotated[str | None, Field(max_length=500)] = None
    country_code: Annotated[str | None, Field(min_length=2, max_length=2)] = None
    region: Annotated[str | None, Field(max_length=120)] = None
    industry: Annotated[str | None, Field(max_length=80)] = None
    employee_count: Annotated[int | None, Field(ge=0, le=1_000_000)] = None
    legal_form: Annotated[str | None, Field(max_length=80)] = None
    company_status: Annotated[str | None, Field(max_length=40)] = None
    source_url: AnyHttpUrl
    observed_at: AwareDatetime

    @field_validator(
        "domain",
        "country_code",
        "region",
        "industry",
        "employee_count",
        "legal_form",
        "company_status",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "provider_record_id",
        "company_name",
        "domain",
        "region",
        "industry",
        "legal_form",
        "company_status",
    )
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("country_code")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class CsvInputProvider:
    key = "csv_input"
    is_live = False

    def estimate_units(self, query: DiscoveryQuery) -> int:
        return 0

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        offset = int(query.cursor or "0")
        end = min(offset + query.limit, len(query.seed_records))
        next_cursor = str(end) if end < len(query.seed_records) else None
        return DiscoveryPage(query.seed_records[offset:end], next_cursor, 0)

    @staticmethod
    def parse(content: bytes, *, max_bytes: int, max_rows: int) -> tuple[DiscoveredBusiness, ...]:
        if not content:
            raise CsvDiscoveryContractError("CSV file is empty")
        if len(content) > max_bytes:
            raise CsvDiscoveryContractError(f"CSV exceeds the {max_bytes}-byte limit")
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CsvDiscoveryContractError("CSV must be UTF-8 encoded") from exc
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        if reader.fieldnames is None:
            raise CsvDiscoveryContractError("CSV header is missing")
        headers = [header.strip() for header in reader.fieldnames]
        if len(headers) != len(set(headers)):
            raise CsvDiscoveryContractError("CSV header contains duplicate columns")
        missing = sorted(CSV_COLUMNS - set(headers))
        if missing:
            raise CsvDiscoveryContractError(
                f"CSV is missing required columns: {', '.join(missing)}"
            )
        unexpected = sorted(set(headers) - CSV_COLUMNS)
        if unexpected:
            raise CsvDiscoveryContractError(
                f"CSV contains unexpected columns: {', '.join(unexpected)}"
            )

        records: list[DiscoveredBusiness] = []
        seen_ids: set[str] = set()
        for row_number, raw in enumerate(reader, start=2):
            if None in raw:
                raise CsvDiscoveryContractError(
                    f"Row {row_number} contains more values than the header"
                )
            if len(records) >= max_rows:
                raise CsvDiscoveryContractError(f"CSV exceeds the {max_rows}-row limit")
            try:
                row = _CsvRow.model_validate({key.strip(): value for key, value in raw.items()})
            except ValidationError as exc:
                message = exc.errors(include_url=False, include_input=False)[0]
                location = ".".join(str(item) for item in message["loc"])
                raise CsvDiscoveryContractError(
                    f"Row {row_number} {location}: {message['msg']}"
                ) from exc
            if row.provider_record_id in seen_ids:
                raise CsvDiscoveryContractError(
                    f"Row {row_number} repeats provider_record_id {row.provider_record_id!r}"
                )
            seen_ids.add(row.provider_record_id)
            records.append(_to_business(row))
        if not records:
            raise CsvDiscoveryContractError("CSV contains no data rows")
        return tuple(records)


def _to_business(row: _CsvRow) -> DiscoveredBusiness:
    observed_at = row.observed_at
    assert isinstance(observed_at, datetime)
    return DiscoveredBusiness(
        provider_record_id=row.provider_record_id,
        company_name=row.company_name,
        domain=row.domain,
        country_code=row.country_code,
        region=row.region,
        industry=row.industry,
        employee_count=row.employee_count,
        legal_form=row.legal_form,
        company_status=row.company_status,
        source_url=str(row.source_url),
        observed_at=observed_at,
    )
