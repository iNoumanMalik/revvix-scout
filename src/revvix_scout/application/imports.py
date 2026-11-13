"""Provider-free CSV business import use case."""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import (
    BusinessImportRow,
    ImportRowError,
    ImportSummary,
)
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    Company,
    CompanyDomain,
    EvidenceClaim,
    IcpVersion,
    ImportJob,
    ImportRow,
    Lead,
    LeadEvidence,
    ScoreComponent,
    ScoreComponentEvidence,
    ScoreRun,
    SourceDocument,
)
from revvix_scout.domain.normalization import (
    InvalidDomainError,
    fallback_company_fingerprint,
    normalize_company_name,
    normalize_domain,
)
from revvix_scout.domain.scoring import ALGORITHM_VERSION, ScoreInput, score_business

REQUIRED_COLUMNS = {
    "schema_version",
    "source_record_id",
    "company_name",
    "domain",
    "country_code",
    "employee_count",
    "industry",
    "technology_need",
    "excluded_reason",
    "source_url",
    "observed_at",
}


class ImportContractError(ValueError):
    """Raised when the file itself cannot be processed as the versioned contract."""


@dataclass(frozen=True, slots=True)
class ParsedCsv:
    rows: list[dict[str, str | None]]
    content_hash: str


def import_business_csv(
    *, session: Session, settings: Settings, filename: str, content: bytes
) -> ImportSummary:
    """Import a CSV with row-level savepoints and deterministic idempotency."""

    parsed = _parse_csv(content=content, settings=settings)
    existing = session.scalar(
        select(ImportJob).where(
            ImportJob.workspace_id == settings.default_workspace_id,
            ImportJob.content_hash == parsed.content_hash,
        )
    )
    if existing is not None:
        return _summary(session=session, job=existing, idempotent_replay=True)

    job = ImportJob(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        content_hash=parsed.content_hash,
        filename=filename[:255] or "businesses.csv",
        status="running",
        total_rows=len(parsed.rows),
    )
    session.add(job)
    session.flush()

    seen_fingerprints: set[str] = set()
    for row_number, raw_row in enumerate(parsed.rows, start=2):
        fingerprint = _hash_json(raw_row)
        source_record_id = (raw_row.get("source_record_id") or "").strip() or None
        if fingerprint in seen_fingerprints:
            session.add(
                ImportRow(
                    import_job_id=job.id,
                    row_number=row_number,
                    source_record_id=source_record_id,
                    row_fingerprint=fingerprint,
                    status="duplicate",
                    error_code="duplicate_row_in_file",
                    error_message="An identical row already appeared in this file.",
                )
            )
            job.succeeded_rows += 1
            job.duplicate_rows += 1
            continue
        seen_fingerprints.add(fingerprint)

        try:
            row = BusinessImportRow.model_validate(raw_row)
        except ValidationError as exc:
            _record_failure(
                session=session,
                job=job,
                row_number=row_number,
                source_record_id=source_record_id,
                fingerprint=fingerprint,
                code="validation_error",
                message=_validation_message(exc),
            )
            continue

        try:
            with session.begin_nested():
                was_duplicate = _process_valid_row(
                    session=session,
                    settings=settings,
                    job=job,
                    row_number=row_number,
                    row_fingerprint=fingerprint,
                    row=row,
                )
        except (InvalidDomainError, IntegrityError, ValueError) as exc:
            _record_failure(
                session=session,
                job=job,
                row_number=row_number,
                source_record_id=row.source_record_id,
                fingerprint=fingerprint,
                code=_safe_error_code(exc),
                message=_safe_error_message(exc),
            )
            continue

        job.succeeded_rows += 1
        if was_duplicate:
            job.duplicate_rows += 1

    job.failed_rows = job.total_rows - job.succeeded_rows
    if job.succeeded_rows == 0 and job.failed_rows:
        job.status = "failed"
    elif job.failed_rows:
        job.status = "partially_succeeded"
    else:
        job.status = "succeeded"
    job.completed_at = datetime.now(UTC)
    session.commit()
    return _summary(session=session, job=job, idempotent_replay=False)


