import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from revvix_scout.application.discovery import (
    enqueue_discovery,
    execute_discovery,
    process_discovery_run,
)
from revvix_scout.config import get_settings
from revvix_scout.db.models import (
    BudgetReservation,
    DiscoveryCandidate,
    DiscoveryRun,
    Job,
    JobAttempt,
    ProviderUsageEvent,
)
from revvix_scout.providers.contracts import (
    DiscoveredBusiness,
    DiscoveryPage,
    DiscoveryQuery,
    ProviderExecutionError,
    ProviderRegistry,
)
from revvix_scout.providers.fixture import FictionalAccountingProvider


class _TransientThenSuccessfulProvider:
    key = "fictional_accounting_directory"
    is_live = False

    def __init__(self) -> None:
        self.calls = 0

    def estimate_units(self, query: DiscoveryQuery) -> int:
        return 1

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        self.calls += 1
        if self.calls == 1:
            raise ProviderExecutionError(
                "temporary_unavailable", "temporary fictional failure", retryable=True
            )
        return DiscoveryPage(
            candidates=(
                DiscoveredBusiness(
                    provider_record_id="retry-001",
                    company_name="Fictional Retry Accountants",
                    domain="retry-accountants.example.co.uk",
                    country_code="GB",
                    region="England",
                    industry="accounting",
                    employee_count=12,
                    legal_form="Ltd",
                    company_status="active",
                    source_url="https://retry-accountants.invalid/about",
                    observed_at=datetime(2026, 11, 1, tzinfo=UTC),
                ),
            ),
            next_cursor=None,
            actual_units=1,
        )


class _AlwaysFailingProvider:
    key = "fictional_accounting_directory"
    is_live = False

    def __init__(self, *, retryable: bool, actual_units: int = 0) -> None:
        self.retryable = retryable
        self.actual_units = actual_units
        self.calls = 0

    def estimate_units(self, query: DiscoveryQuery) -> int:
        return 1

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        self.calls += 1
        raise ProviderExecutionError(
            "fictional_permanent" if not self.retryable else "fictional_transient",
            "fictional provider failure",
            retryable=self.retryable,
            actual_units=self.actual_units,
        )


class _BlockingSuccessfulProvider:
    key = "fictional_accounting_directory"
    is_live = False

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def estimate_units(self, query: DiscoveryQuery) -> int:
        return 1

    def discover(self, query: DiscoveryQuery) -> DiscoveryPage:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise ProviderExecutionError(
                "test_timeout", "test did not release provider", retryable=False
            )
        return DiscoveryPage(candidates=(), next_cursor=None, actual_units=1)


def test_transient_failure_requeues_and_resumes_without_duplicate_candidates(
    client: TestClient,
) -> None:
    del client  # startup bootstraps the isolated database used below
    settings = get_settings()
    provider = _TransientThenSuccessfulProvider()
    registry = ProviderRegistry((provider,))
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        run = execute_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key=provider.key,
            query=DiscoveryQuery(search_text="retry accounting firms"),
            idempotency_key="retry-discovery-001",
        )
        assert run.status == "queued"
        job = session.get(Job, run.job_id)
        assert job is not None
        assert job.next_attempt_at is not None

        resumed = process_discovery_run(
            session=session,
            settings=settings,
            registry=registry,
            run_id=run.id,
            worker_id="test-worker",
            now=job.next_attempt_at,
        )
        assert resumed.status == "succeeded"

        attempts = session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id)
            .order_by(JobAttempt.attempt_number)
        ).all()
        assert [(item.status, item.retryable) for item in attempts] == [
            ("failed", True),
            ("succeeded", False),
        ]
        assert (
            session.scalar(
                select(func.count())
                .select_from(DiscoveryCandidate)
                .where(DiscoveryCandidate.discovery_run_id == run.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProviderUsageEvent)
                .where(ProviderUsageEvent.discovery_run_id == run.id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(BudgetReservation)
                .where(
                    BudgetReservation.discovery_run_id == run.id,
                    BudgetReservation.status == "active",
                )
            )
            == 0
        )
    engine.dispose()


def test_locked_job_is_skipped_instead_of_double_claimed(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _TransientThenSuccessfulProvider()
    registry = ProviderRegistry((provider,))
    engine = create_engine(settings.database_url)

    with Session(engine) as creator:
        run = execute_discovery(
            session=creator,
            settings=settings,
            registry=registry,
            provider_key=provider.key,
            query=DiscoveryQuery(search_text="locked accounting firms"),
            idempotency_key="locked-discovery-001",
        )
        assert run.status == "queued"
        run_id = run.id
        job_id = run.job_id

    with Session(engine) as lock_holder, Session(engine) as competing_worker:
        lock_holder.execute(text("set local lock_timeout = '250ms'"))
        locked = lock_holder.scalar(select(Job).where(Job.id == job_id).with_for_update())
        assert locked is not None

        unchanged = process_discovery_run(
            session=competing_worker,
            settings=settings,
            registry=registry,
            run_id=run_id,
            worker_id="competing-worker",
        )
        assert unchanged.status == "queued"
        assert (
            competing_worker.scalar(
                select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == job_id)
            )
            == 1
        )
    engine.dispose()


def test_permanent_provider_failure_is_terminal_and_auditable(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _AlwaysFailingProvider(retryable=False, actual_units=1)
    registry = ProviderRegistry((provider,))
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        run = execute_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key=provider.key,
            query=DiscoveryQuery(search_text="permanent failure accounting firms"),
            idempotency_key="permanent-failure-001",
        )
        job = session.get(Job, run.job_id)
        assert job is not None
        attempts = session.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id)).all()
        usage = session.scalar(
            select(ProviderUsageEvent).where(ProviderUsageEvent.discovery_run_id == run.id)
        )

        assert run.status == job.status == "failed"
        assert run.error_code == "fictional_permanent"
        assert provider.calls == 1
        assert [(item.status, item.retryable) for item in attempts] == [("failed", False)]
        assert usage is not None
        assert (usage.outcome, usage.actual_units) == ("partial", 1)
    engine.dispose()


