"""PostgreSQL persistence for provider-free business and individual discovery."""

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


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = ({"schema": "scout"},)


class WorkspaceMember(Base, TimestampMixin):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.user_profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint(
            "role in ('owner', 'admin', 'operator', 'reviewer', 'viewer', 'automation')",
            name="role_valid",
        ),
        CheckConstraint("status in ('active', 'disabled')", name="status_valid"),
        Index("ix_workspace_members_user_status", "user_id", "status"),
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


class Person(Base, TimestampMixin):
    __tablename__ = "people"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(120))
    locality: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    is_fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'needs_review', 'suppressed', 'deleted')",
            name="status_valid",
        ),
        CheckConstraint(
            "is_fictional or retention_expires_at is not null",
            name="personal_data_requires_retention",
        ),
        Index("ix_people_workspace_normalized_name", "workspace_id", "normalized_name"),
        Index("ix_people_workspace_created", "workspace_id", "created_at", "id"),
        {"schema": "scout"},
    )


class PersonProfile(Base):
    __tablename__ = "person_profiles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="CASCADE"), nullable=False
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    original_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="source_asserted"
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "normalized_url", name="uq_person_profiles_workspace_url"),
        UniqueConstraint(
            "workspace_id",
            "provider_key",
            "provider_record_id",
            name="uq_person_profiles_workspace_provider_record",
        ),
        CheckConstraint(
            "verification_status in ('source_asserted', 'human_verified', 'invalid')",
            name="verification_status_valid",
        ),
        Index("ix_person_profiles_person_id", "person_id"),
        {"schema": "scout"},
    )


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE")
    )
    person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="CASCADE")
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
        CheckConstraint(
            "(pipeline_kind = 'business' and company_id is not null and person_id is null) or "
            "(pipeline_kind = 'individual' and person_id is not null and company_id is null)",
            name="subject_matches_pipeline",
        ),
        CheckConstraint(
            "stage in ('qualified', 'review', 'suppressed', 'archived')",
            name="stage_valid",
        ),
        CheckConstraint(
            "disposition in ('qualified', 'review', 'unqualified', 'disqualified')",
            name="disposition_valid",
        ),
        Index("ix_leads_workspace_created", "workspace_id", "created_at", "id"),
        Index("ix_leads_workspace_disposition", "workspace_id", "disposition"),
        Index("ix_leads_icp_version_id", "icp_version_id"),
        Index("ix_leads_company_id", "company_id"),
        Index("ix_leads_person_id", "person_id"),
        Index(
            "uq_leads_business_subject",
            "workspace_id",
            "icp_version_id",
            "company_id",
            unique=True,
            postgresql_where=text("pipeline_kind = 'business'"),
        ),
        Index(
            "uq_leads_individual_subject",
            "workspace_id",
            "icp_version_id",
            "person_id",
            unique=True,
            postgresql_where=text("pipeline_kind = 'individual'"),
        ),
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
    import_row_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.import_rows.id", ondelete="CASCADE")
    )
    enrichment_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.enrichment_runs.id", ondelete="CASCADE")
    )
    source_name: Mapped[str] = mapped_column(String(80), nullable=False, default="csv_import")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="import_row")
    provider_key: Mapped[str | None] = mapped_column(String(80))
    source_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    license_policy_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cache_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redaction_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="metadata_only"
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "content_hash"),
        UniqueConstraint("import_row_id"),
        CheckConstraint(
            "redaction_status in ('metadata_only', 'redacted', 'expired')",
            name="redaction_status_valid",
        ),
        CheckConstraint(
            "(import_row_id is not null and enrichment_run_id is null) or "
            "(import_row_id is null and enrichment_run_id is not null)",
            name="origin_reference_valid",
        ),
        Index("ix_source_documents_lead_retrieved", "lead_id", "retrieved_at"),
        Index("ix_source_documents_enrichment_run", "enrichment_run_id"),
        Index("ix_source_documents_cache_expiry", "cache_expires_at"),
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
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_claim_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.evidence_claims.id", ondelete="RESTRICT")
    )
    extractor_version: Mapped[str | None] = mapped_column(String(80))
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
        CheckConstraint(
            "verification_status in "
            "('source_asserted', 'human_verified', 'conflicting', 'invalid')",
            name="verification_status_valid",
        ),
        CheckConstraint(
            "review_status in ('unreviewed', 'accepted', 'rejected', 'superseded')",
            name="review_status_valid",
        ),
        CheckConstraint(
            "supersedes_claim_id is null or supersedes_claim_id <> id",
            name="cannot_supersede_self",
        ),
        Index("ix_evidence_claims_source_document", "source_document_id"),
        Index("ix_evidence_claims_supersedes", "supersedes_claim_id"),
        Index(
            "ix_evidence_claims_workspace_type_review",
            "workspace_id",
            "claim_type",
            "review_status",
        ),
        Index("ix_evidence_claims_valid_until", "valid_until"),
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


