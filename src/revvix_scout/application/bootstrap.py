"""Idempotent bootstrap of the approved M2A development workspace and ICP."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from revvix_scout.config import Settings
from revvix_scout.db.models import BudgetPolicy, IcpConfig, IcpVersion, ProviderConfig, Workspace
from revvix_scout.domain.individuals import development_individual_icp_definition
from revvix_scout.domain.scoring import icp_definition


def bootstrap_defaults(session: Session, settings: Settings) -> None:
    """Create deterministic development records if migrations are present."""

    workspace = session.get(Workspace, settings.default_workspace_id)
    if workspace is None:
        session.add(
            Workspace(
                id=settings.default_workspace_id,
                name="Revvix AI",
                slug="revvix-ai",
                status="active",
            )
        )
        session.flush()

    icp = session.get(IcpConfig, settings.default_icp_id)
    if icp is None:
        session.add(
            IcpConfig(
                id=settings.default_icp_id,
                workspace_id=settings.default_workspace_id,
                name="England Independent Accounting Firms ICP",
                pipeline_kind="business",
                status="active",
            )
        )
        session.flush()

    version = session.get(IcpVersion, settings.default_icp_version_id)
    if version is None:
        session.add(
            IcpVersion(
                id=settings.default_icp_version_id,
                icp_config_id=settings.default_icp_id,
                version=1,
                status="published",
                definition_schema_version=1,
                definition_json=icp_definition(),
                published_at=datetime.now(UTC),
            )
        )
    individual_icp = session.get(IcpConfig, settings.individual_icp_id)
    if individual_icp is None:
        session.add(
            IcpConfig(
                id=settings.individual_icp_id,
                workspace_id=settings.default_workspace_id,
                name="Fictional Individual Prospect Development ICP",
                pipeline_kind="individual",
                status="active",
            )
        )
        session.flush()
    individual_version = session.get(IcpVersion, settings.individual_icp_version_id)
    if individual_version is None:
        session.add(
            IcpVersion(
                id=settings.individual_icp_version_id,
                icp_config_id=settings.individual_icp_id,
                version=1,
                status="published",
                definition_schema_version=1,
                definition_json=development_individual_icp_definition(),
                published_at=datetime.now(UTC),
            )
        )
    providers = (
        ("fictional_accounting_directory", "fixture", "business_discovery", 1, True),
        ("manual_input", "manual", "business_discovery", 0, False),
        ("csv_input", "csv", "business_discovery", 0, False),
        (
            "fictional_professional_directory",
            "fixture",
            "individual_discovery",
            1,
            True,
        ),
    )
    for provider_key, adapter_kind, operation, hard_limit, fictional_only in providers:
        provider = (
            session.query(ProviderConfig)
            .filter_by(
                workspace_id=settings.default_workspace_id,
                provider_key=provider_key,
            )
            .one_or_none()
        )
        if provider is None:
            session.add(
                ProviderConfig(
                    workspace_id=settings.default_workspace_id,
                    provider_key=provider_key,
                    adapter_kind=adapter_kind,
                    enabled=True,
                    live_calls_allowed=False,
                    terms_review_status="approved",
                    config_json={"fictional_data_only": fictional_only},
                    data_policy_json={
                        "retention_days": 14,
                        "contains_personal_data": False,
                    },
                )
            )

        policy = (
            session.query(BudgetPolicy)
            .filter_by(
                workspace_id=settings.default_workspace_id,
                provider_key=provider_key,
                operation=operation,
                window_kind="run",
            )
            .one_or_none()
        )
        if policy is None:
            session.add(
                BudgetPolicy(
                    workspace_id=settings.default_workspace_id,
                    provider_key=provider_key,
                    operation=operation,
                    window_kind="run",
                    hard_limit_units=hard_limit,
                    enabled=True,
                )
            )
    session.commit()
