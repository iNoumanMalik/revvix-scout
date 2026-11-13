"""Boundary schemas for CSV import and API responses."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, Field, field_validator

Industry = Literal[
    "accounting",
    "bookkeeping",
    "professional_services",
    "software",
    "healthcare",
    "legal",
    "education",
    "retail",
    "manufacturing",
    "real_estate",
    "hospitality",
    "other",
]
TechnologyNeed = Literal[
    "manual_processes",
    "legacy_systems",
    "integration_gap",
    "data_ai_opportunity",
    "cloud_it_gap",
    "digital_experience",
]


class BusinessImportRow(BaseModel):
    """Version 1 contract for one provider-free business import row."""

    schema_version: Literal["1"]
    source_record_id: Annotated[str, Field(min_length=1, max_length=160)]
    company_name: Annotated[str, Field(min_length=1, max_length=240)]
    domain: Annotated[str | None, Field(max_length=500)] = None
    country_code: Annotated[str | None, Field(min_length=2, max_length=2)] = None
    employee_count: Annotated[int | None, Field(ge=0, le=1_000_000)] = None
    industry: Industry | None = None
    technology_need: TechnologyNeed | None = None
    excluded_reason: Annotated[str | None, Field(max_length=500)] = None
    source_url: AnyHttpUrl
    observed_at: AwareDatetime

    @field_validator(
        "domain",
        "country_code",
        "industry",
        "technology_need",
        "excluded_reason",
        "employee_count",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("source_record_id", "company_name", "domain", "excluded_reason")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class ImportRowError(BaseModel):
    row_number: int
    source_record_id: str | None
    code: str
    message: str


class ImportSummary(BaseModel):
    import_job_id: UUID
    status: str
    total_rows: int
    succeeded_rows: int
    failed_rows: int
    duplicate_rows: int
    idempotent_replay: bool
    errors: list[ImportRowError]


class ScoreComponentView(BaseModel):
    rule_key: str
    points: int
    maximum_points: int
    result: str
    explanation: str
    evidence_claim_ids: list[UUID]


class ScoreView(BaseModel):
    id: UUID
    icp_version_id: UUID
    algorithm_version: str
    total_score: int
    maximum_score: int
    normalized_score: float
    disposition: str
    missing_fields: list[str]
    scored_at: datetime
    components: list[ScoreComponentView] = Field(default_factory=list)


class EvidenceView(BaseModel):
    id: UUID
    claim_type: str
    value: object
    classification: str
    confidence: float
    verification_status: str
    source_url: str
    source_record_id: str
    observed_at: datetime
    retrieved_at: datetime


class LeadListItem(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    normalized_domain: str | None
    country_code: str | None
    industry: str | None
    employee_count: int | None
    match_status: str
    disposition: str
    score: int
    created_at: datetime


class LeadPage(BaseModel):
    items: list[LeadListItem]
    next_cursor: str | None


class LeadDetail(LeadListItem):
    icp_version_id: UUID
    stage: str
    score_detail: ScoreView
    evidence: list[EvidenceView]


class DiscoveryRunRequest(BaseModel):
    provider_key: str = "fictional_accounting_directory"
    search_text: Annotated[str, Field(min_length=1, max_length=300)] = "accounting firms"
    country_code: Annotated[str, Field(min_length=2, max_length=2)] = "GB"
    region: Annotated[str, Field(min_length=1, max_length=120)] = "England"
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    cursor: Annotated[str | None, Field(max_length=500)] = None
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class ManualDiscoveryRecord(BaseModel):
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

    @field_validator("country_code")
    @classmethod
    def normalize_manual_country(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class ManualDiscoveryRequest(BaseModel):
    records: Annotated[list[ManualDiscoveryRecord], Field(min_length=1, max_length=5_000)]
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    cursor: Annotated[str | None, Field(max_length=500)] = None
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class DiscoveryCandidateView(BaseModel):
    id: UUID
    provider_record_id: str
    company_name: str
    normalized_domain: str | None
    country_code: str | None
    region: str | None
    industry: str | None
    employee_count: int | None
    legal_form: str | None
    company_status: str | None
    source_url: str
    observed_at: datetime
    status: str
    rejection_reason: str | None


class DiscoveryRunView(BaseModel):
    id: UUID
    provider_key: str
    status: str
    next_cursor: str | None
    discovered_count: int
    duplicate_count: int
    rejected_count: int
    error_code: str | None
    error_message: str | None
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    candidates: list[DiscoveryCandidateView] = Field(default_factory=list)