class CompanyEvidence(Base):
    __tablename__ = "company_evidence"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.evidence_claims.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        Index("ix_company_evidence_workspace", "workspace_id"),
        Index("ix_company_evidence_claim", "evidence_claim_id"),
        {"schema": "scout"},
    )


class PersonEvidence(Base):
    __tablename__ = "person_evidence"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.people.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.evidence_claims.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        Index("ix_person_evidence_workspace", "workspace_id"),
        Index("ix_person_evidence_claim", "evidence_claim_id"),
        {"schema": "scout"},
    )


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
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(120))
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
        CheckConstraint("max_attempts > 0 and max_attempts <= 10", name="max_attempts_valid"),
        Index(
            "ix_jobs_claimable",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("status = 'queued'"),
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
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number"),
        CheckConstraint("attempt_number > 0", name="attempt_positive"),
        CheckConstraint("status in ('running', 'succeeded', 'failed')", name="status_valid"),
        {"schema": "scout"},
    )


class EnrichmentPlan(Base, TimestampMixin):
    __tablename__ = "enrichment_plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    icp_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.icp_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    pipeline_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    required_fields_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "name", "version", name="uq_enrichment_plans_workspace_name_version"
        ),
        CheckConstraint("pipeline_kind in ('business', 'individual')", name="pipeline_kind_valid"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("status in ('draft', 'published', 'retired')", name="status_valid"),
        CheckConstraint(
            "(status = 'published' and published_at is not null) or status <> 'published'",
            name="published_plan_has_timestamp",
        ),
        Index("ix_enrichment_plans_icp_version", "icp_version_id"),
        Index("ix_enrichment_plans_workspace_status", "workspace_id", "status"),
        {"schema": "scout"},
    )


class EnrichmentStep(Base, TimestampMixin):
    __tablename__ = "enrichment_steps"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.enrichment_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_fields_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    eligibility_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    freshness_days: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_units: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_if_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fallback_step_order: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("plan_id", "step_order", name="uq_enrichment_steps_plan_order"),
        CheckConstraint("step_order > 0", name="step_order_positive"),
        CheckConstraint("freshness_days >= 0", name="freshness_nonnegative"),
        CheckConstraint("estimated_units >= 0", name="estimated_units_nonnegative"),
        CheckConstraint(
            "fallback_step_order is null or fallback_step_order > step_order",
            name="fallback_moves_forward",
        ),
        Index("ix_enrichment_steps_provider_operation", "provider_key", "operation"),
        {"schema": "scout"},
    )


