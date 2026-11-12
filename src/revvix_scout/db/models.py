"""M2A PostgreSQL persistence model.

The model intentionally contains only the provider-free business qualification slice.
Future milestones extend it rather than pre-creating unused platform tables.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from revvix_scout.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status in ('active', 'disabled')", name="status_valid"),
        {"schema": "scout"},
    )


class IcpConfig(Base, TimestampMixin):
    __tablename__ = "icp_configs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    pipeline_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", "pipeline_kind"),
        CheckConstraint("pipeline_kind in ('business', 'individual')", name="pipeline_valid"),
        CheckConstraint("status in ('active', 'archived')", name="status_valid"),
        {"schema": "scout"},
    )


class IcpVersion(Base):
    __tablename__ = "icp_versions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    icp_config_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.icp_configs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="published")
    definition_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("icp_config_id", "version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("status in ('draft', 'published', 'retired')", name="status_valid"),
        {"schema": "scout"},
    )


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    fallback_fingerprint: Mapped[str | None] = mapped_column(String(64))
    country_code: Mapped[str | None] = mapped_column(String(2))
    industry: Mapped[str | None] = mapped_column(String(80))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    match_status: Mapped[str] = mapped_column(String(24), nullable=False, default="resolved")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "employee_count is null or employee_count >= 0", name="employees_nonnegative"
        ),
        CheckConstraint("match_status in ('resolved', 'needs_review')", name="match_status_valid"),
        Index(
            "uq_companies_workspace_fallback_fingerprint",
            "workspace_id",
            "fallback_fingerprint",
            unique=True,
            postgresql_where=text("fallback_fingerprint is not null"),
        ),
        Index("ix_companies_workspace_created", "workspace_id", "created_at", "id"),
        {"schema": "scout"},
    )


class CompanyDomain(Base):
    __tablename__ = "company_domains"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE"), nullable=False
    )
    original_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    normalized_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    domain_type: Mapped[str] = mapped_column(String(24), nullable=False, default="primary")
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="source_asserted"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "normalized_domain"),
        CheckConstraint("domain_type in ('primary', 'alias')", name="domain_type_valid"),
        {"schema": "scout"},
    )


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE"), nullable=False
    )
    icp_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.icp_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pipeline_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="business")
    stage: Mapped[str] = mapped_column(String(24), nullable=False, default="qualified")
    disposition: Mapped[str] = mapped_column(String(24), nullable=False, default="unqualified")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "icp_version_id", "company_id"),
        CheckConstraint("pipeline_kind = 'business'", name="m2a_business_only"),
        CheckConstraint(
            "disposition in ('qualified', 'review', 'unqualified', 'disqualified')",
            name="disposition_valid",
        ),
        Index("ix_leads_workspace_created", "workspace_id", "created_at", "id"),
        Index("ix_leads_workspace_disposition", "workspace_id", "disposition"),
        {"schema": "scout"},
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("workspace_id", "content_hash"),
        CheckConstraint(
            "status in ('running', 'succeeded', 'partially_succeeded', 'failed')",
            name="status_valid",
        ),
        {"schema": "scout"},
    )


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    import_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.import_jobs.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(160))
    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="SET NULL")
    )
    lead_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="SET NULL")
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("import_job_id", "row_number"),
        CheckConstraint("status in ('created', 'duplicate', 'failed')", name="status_valid"),
        {"schema": "scout"},
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="CASCADE"), nullable=False
    )
    import_row_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.import_rows.id", ondelete="CASCADE"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String(80), nullable=False, default="csv_import")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="import_row")
    source_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "content_hash"),
        UniqueConstraint("import_row_id"),
        {"schema": "scout"},
    )


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_type: Mapped[str] = mapped_column(String(80), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(
        String(32), nullable=False, default="provider_asserted"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="source_asserted"
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source_document_id", "claim_type", "value_hash"),
        CheckConstraint("confidence >= 0 and confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "classification in ('observed', 'provider_asserted', 'inferred', 'human_verified')",
            name="classification_valid",
        ),
        {"schema": "scout"},
    )


class LeadEvidence(Base):
    __tablename__ = "lead_evidence"

    lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.evidence_claims.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = ({"schema": "scout"},)


class ScoreRun(Base):
    __tablename__ = "score_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="CASCADE"), nullable=False
    )
    icp_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.icp_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_score: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False)
    disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("lead_id", "icp_version_id", "algorithm_version", "input_fingerprint"),
        CheckConstraint("total_score >= 0", name="total_nonnegative"),
        CheckConstraint("maximum_score > 0", name="maximum_positive"),
        CheckConstraint("normalized_score >= 0 and normalized_score <= 1", name="normalized_range"),
        Index("ix_score_runs_lead_scored", "lead_id", "scored_at", "id"),
        {"schema": "scout"},
    )


class ScoreComponent(Base):
    __tablename__ = "score_components"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    score_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.score_runs.id", ondelete="CASCADE"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(String(80), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_points: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(80), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("score_run_id", "rule_key"),
        CheckConstraint("points >= 0", name="points_nonnegative"),
        CheckConstraint("maximum_points > 0", name="maximum_positive"),
        {"schema": "scout"},
    )


class ScoreComponentEvidence(Base):
    __tablename__ = "score_component_evidence"

    score_component_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.score_components.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.evidence_claims.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = ({"schema": "scout"},)


class ProviderConfig(Base, TimestampMixin):
    """Workspace-scoped adapter enablement and governance state (never secrets)."""

    __tablename__ = "provider_configs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    live_calls_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    terms_review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    data_policy_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_key"),
        CheckConstraint(
            "terms_review_status in ('pending', 'approved', 'rejected', 'expired')",
            name="terms_review_status_valid",
        ),
        CheckConstraint(
            "not live_calls_allowed or (enabled and terms_review_status = 'approved')",
            name="live_calls_require_approval",
        ),
        {"schema": "scout"},
    )


class BudgetPolicy(Base, TimestampMixin):
    __tablename__ = "budget_policies"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    window_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="run")
    hard_limit_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_key", "operation", "window_kind"),
        CheckConstraint("window_kind in ('run', 'day', 'month')", name="window_kind_valid"),
        CheckConstraint("hard_limit_units >= 0", name="hard_limit_nonnegative"),
        {"schema": "scout"},
    )


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("workspace_id", "job_type", "idempotency_key"),
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'partially_succeeded', 'failed')",
            name="status_valid",
        ),
        {"schema": "scout"},
    )


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number"),
        CheckConstraint("attempt_number > 0", name="attempt_positive"),
        CheckConstraint("status in ('running', 'succeeded', 'failed')", name="status_valid"),
        {"schema": "scout"},
    )


class DiscoveryRun(Base, TimestampMixin):
    __tablename__ = "discovery_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.jobs.id", ondelete="CASCADE"), nullable=False
    )
    icp_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.icp_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    next_cursor: Mapped[str | None] = mapped_column(String(500))
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("workspace_id", "request_fingerprint"),
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'partially_succeeded', 'failed')",
            name="status_valid",
        ),
        {"schema": "scout"},
    )


class DiscoveryCandidate(Base, TimestampMixin):
    __tablename__ = "discovery_candidates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    company_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_domain: Mapped[str | None] = mapped_column(String(253))
    country_code: Mapped[str | None] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(120))
    industry: Mapped[str | None] = mapped_column(String(80))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    legal_form: Mapped[str | None] = mapped_column(String(80))
    company_status: Mapped[str | None] = mapped_column(String(40))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    rejection_reason: Mapped[str | None] = mapped_column(String(160))
    duplicate_company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="SET NULL")
    )
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("discovery_run_id", "provider_key", "provider_record_id"),
        CheckConstraint(
            "employee_count is null or employee_count >= 0", name="employees_nonnegative"
        ),
        CheckConstraint(
            "status in ('new', 'duplicate', 'rejected', 'needs_review', 'promoted')",
            name="status_valid",
        ),
        Index("ix_discovery_candidates_run_created", "discovery_run_id", "created_at", "id"),
        {"schema": "scout"},
    )


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    reserved_units: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_units: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("reserved_units >= 0", name="reserved_units_nonnegative"),
        CheckConstraint(
            "settled_units is null or settled_units >= 0", name="settled_units_nonnegative"
        ),
        CheckConstraint("status in ('active', 'settled', 'released')", name="status_valid"),
        {"schema": "scout"},
    )


class ProviderUsageEvent(Base):
    __tablename__ = "provider_usage_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    reservation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.budget_reservations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    estimated_units: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_units: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_type: Mapped[str] = mapped_column(String(40), nullable=False, default="request")
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("estimated_units >= 0 and actual_units >= 0", name="units_nonnegative"),
        CheckConstraint("outcome in ('succeeded', 'failed', 'partial')", name="outcome_valid"),
        {"schema": "scout"},
    )
