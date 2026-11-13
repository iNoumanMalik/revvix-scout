"""Boundary schemas for CSV import and API responses."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, Field, field_validator, model_validator

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


class SessionView(BaseModel):
    user_id: UUID
    workspace_id: UUID
    role: str
    display_name: str
    auth_mode: Literal["development", "supabase"]
    capabilities: list[str]


class ReviewQueueItem(BaseModel):
    """One operator-review item with only allow-listed decision context."""

    id: UUID
    kind: Literal[
        "business_lead",
        "individual_candidate",
        "entity_match",
        "opportunity_hypothesis",
    ]
    title: str
    summary: str
    status: str
    created_at: datetime
    primary_subject_id: UUID
    secondary_subject_id: UUID | None = None
    lead_id: UUID | None = None
    source_url: str | None = None
    score: float | None = None
    possible_match_person_id: UUID | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueItem]
    counts: dict[str, int]


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


class IndividualDiscoveryRunRequest(BaseModel):
    """Fictional-only M4 discovery request; no contact fields are accepted."""

    provider_key: str = "fictional_professional_directory"
    search_text: Annotated[str, Field(min_length=1, max_length=300)] = "fictional consultants"
    country_code: Annotated[str, Field(min_length=2, max_length=2)] = "GB"
    region: Annotated[str, Field(min_length=1, max_length=120)] = "England"
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    cursor: Annotated[str | None, Field(max_length=500)] = None
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]

    @field_validator("country_code")
    @classmethod
    def normalize_individual_country(cls, value: str) -> str:
        return value.upper()


class IndividualCandidateView(BaseModel):
    id: UUID
    provider_record_id: str
    display_name: str
    professional_profile_url: str
    normalized_profile_url: str
    persona: str | None
    country_code: str | None
    region: str | None
    service_summary: str | None
    has_professional_presence: bool
    has_business_relevance: bool
    is_fictional: bool
    source_url: str
    observed_at: datetime
    status: str
    disposition: str
    score: int
    maximum_score: int
    rejection_reason: str | None
    possible_match_person_id: UUID | None
    duplicate_person_id: UUID | None
    evidence_classification: str


class IndividualDiscoveryRunView(BaseModel):
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
    candidates: list[IndividualCandidateView] = Field(default_factory=list)


class IndividualReviewRequest(BaseModel):
    action: Literal["promote_new", "link_existing", "reject", "suppress"]
    person_id: UUID | None = None
    reason: Annotated[str, Field(min_length=3, max_length=500)]

    @model_validator(mode="after")
    def validate_action_target(self) -> "IndividualReviewRequest":
        if self.action == "link_existing" and self.person_id is None:
            raise ValueError("person_id is required when linking an existing person")
        if self.action != "link_existing" and self.person_id is not None:
            raise ValueError("person_id is only allowed when linking an existing person")
        return self


class IndividualLeadView(BaseModel):
    id: UUID
    person_id: UUID
    display_name: str
    normalized_profile_url: str
    stage: str
    disposition: str
    person_status: str
    is_fictional: bool
    created_at: datetime


class IndividualLeadPage(BaseModel):
    items: list[IndividualLeadView]


class IndividualReviewResult(BaseModel):
    candidate_id: UUID
    action: str
    candidate_status: str
    rejection_reason: str | None
    lead: IndividualLeadView | None


class PersonSuppressionRequest(BaseModel):
    reason_category: Literal["opt_out", "privacy_request", "operator_suppressed"]


class PersonSuppressionView(BaseModel):
    person_id: UUID
    status: str
    reason_category: str
    effective_at: datetime


class DecisionMakerRunRequest(BaseModel):
    provider_key: str = "fictional_decision_maker_directory"
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class DecisionMakerCandidateView(BaseModel):
    id: UUID
    company_id: UUID
    display_name: str
    professional_profile_url: str
    title: str
    seniority: str | None
    department: str | None
    is_current: bool
    role_score: int
    matched_role: str | None
    qualification_explanation: str
    status: str
    rejection_reason: str | None
    source_url: str
    observed_at: datetime
    evidence_classification: str


class DecisionMakerRunView(BaseModel):
    id: UUID
    company_id: UUID
    provider_key: str
    status: str
    discovered_count: int
    duplicate_count: int
    rejected_count: int
    error_code: str | None
    error_message: str | None
    candidates: list[DecisionMakerCandidateView]


class DecisionMakerRoleView(BaseModel):
    id: UUID
    candidate_id: UUID
    person_id: UUID
    company_id: UUID
    display_name: str
    title: str
    relationship_type: str
    is_current: bool
    evidence_classification: str


class EnrichmentRunRequest(BaseModel):
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class EnrichmentClaimView(BaseModel):
    id: UUID
    claim_type: str
    value: object
    normalized_value: str
    classification: str
    confidence: float
    verification_status: str
    review_status: str
    valid_until: datetime | None
    source_url: str


class EnrichmentRunView(BaseModel):
    id: UUID
    lead_id: UUID
    plan_id: UUID
    status: str
    current_step_order: int | None
    completed_fields: list[str]
    stop_reason: str | None
    claims: list[EnrichmentClaimView]


class OpportunityAnalysisRunRequest(BaseModel):
    provider_key: str = "fictional_opportunity_analyzer"
    idempotency_key: Annotated[str, Field(min_length=8, max_length=160)]


class OpportunityHypothesisView(BaseModel):
    id: UUID
    category: str
    title: str
    summary: str
    confidence: float
    review_status: str
    citation_claim_ids: list[UUID]
    missing_fields: list[str]
    contradictions: list[str]


class OpportunityAnalysisRunView(BaseModel):
    id: UUID
    lead_id: UUID
    provider_key: str
    status: str
    prompt_key: str
    prompt_version: int
    output_schema_version: int
    taxonomy_version: int
    model_name: str | None
    model_version: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    injection_detected: bool
    excluded_claim_ids: list[UUID]
    missing_fields: list[str]
    contradictions: list[str]
    error_code: str | None
    error_message: str | None
    hypotheses: list[OpportunityHypothesisView]


class OpportunityReviewRequest(BaseModel):
    decision: Literal["accept", "reject"]
    reason: Annotated[str, Field(min_length=8, max_length=500)]


class ReviewReversalRequest(BaseModel):
    reason: Annotated[str, Field(min_length=8, max_length=500)]


class EntityMatchRequest(BaseModel):
    entity_kind: Literal["company", "person"]
    left_id: UUID
    right_id: UUID
    exact_stable_identifier: bool = False
    name_similarity: Annotated[float, Field(ge=0, le=1)]


class EntityMatchReviewRequest(BaseModel):
    action: Literal["merge", "reject"]
    survivor_id: UUID | None = None
    reason: Annotated[str, Field(min_length=8, max_length=500)]

    @model_validator(mode="after")
    def merge_requires_survivor(self) -> "EntityMatchReviewRequest":
        if self.action == "merge" and self.survivor_id is None:
            raise ValueError("survivor_id is required for merge")
        if self.action == "reject" and self.survivor_id is not None:
            raise ValueError("survivor_id is not allowed for reject")
        return self


class EntityUnmergeRequest(BaseModel):
    reason: Annotated[str, Field(min_length=8, max_length=500)]


class EntityMergeEventView(BaseModel):
    id: UUID
    action: str
    survivor_id: UUID
    merged_id: UUID
    reverses_event_id: UUID | None
    reason: str
    occurred_at: datetime


class EntityMatchView(BaseModel):
    id: UUID
    entity_kind: str
    left_id: UUID
    right_id: UUID
    match_basis: str
    score: float
    status: str
    explanation: str
    reviewed_at: datetime | None
    events: list[EntityMergeEventView]