class EnrichmentRun(Base, TimestampMixin):
    __tablename__ = "enrichment_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.enrichment_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    current_step_order: Mapped[int | None] = mapped_column(Integer)
    completed_fields_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    stop_reason: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status in "
            "('queued', 'running', 'succeeded', 'partially_succeeded', 'failed', 'stopped')",
            name="status_valid",
        ),
        CheckConstraint(
            "current_step_order is null or current_step_order > 0",
            name="current_step_positive",
        ),
        CheckConstraint(
            "stop_reason is null or status in "
            "('succeeded', 'partially_succeeded', 'failed', 'stopped')",
            name="stop_reason_requires_terminal_status",
        ),
        Index("ix_enrichment_runs_workspace_status", "workspace_id", "status", "created_at"),
        Index("ix_enrichment_runs_lead_created", "lead_id", "created_at"),
        Index("ix_enrichment_runs_plan", "plan_id"),
        {"schema": "scout"},
    )


class EntityMatchCandidate(Base, TimestampMixin):
    __tablename__ = "entity_match_candidates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    entity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    left_company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE")
    )
    right_company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE")
    )
    left_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="CASCADE")
    )
    right_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="CASCADE")
    )
    match_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("entity_kind in ('company', 'person')", name="entity_kind_valid"),
        CheckConstraint("match_basis in ('exact', 'fuzzy')", name="match_basis_valid"),
        CheckConstraint("score >= 0 and score <= 1", name="score_range"),
        CheckConstraint(
            "status in ('pending', 'confirmed', 'rejected', 'merged')", name="status_valid"
        ),
        CheckConstraint(
            "(entity_kind = 'company' and left_company_id is not null "
            "and right_company_id is not null "
            "and left_person_id is null and right_person_id is null) or "
            "(entity_kind = 'person' and left_person_id is not null "
            "and right_person_id is not null "
            "and left_company_id is null and right_company_id is null)",
            name="subjects_match_entity_kind",
        ),
        CheckConstraint(
            "(entity_kind = 'company' and left_company_id < right_company_id) or "
            "(entity_kind = 'person' and left_person_id < right_person_id)",
            name="subjects_are_canonical_and_distinct",
        ),
        Index(
            "uq_entity_match_candidates_company_pair",
            "workspace_id",
            "left_company_id",
            "right_company_id",
            unique=True,
            postgresql_where=text("entity_kind = 'company'"),
        ),
        Index(
            "uq_entity_match_candidates_person_pair",
            "workspace_id",
            "left_person_id",
            "right_person_id",
            unique=True,
            postgresql_where=text("entity_kind = 'person'"),
        ),
        Index("ix_entity_match_candidates_left_company", "left_company_id"),
        Index("ix_entity_match_candidates_right_company", "right_company_id"),
        Index("ix_entity_match_candidates_left_person", "left_person_id"),
        Index("ix_entity_match_candidates_right_person", "right_person_id"),
        Index("ix_entity_match_candidates_workspace_status", "workspace_id", "status"),
        {"schema": "scout"},
    )


class EntityMergeEvent(Base):
    __tablename__ = "entity_merge_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    match_candidate_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.entity_match_candidates.id", ondelete="RESTRICT"),
    )
    entity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    survivor_company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="RESTRICT")
    )
    merged_company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="RESTRICT")
    )
    survivor_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="RESTRICT")
    )
    merged_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="RESTRICT")
    )
    reverses_event_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.entity_merge_events.id", ondelete="RESTRICT")
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, default="operator")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("entity_kind in ('company', 'person')", name="entity_kind_valid"),
        CheckConstraint("action in ('merge', 'unmerge')", name="action_valid"),
        CheckConstraint("actor_type = 'operator'", name="actor_type_valid"),
        CheckConstraint(
            "(entity_kind = 'company' and survivor_company_id is not null "
            "and merged_company_id is not null "
            "and survivor_person_id is null and merged_person_id is null) or "
            "(entity_kind = 'person' and survivor_person_id is not null "
            "and merged_person_id is not null "
            "and survivor_company_id is null and merged_company_id is null)",
            name="subjects_match_entity_kind",
        ),
        CheckConstraint(
            "(entity_kind = 'company' and survivor_company_id <> merged_company_id) or "
            "(entity_kind = 'person' and survivor_person_id <> merged_person_id)",
            name="survivor_differs_from_merged",
        ),
        CheckConstraint(
            "(action = 'merge' and reverses_event_id is null) or "
            "(action = 'unmerge' and reverses_event_id is not null)",
            name="unmerge_reverses_event",
        ),
        Index("ix_entity_merge_events_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_entity_merge_events_match_candidate", "match_candidate_id"),
        Index("ix_entity_merge_events_reverses", "reverses_event_id"),
        Index("ix_entity_merge_events_survivor_company", "survivor_company_id"),
        Index("ix_entity_merge_events_merged_company", "merged_company_id"),
        Index("ix_entity_merge_events_survivor_person", "survivor_person_id"),
        Index("ix_entity_merge_events_merged_person", "merged_person_id"),
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
    pipeline_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="business")
    discovery_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="company")
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
        UniqueConstraint("job_id"),
        UniqueConstraint("workspace_id", "request_fingerprint"),
        CheckConstraint("pipeline_kind in ('business', 'individual')", name="pipeline_kind_valid"),
        CheckConstraint(
            "(pipeline_kind = 'business' and discovery_kind in ('company', 'decision_maker')) or "
            "(pipeline_kind = 'individual' and discovery_kind = 'individual')",
            name="discovery_kind_matches_pipeline",
        ),
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


