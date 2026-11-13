from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from revvix_scout.application.discovery import enqueue_discovery
from revvix_scout.config import get_settings
from revvix_scout.db.models import Job
from revvix_scout.providers.contracts import DiscoveryQuery
from revvix_scout.providers.registry import create_provider_registry
from revvix_scout.worker import run_worker_cycle


def test_worker_cycle_honors_batch_limit_and_drains_due_jobs(client: TestClient) -> None:
    del client
    settings = get_settings()
    registry = create_provider_registry()
    engine = create_engine(settings.database_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as session:
        first = enqueue_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key="fictional_accounting_directory",
            query=DiscoveryQuery(search_text="worker accounting firms one"),
            idempotency_key="worker-discovery-001",
        )
        second = enqueue_discovery(
            session=session,
            settings=settings,
            registry=registry,
            provider_key="fictional_accounting_directory",
            query=DiscoveryQuery(search_text="worker accounting firms two"),
            idempotency_key="worker-discovery-002",
        )

    first_cycle = run_worker_cycle(
        session_factory=factory,
        settings=settings,
        registry=registry,
        worker_id="integration-worker",
        max_jobs=1,
    )
    assert first_cycle.processed == 1
    assert first_cycle.succeeded == 1
    assert first_cycle.idle is False

    with factory() as session:
        queued = session.scalar(select(func.count()).select_from(Job).where(Job.status == "queued"))
        jobs = (session.get(Job, first.job_id), session.get(Job, second.job_id))
        assert all(job is not None for job in jobs)
        statuses = {job.status for job in jobs if job is not None}
    assert queued == 1
    assert statuses == {"queued", "succeeded"}

    second_cycle = run_worker_cycle(
        session_factory=factory,
        settings=settings,
        registry=registry,
        worker_id="integration-worker",
        max_jobs=25,
    )
    assert second_cycle.processed == 1
    assert second_cycle.succeeded == 1
    assert second_cycle.idle is True

    idle_cycle = run_worker_cycle(
        session_factory=factory,
        settings=settings,
        registry=registry,
        worker_id="integration-worker",
        max_jobs=25,
    )
    assert idle_cycle == type(idle_cycle)(0, 0, 0, 0, True)
    engine.dispose()
