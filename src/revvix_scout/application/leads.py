"""Lead read models, cursor pagination, and safe CSV projection."""

import base64
import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from revvix_scout.application.contracts import (
    EvidenceView,
    LeadDetail,
    LeadListItem,
    LeadPage,
    ScoreComponentView,
    ScoreView,
)
from revvix_scout.config import Settings
from revvix_scout.db.models import (
    Company,
    CompanyDomain,
    EvidenceClaim,
    Lead,
    LeadEvidence,
    ScoreComponent,
    ScoreComponentEvidence,
    ScoreRun,
    SourceDocument,
)


class InvalidCursorError(ValueError):
    """Raised when a list cursor is invalid or altered."""


class LeadNotFoundError(LookupError):
    """Raised when a lead is outside the configured workspace or absent."""


@dataclass(frozen=True, slots=True)
class LeadFilters:
    disposition: str | None = None
    min_score: int | None = None


def list_leads(
    *,
    session: Session,
    settings: Settings,
    filters: LeadFilters,
    limit: int,
    cursor: str | None,
) -> LeadPage:
    """Return a stable, newest-first page of qualified business leads."""

    stmt = _lead_select(settings=settings, filters=filters)
    if cursor is not None:
        created_at, lead_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Lead.created_at < created_at,
                and_(Lead.created_at == created_at, Lead.id < lead_id),
            )
        )
    rows = session.execute(stmt.limit(limit + 1)).all()
    has_more = len(rows) > limit
    selected = rows[:limit]
    items = [_to_list_item(row) for row in selected]
    next_cursor = None
    if has_more and selected:
        final_lead: Lead = selected[-1][0]
        next_cursor = _encode_cursor(final_lead.created_at, final_lead.id)
    return LeadPage(items=items, next_cursor=next_cursor)


def get_lead_detail(*, session: Session, settings: Settings, lead_id: UUID) -> LeadDetail:
    """Return a lead with its latest score explanation and immutable evidence."""

    row = session.execute(
        _lead_select(settings=settings, filters=LeadFilters()).where(Lead.id == lead_id)
    ).one_or_none()
    if row is None:
        raise LeadNotFoundError(str(lead_id))

    item = _to_list_item(row)
    lead: Lead = row[0]
    score_run: ScoreRun = row[3]
    components = session.scalars(
        select(ScoreComponent)
        .where(ScoreComponent.score_run_id == score_run.id)
        .order_by(ScoreComponent.rule_key)
    ).all()
    evidence_by_component: dict[UUID, list[UUID]] = {}
    if components:
        links = session.execute(
            select(
                ScoreComponentEvidence.score_component_id,
                ScoreComponentEvidence.evidence_claim_id,
            ).where(
                ScoreComponentEvidence.score_component_id.in_(
                    [component.id for component in components]
                )
            )
        ).all()
        for component_id, evidence_id in links:
            evidence_by_component.setdefault(component_id, []).append(evidence_id)

    evidence_rows = session.execute(
        select(EvidenceClaim, SourceDocument)
        .join(LeadEvidence, LeadEvidence.evidence_claim_id == EvidenceClaim.id)
        .join(SourceDocument, SourceDocument.id == EvidenceClaim.source_document_id)
        .where(LeadEvidence.lead_id == lead.id)
        .order_by(EvidenceClaim.observed_at.desc(), EvidenceClaim.id)
    ).all()

    score_view = ScoreView(
        id=score_run.id,
        icp_version_id=score_run.icp_version_id,
        algorithm_version=score_run.algorithm_version,
        total_score=score_run.total_score,
        maximum_score=score_run.maximum_score,
        normalized_score=score_run.normalized_score,
        disposition=score_run.disposition,
        missing_fields=list(score_run.missing_fields),
        scored_at=score_run.scored_at,
        components=[
            ScoreComponentView(
                rule_key=component.rule_key,
                points=component.points,
                maximum_points=component.maximum_points,
                result=component.result,
                explanation=component.explanation,
                evidence_claim_ids=evidence_by_component.get(component.id, []),
            )
            for component in components
        ],
    )
    evidence = [
        EvidenceView(
            id=claim.id,
            claim_type=claim.claim_type,
            value=claim.value_json,
            classification=claim.classification,
            confidence=claim.confidence,
            verification_status=claim.verification_status,
            source_url=document.canonical_url,
            source_record_id=document.source_record_id,
            observed_at=claim.observed_at,
            retrieved_at=claim.retrieved_at,
        )
        for claim, document in evidence_rows
    ]
    return LeadDetail(
        **item.model_dump(),
        icp_version_id=lead.icp_version_id,
        stage=lead.stage,
        score_detail=score_view,
        evidence=evidence,
    )


def export_leads_csv(
    *, session: Session, settings: Settings, filters: LeadFilters, max_rows: int = 5_000
) -> str:
    """Export allow-listed lead fields with spreadsheet-formula neutralization."""

    page = list_leads(
        session=session,
        settings=settings,
        filters=filters,
        limit=max_rows,
        cursor=None,
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "lead_id",
            "company_name",
            "domain",
            "country_code",
            "industry",
            "employee_count",
            "match_status",
            "disposition",
            "score",
            "created_at",
        ]
    )
    for item in page.items:
        writer.writerow(
            [
                str(item.id),
                _safe_spreadsheet_cell(item.company_name),
                _safe_spreadsheet_cell(item.normalized_domain),
                item.country_code or "",
                item.industry or "",
                item.employee_count if item.employee_count is not None else "",
                item.match_status,
                item.disposition,
                item.score,
                item.created_at.isoformat(),
            ]
        )
    return buffer.getvalue()


def _lead_select(
    *, settings: Settings, filters: LeadFilters
) -> Select[tuple[Lead, Company, str, ScoreRun]]:
    latest_score_id = (
        select(ScoreRun.id)
        .where(ScoreRun.lead_id == Lead.id)
        .order_by(ScoreRun.scored_at.desc(), ScoreRun.id.desc())
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )
    stmt = (
        select(Lead, Company, CompanyDomain.normalized_domain, ScoreRun)
        .join(Company, Company.id == Lead.company_id)
        .outerjoin(CompanyDomain, CompanyDomain.company_id == Company.id)
        .join(ScoreRun, ScoreRun.id == latest_score_id)
        .where(Lead.workspace_id == settings.default_workspace_id)
        .order_by(Lead.created_at.desc(), Lead.id.desc())
    )
    if filters.disposition is not None:
        stmt = stmt.where(Lead.disposition == filters.disposition)
    if filters.min_score is not None:
        stmt = stmt.where(ScoreRun.total_score >= filters.min_score)
    return stmt


def _to_list_item(row: object) -> LeadListItem:
    lead: Lead = row[0]  # type: ignore[index]
    company: Company = row[1]  # type: ignore[index]
    domain: str | None = row[2]  # type: ignore[index]
    score: ScoreRun = row[3]  # type: ignore[index]
    return LeadListItem(
        id=lead.id,
        company_id=company.id,
        company_name=company.display_name,
        normalized_domain=domain,
        country_code=company.country_code,
        industry=company.industry,
        employee_count=company.employee_count,
        match_status=company.match_status,
        disposition=lead.disposition,
        score=score.total_score,
        created_at=lead.created_at,
    )


def _encode_cursor(created_at: datetime, lead_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(lead_id)}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        lead_id = UUID(payload["id"])
        if created_at.tzinfo is None:
            raise ValueError("cursor timestamp lacks timezone")
        return created_at, lead_id
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise InvalidCursorError("cursor is invalid") from exc


def _safe_spreadsheet_cell(value: str | None) -> str:
    if value is None:
        return ""
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value