class IndividualDiscoveryCandidate(Base, TimestampMixin):
    __tablename__ = "individual_discovery_candidates"

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
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    professional_profile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_profile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    persona: Mapped[str | None] = mapped_column(String(80))
    country_code: Mapped[str | None] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(120))
    service_summary: Mapped[str | None] = mapped_column(Text)
    has_professional_presence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_business_relevance: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_score: Mapped[int] = mapped_column(Integer, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(160))
    possible_match_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="SET NULL")
    )
    duplicate_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="SET NULL")
    )
    qualification_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "provider_key",
            "provider_record_id",
            name="uq_individual_candidates_run_provider_record",
        ),
        CheckConstraint(
            "status in ('new', 'needs_review', 'duplicate', 'rejected', 'promoted')",
            name="status_valid",
        ),
        CheckConstraint(
            "disposition in ('qualified', 'review', 'unqualified', 'disqualified')",
            name="disposition_valid",
        ),
        CheckConstraint("score >= 0 and score <= maximum_score", name="score_range"),
        CheckConstraint("maximum_score > 0", name="maximum_score_positive"),
        CheckConstraint(
            "is_fictional or retention_expires_at is not null",
            name="personal_data_requires_retention",
        ),
        CheckConstraint(
            "not (possible_match_person_id is not null and duplicate_person_id is not null)",
            name="single_match_resolution",
        ),
        Index("ix_individual_candidates_run_created", "discovery_run_id", "created_at", "id"),
        Index(
            "ix_individual_candidates_workspace_name",
            "workspace_id",
            "normalized_name",
        ),
        Index("ix_individual_candidates_possible_match", "possible_match_person_id"),
        Index("ix_individual_candidates_duplicate", "duplicate_person_id"),
        {"schema": "scout"},
    )


class DecisionMakerCandidate(Base, TimestampMixin):
    __tablename__ = "decision_maker_candidates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE"), nullable=False
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    professional_profile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_profile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title_original: Mapped[str] = mapped_column(String(240), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(240), nullable=False)
    seniority: Mapped[str | None] = mapped_column(String(40))
    department: Mapped[str | None] = mapped_column(String(80))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_fictional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    role_score: Mapped[int] = mapped_column(Integer, nullable=False)
    role_maximum_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(160))
    duplicate_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="SET NULL")
    )
    qualification_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "provider_key",
            "provider_record_id",
            name="uq_decision_maker_candidates_run_provider_record",
        ),
        CheckConstraint(
            "status in ('new', 'duplicate', 'rejected', 'promoted')",
            name="status_valid",
        ),
        CheckConstraint(
            "role_score >= 0 and role_score <= role_maximum_score and role_maximum_score > 0",
            name="role_score_valid",
        ),
        CheckConstraint("is_fictional", name="fictional_only"),
        Index("ix_decision_maker_candidates_run_created", "discovery_run_id", "created_at", "id"),
        Index("ix_decision_maker_candidates_company_status", "company_id", "status"),
        Index("ix_decision_maker_candidates_workspace_created", "workspace_id", "created_at"),
        Index("ix_decision_maker_candidates_duplicate_person", "duplicate_person_id"),
        {"schema": "scout"},
    )