def test_transient_failure_exhausts_exactly_three_attempts(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _AlwaysFailingProvider(retryable=True)
    registry = ProviderRegistry((provider,))
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        run = execute_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key=provider.key,
            query=DiscoveryQuery(search_text="exhaust retries accounting firms"),
            idempotency_key="retry-exhaustion-001",
        )
        for _ in range(2):
            job = session.get(Job, run.job_id)
            assert job is not None
            run = process_discovery_run(
                session=session,
                settings=settings,
                registry=registry,
                run_id=run.id,
                worker_id="retry-exhaustion-worker",
                now=job.next_attempt_at,
            )

        job = session.get(Job, run.job_id)
        assert job is not None
        attempts = session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id)
            .order_by(JobAttempt.attempt_number)
        ).all()
        usage_count = session.scalar(
            select(func.count())
            .select_from(ProviderUsageEvent)
            .where(ProviderUsageEvent.discovery_run_id == run.id)
        )

        assert run.status == job.status == "failed"
        assert run.error_code == "attempts_exhausted"
        assert provider.calls == job.max_attempts == 3
        assert [item.attempt_number for item in attempts] == [1, 2, 3]
        assert all(item.status == "failed" and item.retryable for item in attempts)
        assert usage_count == 3
    engine.dispose()


def test_expired_lease_releases_reservation_and_recovers(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = FictionalAccountingProvider()
    registry = ProviderRegistry((provider,))
    engine = create_engine(settings.database_url)
    now = datetime.now(UTC)

    with Session(engine) as session:
        run = enqueue_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key=provider.key,
            query=DiscoveryQuery(search_text="lease recovery accounting firms"),
            idempotency_key="lease-recovery-001",
        )
        job = session.get(Job, run.job_id)
        assert job is not None
        abandoned_attempt = JobAttempt(
            id=uuid4(),
            job_id=job.id,
            attempt_number=1,
            status="running",
            started_at=now - timedelta(minutes=10),
            retryable=False,
        )
        abandoned_reservation = BudgetReservation(
            id=uuid4(),
            workspace_id=settings.default_workspace_id,
            discovery_run_id=run.id,
            provider_key=provider.key,
            operation="business_discovery",
            reserved_units=1,
            status="active",
            reserved_at=now - timedelta(minutes=10),
            expires_at=now - timedelta(minutes=5),
        )
        session.add_all((abandoned_attempt, abandoned_reservation))
        job.status = run.status = "running"
        job.worker_id = "abandoned-worker"
        job.lease_expires_at = now - timedelta(minutes=1)
        session.commit()

        recovered = process_discovery_run(
            session=session,
            settings=settings,
            registry=registry,
            run_id=run.id,
            worker_id="recovery-worker",
            now=now,
        )
        session.refresh(abandoned_attempt)
        session.refresh(abandoned_reservation)
        attempts = session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id)
            .order_by(JobAttempt.attempt_number)
        ).all()

        assert recovered.status == "succeeded"
        assert (abandoned_attempt.status, abandoned_attempt.error_category) == (
            "failed",
            "lease_expired",
        )
        assert abandoned_reservation.status == "released"
        assert abandoned_reservation.settled_units == 0
        assert [(item.attempt_number, item.status) for item in attempts] == [
            (1, "failed"),
            (2, "succeeded"),
        ]
    engine.dispose()


def test_concurrent_workers_create_only_one_budget_reservation(client: TestClient) -> None:
    del client
    settings = get_settings()
    provider = _BlockingSuccessfulProvider()
    registry = ProviderRegistry((provider,))
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        run = enqueue_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key=provider.key,
            query=DiscoveryQuery(search_text="concurrent budget accounting firms"),
            idempotency_key="budget-race-001",
        )
        run_id = run.id

    def process(worker_id: str) -> str:
        with Session(engine) as session:
            result = process_discovery_run(
                session=session,
                settings=settings,
                registry=registry,
                run_id=run_id,
                worker_id=worker_id,
            )
            return result.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(process, "budget-worker-one")
        assert provider.started.wait(timeout=5)
        second = pool.submit(process, "budget-worker-two")
        assert second.result(timeout=5) == "running"
        with Session(engine) as session:
            active_count = session.scalar(
                select(func.count())
                .select_from(BudgetReservation)
                .where(
                    BudgetReservation.discovery_run_id == run_id,
                    BudgetReservation.status == "active",
                )
            )
        assert active_count == 1
        provider.release.set()
        assert first.result(timeout=5) == "succeeded"

    with Session(engine) as session:
        reservation_count = session.scalar(
            select(func.count())
            .select_from(BudgetReservation)
            .where(BudgetReservation.discovery_run_id == run_id)
        )
        usage_count = session.scalar(
            select(func.count())
            .select_from(ProviderUsageEvent)
            .where(ProviderUsageEvent.discovery_run_id == run_id)
        )
        final_run = session.get(DiscoveryRun, run_id)
        assert final_run is not None
        assert final_run.status == "succeeded"
    assert provider.calls == 1
    assert reservation_count == usage_count == 1
    engine.dispose()