def _parse_csv(*, content: bytes, settings: Settings) -> ParsedCsv:
    if not content:
        raise ImportContractError("CSV file is empty")
    if len(content) > settings.max_import_bytes:
        raise ImportContractError(
            f"CSV exceeds the {settings.max_import_bytes}-byte development limit"
        )
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportContractError("CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    if reader.fieldnames is None:
        raise ImportContractError("CSV header is missing")
    normalized_headers = [header.strip() for header in reader.fieldnames]
    if len(set(normalized_headers)) != len(normalized_headers):
        raise ImportContractError("CSV header contains duplicate columns")
    missing = sorted(REQUIRED_COLUMNS - set(normalized_headers))
    if missing:
        raise ImportContractError(f"CSV is missing required columns: {', '.join(missing)}")

    rows: list[dict[str, str | None]] = []
    for raw in reader:
        if None in raw:
            raise ImportContractError("A CSV row contains more values than the header")
        rows.append({key.strip(): value for key, value in raw.items()})
        if len(rows) > settings.max_import_rows:
            raise ImportContractError(
                f"CSV exceeds the {settings.max_import_rows}-row development limit"
            )
    if not rows:
        raise ImportContractError("CSV contains no data rows")
    return ParsedCsv(rows=rows, content_hash=hashlib.sha256(content).hexdigest())


def _process_valid_row(
    *,
    session: Session,
    settings: Settings,
    job: ImportJob,
    row_number: int,
    row_fingerprint: str,
    row: BusinessImportRow,
) -> bool:
    now = datetime.now(UTC)
    normalized_name = normalize_company_name(row.company_name)
    if not normalized_name:
        raise ValueError("company_name has no usable characters after normalization")
    normalized_domain = normalize_domain(row.domain)
    fallback = None
    company: Company | None = None

    if normalized_domain is not None:
        company = session.scalar(
            select(Company)
            .join(CompanyDomain, CompanyDomain.company_id == Company.id)
            .where(
                CompanyDomain.workspace_id == settings.default_workspace_id,
                CompanyDomain.normalized_domain == normalized_domain,
            )
        )
    else:
        fallback = fallback_company_fingerprint(
            normalized_name=normalized_name,
            country_code=row.country_code,
            source_record_id=row.source_record_id,
        )
        company = session.scalar(
            select(Company).where(
                Company.workspace_id == settings.default_workspace_id,
                Company.fallback_fingerprint == fallback,
            )
        )

    was_duplicate = company is not None
    if company is None:
        company = Company(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            display_name=row.company_name,
            normalized_name=normalized_name,
            fallback_fingerprint=fallback,
            country_code=row.country_code,
            industry=row.industry,
            employee_count=row.employee_count,
            match_status="resolved" if normalized_domain else "needs_review",
            first_seen_at=row.observed_at,
            last_seen_at=row.observed_at,
        )
        session.add(company)
        session.flush()
        if normalized_domain is not None and row.domain is not None:
            session.add(
                CompanyDomain(
                    workspace_id=settings.default_workspace_id,
                    company_id=company.id,
                    original_domain=row.domain,
                    normalized_domain=normalized_domain,
                )
            )
    else:
        company.last_seen_at = max(company.last_seen_at, row.observed_at)
        company.updated_at = now
        if row.country_code is not None:
            company.country_code = row.country_code
        if row.industry is not None:
            company.industry = row.industry
        if row.employee_count is not None:
            company.employee_count = row.employee_count

    lead = session.scalar(
        select(Lead).where(
            Lead.workspace_id == settings.default_workspace_id,
            Lead.icp_version_id == settings.default_icp_version_id,
            Lead.company_id == company.id,
        )
    )
    if lead is None:
        lead = Lead(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            company_id=company.id,
            icp_version_id=settings.default_icp_version_id,
            pipeline_kind="business",
            stage="qualified",
            disposition="unqualified",
            first_seen_at=row.observed_at,
            last_activity_at=now,
        )
        session.add(lead)
        session.flush()
    else:
        lead.last_activity_at = now

    import_row = ImportRow(
        id=uuid4(),
        import_job_id=job.id,
        row_number=row_number,
        source_record_id=row.source_record_id,
        row_fingerprint=row_fingerprint,
        status="duplicate" if was_duplicate else "created",
        company_id=company.id,
        lead_id=lead.id,
    )
    session.add(import_row)
    session.flush()

    document_content_hash = _hash_json(row.model_dump(mode="json"))
    existing_document = session.scalar(
        select(SourceDocument).where(
            SourceDocument.workspace_id == settings.default_workspace_id,
            SourceDocument.content_hash == document_content_hash,
        )
    )
    if existing_document is not None:
        import_row.status = "duplicate"
        return True

    source_document = SourceDocument(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        lead_id=lead.id,
        import_row_id=import_row.id,
        source_name="csv_import",
        source_type="import_row",
        provider_key=None,
        source_record_id=row.source_record_id,
        canonical_url=str(row.source_url),
        content_hash=document_content_hash,
        license_policy_json={
            "source": "csv_import",
            "raw_content_retained": False,
        },
        cache_expires_at=None,
        redaction_status="metadata_only",
        observed_at=row.observed_at,
        retrieved_at=now,
    )
    session.add(source_document)
    session.flush()

    evidence_ids = _create_evidence(
        session=session,
        settings=settings,
        lead=lead,
        source_document=source_document,
        row=row,
        retrieved_at=now,
    )
    _score_and_persist(
        session=session,
        settings=settings,
        lead=lead,
        row=row,
        evidence_ids=evidence_ids,
        scored_at=now,
    )
    return was_duplicate


def _create_evidence(
    *,
    session: Session,
    settings: Settings,
    lead: Lead,
    source_document: SourceDocument,
    row: BusinessImportRow,
    retrieved_at: datetime,
) -> dict[str, UUID]:
    values: dict[str, Any] = {
        "industry": row.industry,
        "employee_count": row.employee_count,
        "country_code": row.country_code,
        "technology_need": row.technology_need,
        "excluded_reason": row.excluded_reason,
    }
    evidence_ids: dict[str, UUID] = {}
    for claim_type, value in values.items():
        if value is None:
            continue
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        claim = EvidenceClaim(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            source_document_id=source_document.id,
            claim_type=claim_type,
            value_json=value,
            normalized_value=str(value),
            value_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            classification="provider_asserted",
            confidence=0.8,
            verification_status="source_asserted",
            observed_at=row.observed_at,
            retrieved_at=retrieved_at,
        )
        session.add(claim)
        session.flush()
        session.add(LeadEvidence(lead_id=lead.id, evidence_claim_id=claim.id))
        evidence_ids[claim_type] = claim.id
    return evidence_ids


def _score_and_persist(
    *,
    session: Session,
    settings: Settings,
    lead: Lead,
    row: BusinessImportRow,
    evidence_ids: dict[str, UUID],
    scored_at: datetime,
) -> None:
    score_input = ScoreInput(
        industry=row.industry,
        employee_count=row.employee_count,
        country_code=row.country_code,
        technology_need=row.technology_need,
        excluded_reason=row.excluded_reason,
        evidence_ids=evidence_ids,
    )
    icp_version = session.get(IcpVersion, settings.default_icp_version_id)
    if icp_version is None:
        raise ValueError("Configured ICP version does not exist")
    result = score_business(score_input, icp_version.definition_json)
    input_fingerprint = _hash_json(
        {
            "algorithm_version": ALGORITHM_VERSION,
            "industry": row.industry,
            "employee_count": row.employee_count,
            "country_code": row.country_code,
            "technology_need": row.technology_need,
            "excluded_reason": row.excluded_reason,
        }
    )
    existing = session.scalar(
        select(ScoreRun).where(
            ScoreRun.lead_id == lead.id,
            ScoreRun.icp_version_id == settings.default_icp_version_id,
            ScoreRun.algorithm_version == ALGORITHM_VERSION,
            ScoreRun.input_fingerprint == input_fingerprint,
        )
    )
    if existing is not None:
        lead.disposition = existing.disposition
        return

    run = ScoreRun(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        lead_id=lead.id,
        icp_version_id=settings.default_icp_version_id,
        algorithm_version=ALGORITHM_VERSION,
        input_fingerprint=input_fingerprint,
        total_score=result.total_score,
        maximum_score=result.maximum_score,
        normalized_score=result.total_score / result.maximum_score,
        disposition=result.disposition.value,
        missing_fields=list(result.missing_fields),
        scored_at=scored_at,
    )
    session.add(run)
    session.flush()
    for component in result.components:
        stored = ScoreComponent(
            id=uuid4(),
            score_run_id=run.id,
            rule_key=component.rule_key,
            points=component.points,
            maximum_points=component.maximum_points,
            result=component.result,
            explanation=component.explanation,
        )
        session.add(stored)
        session.flush()
        if component.evidence_id is not None:
            session.add(
                ScoreComponentEvidence(
                    score_component_id=stored.id,
                    evidence_claim_id=component.evidence_id,
                )
            )
    lead.disposition = result.disposition.value


def _record_failure(
    *,
    session: Session,
    job: ImportJob,
    row_number: int,
    source_record_id: str | None,
    fingerprint: str,
    code: str,
    message: str,
) -> None:
    session.add(
        ImportRow(
            import_job_id=job.id,
            row_number=row_number,
            source_record_id=source_record_id,
            row_fingerprint=fingerprint,
            status="failed",
            error_code=code,
            error_message=message,
        )
    )


def _summary(*, session: Session, job: ImportJob, idempotent_replay: bool) -> ImportSummary:
    failures = session.scalars(
        select(ImportRow)
        .where(ImportRow.import_job_id == job.id, ImportRow.status == "failed")
        .order_by(ImportRow.row_number)
    ).all()
    return ImportSummary(
        import_job_id=job.id,
        status=job.status,
        total_rows=job.total_rows,
        succeeded_rows=job.succeeded_rows,
        failed_rows=job.failed_rows,
        duplicate_rows=job.duplicate_rows,
        idempotent_replay=idempotent_replay,
        errors=[
            ImportRowError(
                row_number=row.row_number,
                source_record_id=row.source_record_id,
                code=row.error_code or "unknown",
                message=row.error_message or "Unknown import error",
            )
            for row in failures
        ],
    )


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(item) for item in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)[:500]


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, InvalidDomainError):
        return "invalid_domain"
    if isinstance(exc, IntegrityError):
        return "database_constraint"
    return "processing_error"


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, InvalidDomainError):
        return str(exc)[:500]
    if isinstance(exc, IntegrityError):
        return "The row conflicts with a database identity or provenance constraint."
    return str(exc)[:500]


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