class PersonCompanyRole(Base, TimestampMixin):
    __tablename__ = "person_company_roles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.companies.id", ondelete="CASCADE"), nullable=False
    )
    source_candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.decision_maker_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title_original: Mapped[str] = mapped_column(String(240), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(240), nullable=False)
    seniority: Mapped[str | None] = mapped_column(String(40))
    department: Mapped[str | None] = mapped_column(String(80))
    relationship_type: Mapped[str] = mapped_column(String(24), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    started_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_candidate_id", name="uq_person_company_roles_source_candidate"),
        CheckConstraint(
            "relationship_type in ('partner', 'director', 'employee', 'owner')",
            name="relationship_type_valid",
        ),
        CheckConstraint(
            "evidence_classification in ('provider_asserted', 'human_verified')",
            name="evidence_classification_valid",
        ),
        CheckConstraint(
            "verification_status in ('source_asserted', 'human_verified')",
            name="verification_status_valid",
        ),
        CheckConstraint(
            "ended_on is null or started_on is null or ended_on >= started_on",
            name="role_dates_valid",
        ),
        CheckConstraint("not is_current or ended_on is null", name="current_role_has_no_end"),
        Index("ix_person_company_roles_person_id", "person_id"),
        Index("ix_person_company_roles_company_current", "company_id", "is_current"),
        Index("ix_person_company_roles_workspace_created", "workspace_id", "created_at"),
        {"schema": "scout"},
    )


class Suppression(Base):
    __tablename__ = "suppressions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="RESTRICT")
    )
    normalized_value_hash: Mapped[str | None] = mapped_column(String(64))
    reason_category: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="operator")
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("scope in ('person', 'profile')", name="scope_valid"),
        CheckConstraint(
            "reason_category in ('opt_out', 'privacy_request', 'operator_suppressed')",
            name="reason_category_valid",
        ),
        CheckConstraint("source in ('operator', 'privacy_request')", name="source_valid"),
        CheckConstraint(
            "(scope = 'person' and person_id is not null and normalized_value_hash is null) or "
            "(scope = 'profile' and person_id is null and normalized_value_hash is not null)",
            name="target_matches_scope",
        ),
        CheckConstraint(
            "expires_at is null or expires_at > effective_at",
            name="expiry_after_effective",
        ),
        Index("ix_suppressions_person_id", "person_id"),
        Index(
            "uq_suppressions_active_person",
            "workspace_id",
            "person_id",
            unique=True,
            postgresql_where=text("revoked_at is null and person_id is not null"),
        ),
        Index(
            "uq_suppressions_active_profile",
            "workspace_id",
            "normalized_value_hash",
            unique=True,
            postgresql_where=text("revoked_at is null and normalized_value_hash is not null"),
        ),
        {"schema": "scout"},
    )


