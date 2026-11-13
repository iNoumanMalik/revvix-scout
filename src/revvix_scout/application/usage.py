"""Shared atomic provider budget reservation and usage settlement."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from revvix_scout.config import Settings
from revvix_scout.db.models import (
    BudgetPolicy,
    BudgetReservation,
    DiscoveryRun,
    ProviderUsageEvent,
)


class BudgetExceededError(RuntimeError):
    pass


def reserve_provider_budget(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    provider_key: str,
    operation: str,
    estimated_units: int,
    now: datetime,
) -> BudgetReservation:
    """Lock the applicable policy and reserve units before provider execution."""

    policy = session.scalar(
        select(BudgetPolicy)
        .where(
            BudgetPolicy.workspace_id == settings.default_workspace_id,
            BudgetPolicy.provider_key == provider_key,
            BudgetPolicy.operation == operation,
            BudgetPolicy.window_kind == "run",
            BudgetPolicy.enabled.is_(True),
        )
        .with_for_update()
    )
    if policy is None:
        raise BudgetExceededError("No enabled budget policy; default deny")
    active_units = session.scalar(
        select(func.coalesce(func.sum(BudgetReservation.reserved_units), 0)).where(
            BudgetReservation.discovery_run_id == run.id,
            BudgetReservation.status == "active",
        )
    )
    settled_units = session.scalar(
        select(func.coalesce(func.sum(ProviderUsageEvent.actual_units), 0)).where(
            ProviderUsageEvent.discovery_run_id == run.id
        )
    )
    if int(active_units or 0) + int(settled_units or 0) + estimated_units > policy.hard_limit_units:
        raise BudgetExceededError("Provider call would exceed the hard run budget")
    reservation = BudgetReservation(
        id=uuid4(),
        workspace_id=settings.default_workspace_id,
        discovery_run_id=run.id,
        provider_key=provider_key,
        operation=operation,
        reserved_units=estimated_units,
        status="active",
        reserved_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    session.add(reservation)
    session.flush()
    return reservation


def settle_provider_usage(
    *,
    session: Session,
    settings: Settings,
    run: DiscoveryRun,
    reservation: BudgetReservation,
    operation: str,
    actual_units: int,
    outcome: str,
    now: datetime,
) -> None:
    """Settle one reservation and append its immutable usage event."""

    reservation.status = "settled"
    reservation.settled_units = actual_units
    reservation.settled_at = now
    session.add(
        ProviderUsageEvent(
            workspace_id=settings.default_workspace_id,
            discovery_run_id=run.id,
            reservation_id=reservation.id,
            provider_key=run.provider_key,
            operation=operation,
            outcome=outcome,
            estimated_units=reservation.reserved_units,
            actual_units=actual_units,
            unit_type="request",
            billable=False,
            occurred_at=now,
        )
    )
