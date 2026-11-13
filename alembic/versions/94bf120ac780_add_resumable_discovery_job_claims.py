"""add resumable discovery job claims

Revision ID: 94bf120ac780
Revises: 6b870e036374
Create Date: 2026-11-13 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "94bf120ac780"
down_revision: str | None = "6b870e036374"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Server defaults make this additive migration safe for existing M3 rows. The
    # application owns new-row defaults after the columns have been backfilled.
    op.add_column(
        "jobs",
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        schema="scout",
    )
    op.add_column(
        "jobs",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="scout",
    )
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)), schema="scout")
    op.add_column("jobs", sa.Column("worker_id", sa.String(length=120)), schema="scout")
    op.create_check_constraint(
        op.f("ck_jobs_max_attempts_valid"),
        "jobs",
        "max_attempts > 0 and max_attempts <= 10",
        schema="scout",
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["next_attempt_at", "created_at"],
        unique=False,
        schema="scout",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.add_column(
        "job_attempts",
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="scout",
    )
    op.create_unique_constraint(
        op.f("uq_discovery_runs_job_id"), "discovery_runs", ["job_id"], schema="scout"
    )
    op.create_index(
        "ix_budget_reservations_run_status",
        "budget_reservations",
        ["discovery_run_id", "status"],
        unique=False,
        schema="scout",
    )
    op.create_index(
        "ix_provider_usage_events_run_occurred",
        "provider_usage_events",
        ["discovery_run_id", "occurred_at"],
        unique=False,
        schema="scout",
    )
    op.alter_column("jobs", "max_attempts", server_default=None, schema="scout")
    op.alter_column("jobs", "next_attempt_at", server_default=None, schema="scout")
    op.alter_column("job_attempts", "retryable", server_default=None, schema="scout")


def downgrade() -> None:
    op.drop_index(
        "ix_provider_usage_events_run_occurred",
        table_name="provider_usage_events",
        schema="scout",
    )
    op.drop_index(
        "ix_budget_reservations_run_status",
        table_name="budget_reservations",
        schema="scout",
    )
    op.drop_constraint(
        op.f("uq_discovery_runs_job_id"),
        "discovery_runs",
        schema="scout",
        type_="unique",
    )
    op.drop_column("job_attempts", "retryable", schema="scout")
    op.drop_index("ix_jobs_claimable", table_name="jobs", schema="scout")
    op.drop_constraint(op.f("ck_jobs_max_attempts_valid"), "jobs", schema="scout", type_="check")
    op.drop_column("jobs", "worker_id", schema="scout")
    op.drop_column("jobs", "lease_expires_at", schema="scout")
    op.drop_column("jobs", "next_attempt_at", schema="scout")
    op.drop_column("jobs", "max_attempts", schema="scout")