class IndividualReviewDecision(Base):
    __tablename__ = "individual_review_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.individual_discovery_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    selected_person_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.people.id", ondelete="RESTRICT")
    )
    lead_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, default="operator")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(String(500))
    reversed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.user_profiles.user_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "action in ('promote_new', 'link_existing', 'reject', 'suppress')",
            name="action_valid",
        ),
        CheckConstraint("actor_type = 'operator'", name="actor_type_valid"),
        CheckConstraint(
            "(action in ('promote_new', 'link_existing') and selected_person_id is not null) or "
            "(action in ('reject', 'suppress') and selected_person_id is null)",
            name="promotion_action_requires_person",
        ),
        CheckConstraint(
            "(action in ('promote_new', 'link_existing') and lead_id is not null) or "
            "(action in ('reject', 'suppress') and lead_id is null)",
            name="promotion_action_requires_lead",
        ),
        CheckConstraint(
            "(reversed_at is null and reversal_reason is null and reversed_by_user_id is null) or "
            "(reversed_at is not null and reversal_reason is not null and "
            "reversed_by_user_id is not null)",
            name="reversal_fields_complete",
        ),
        Index("ix_individual_review_decisions_workspace_decided", "workspace_id", "decided_at"),
        Index("ix_individual_review_decisions_selected_person", "selected_person_id"),
        Index("ix_individual_review_decisions_lead", "lead_id"),
        Index("ix_individual_review_decisions_reversed_by", "reversed_by_user_id"),
        Index(
            "uq_individual_review_decisions_active_candidate",
            "workspace_id",
            "candidate_id",
            unique=True,
            postgresql_where=text("reversed_at is null"),
        ),
        {"schema": "scout"},
    )


class AiPromptDefinition(Base):
    __tablename__ = "ai_prompt_definitions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    prompt_key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    system_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    taxonomy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    taxonomy_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "prompt_key", "version", name="uq_ai_prompt_definitions_version"
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("output_schema_version > 0", name="output_schema_version_positive"),
        CheckConstraint("taxonomy_version > 0", name="taxonomy_version_positive"),
        CheckConstraint("status in ('draft', 'published', 'retired')", name="status_valid"),
        CheckConstraint(
            "(status = 'published' and published_at is not null) or status <> 'published'",
            name="published_requires_timestamp",
        ),
        Index("ix_ai_prompt_definitions_workspace_status", "workspace_id", "status"),
        {"schema": "scout"},
    )


class OpportunityAnalysisRun(Base, TimestampMixin):
    __tablename__ = "opportunity_analysis_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.leads.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    prompt_definition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.ai_prompt_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(120))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_snapshot_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    excluded_claim_ids_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    injection_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_fields_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    contradictions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "lead_id",
            "prompt_definition_id",
            "input_fingerprint",
            name="uq_opportunity_analysis_runs_input",
        ),
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed')", name="status_valid"
        ),
        CheckConstraint(
            "prompt_tokens is null or prompt_tokens >= 0", name="prompt_tokens_nonnegative"
        ),
        CheckConstraint(
            "completion_tokens is null or completion_tokens >= 0",
            name="completion_tokens_nonnegative",
        ),
        Index(
            "ix_opportunity_analysis_runs_workspace_status",
            "workspace_id",
            "status",
            "created_at",
        ),
        Index("ix_opportunity_analysis_runs_lead_created", "lead_id", "created_at"),
        Index("ix_opportunity_analysis_runs_prompt", "prompt_definition_id"),
        {"schema": "scout"},
    )


class OpportunityHypothesis(Base):
    __tablename__ = "opportunity_hypotheses"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.opportunity_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")
    missing_fields_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    contradictions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("confidence >= 0 and confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "review_status in ('unreviewed', 'accepted', 'rejected')",
            name="review_status_valid",
        ),
        Index("ix_opportunity_hypotheses_run", "analysis_run_id"),
        Index("ix_opportunity_hypotheses_workspace_review", "workspace_id", "review_status"),
        {"schema": "scout"},
    )


class OpportunityHypothesisEvidence(Base):
    __tablename__ = "opportunity_hypothesis_evidence"

    hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.opportunity_hypotheses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_claim_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.evidence_claims.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = (
        Index("ix_opportunity_hypothesis_evidence_claim", "evidence_claim_id"),
        {"schema": "scout"},
    )


class OpportunityReviewDecision(Base):
    __tablename__ = "opportunity_review_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    hypothesis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.opportunity_hypotheses.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, default="operator")
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(String(500))
    reversed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.user_profiles.user_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("decision in ('accept', 'reject')", name="decision_valid"),
        CheckConstraint("actor_type = 'operator'", name="actor_type_valid"),
        CheckConstraint(
            "(reversed_at is null and reversal_reason is null and reversed_by_user_id is null) or "
            "(reversed_at is not null and reversal_reason is not null and "
            "reversed_by_user_id is not null)",
            name="reversal_fields_complete",
        ),
        Index("ix_opportunity_review_decisions_workspace_decided", "workspace_id", "decided_at"),
        Index("ix_opportunity_review_decisions_reversed_by", "reversed_by_user_id"),
        Index(
            "uq_opportunity_review_decisions_active_hypothesis",
            "workspace_id",
            "hypothesis_id",
            unique=True,
            postgresql_where=text("reversed_at is null"),
        ),
        {"schema": "scout"},
    )


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.discovery_runs.id", ondelete="CASCADE"),
    )
    enrichment_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.enrichment_runs.id", ondelete="CASCADE"),
    )
    opportunity_analysis_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.opportunity_analysis_runs.id", ondelete="CASCADE"),
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
        CheckConstraint(
            "(discovery_run_id is not null and enrichment_run_id is null "
            "and opportunity_analysis_run_id is null) or "
            "(discovery_run_id is null and enrichment_run_id is not null "
            "and opportunity_analysis_run_id is null) or "
            "(discovery_run_id is null and enrichment_run_id is null "
            "and opportunity_analysis_run_id is not null)",
            name="run_reference_valid",
        ),
        Index(
            "ix_budget_reservations_run_status",
            "discovery_run_id",
            "status",
        ),
        Index(
            "ix_budget_reservations_enrichment_run_status",
            "enrichment_run_id",
            "status",
        ),
        Index(
            "ix_budget_reservations_opportunity_run_status",
            "opportunity_analysis_run_id",
            "status",
        ),
        Index("ix_budget_reservations_workspace", "workspace_id"),
        {"schema": "scout"},
    )


class ProviderUsageEvent(Base):
    __tablename__ = "provider_usage_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    discovery_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.discovery_runs.id", ondelete="CASCADE"),
    )
    enrichment_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.enrichment_runs.id", ondelete="CASCADE"),
    )
    opportunity_analysis_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.opportunity_analysis_runs.id", ondelete="CASCADE"),
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
        CheckConstraint(
            "(discovery_run_id is not null and enrichment_run_id is null "
            "and opportunity_analysis_run_id is null) or "
            "(discovery_run_id is null and enrichment_run_id is not null "
            "and opportunity_analysis_run_id is null) or "
            "(discovery_run_id is null and enrichment_run_id is null "
            "and opportunity_analysis_run_id is not null)",
            name="run_reference_valid",
        ),
        Index("ix_provider_usage_events_run_occurred", "discovery_run_id", "occurred_at"),
        Index(
            "ix_provider_usage_events_enrichment_run_occurred",
            "enrichment_run_id",
            "occurred_at",
        ),
        Index(
            "ix_provider_usage_events_opportunity_run_occurred",
            "opportunity_analysis_run_id",
            "occurred_at",
        ),
        Index("ix_provider_usage_events_workspace", "workspace_id"),
        Index("ix_provider_usage_events_reservation", "reservation_id"),
        {"schema": "scout"},
    )


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.user_profiles.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    filter_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    selected_fields_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("row_count >= 0", name="row_count_nonnegative"),
        CheckConstraint("status in ('succeeded', 'failed')", name="status_valid"),
        Index("ix_export_jobs_workspace_created", "workspace_id", "created_at", "id"),
        Index("ix_export_jobs_requester", "requested_by_user_id"),
        {"schema": "scout"},
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scout.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scout.user_profiles.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_audit_events_workspace_occurred", "workspace_id", "occurred_at", "id"),
        Index("ix_audit_events_actor", "actor_user_id", "occurred_at"),
        {"schema": "scout"},
    )
