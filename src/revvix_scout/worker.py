"""Local PostgreSQL-backed discovery worker process."""

import json
import logging
import os
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import FrameType
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from revvix_scout.application.bootstrap import bootstrap_defaults
from revvix_scout.application.discovery import DiscoveryError, process_next_discovery_run
from revvix_scout.config import Settings, get_settings
from revvix_scout.db.session import get_session_factory
from revvix_scout.providers.contracts import ProviderNotRegisteredError, ProviderRegistry
from revvix_scout.providers.registry import create_provider_registry

logger = logging.getLogger("revvix_scout.worker")


@dataclass(frozen=True, slots=True)
class WorkerCycleResult:
    """Safe operational summary for one bounded queue-drain cycle."""

    processed: int
    succeeded: int
    failed: int
    requeued: int
    idle: bool


def run_worker_cycle(
    *,
    session_factory: sessionmaker[Session],
    settings: Settings,
    registry: ProviderRegistry,
    worker_id: str,
    max_jobs: int,
    now: datetime | None = None,
) -> WorkerCycleResult:
    """Process at most ``max_jobs`` due runs using one session per job."""

    processed = succeeded = failed = requeued = 0
    idle = False
    for _ in range(max_jobs):
        try:
            with session_factory() as session:
                run = process_next_discovery_run(
                    session=session,
                    settings=settings,
                    registry=registry,
                    worker_id=worker_id,
                    now=now,
                )
                summary = None if run is None else (str(run.id), run.status, run.provider_key)
        except (DiscoveryError, ProviderNotRegisteredError, SQLAlchemyError) as exc:
            _log(
                logging.ERROR,
                "worker_cycle_error",
                worker_id=worker_id,
                error_type=type(exc).__name__,
            )
            break
        if summary is None:
            idle = True
            break
        run_id, status, provider_key = summary
        processed += 1
        if status == "succeeded":
            succeeded += 1
        elif status == "queued":
            requeued += 1
        elif status == "failed":
            failed += 1
        _log(
            logging.INFO,
            "discovery_run_processed",
            worker_id=worker_id,
            run_id=run_id,
            status=status,
            provider_key=provider_key,
        )
    return WorkerCycleResult(processed, succeeded, failed, requeued, idle)


def run_worker_loop(
    *,
    session_factory: sessionmaker[Session],
    settings: Settings,
    registry: ProviderRegistry,
    worker_id: str,
    stop_event: threading.Event,
    cycle: Callable[..., WorkerCycleResult] = run_worker_cycle,
) -> None:
    """Poll until interrupted, sleeping without holding a database connection."""

    _log(logging.INFO, "worker_started", worker_id=worker_id)
    while not stop_event.is_set():
        result = cycle(
            session_factory=session_factory,
            settings=settings,
            registry=registry,
            worker_id=worker_id,
            max_jobs=settings.worker_batch_size,
        )
        if result.processed == settings.worker_batch_size:
            continue
        stop_event.wait(settings.worker_poll_seconds)
    _log(logging.INFO, "worker_stopped", worker_id=worker_id)


def run() -> None:
    """Bootstrap and run the provider-free worker until SIGINT or SIGTERM."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    session_factory = get_session_factory()
    with session_factory() as session:
        bootstrap_defaults(session, settings)

    stop_event = threading.Event()
    worker_id = f"local-{os.getpid()}-{str(uuid4())[:8]}"

    def request_stop(signum: int, _: FrameType | None) -> None:
        _log(logging.INFO, "worker_stop_requested", worker_id=worker_id, signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    run_worker_loop(
        session_factory=session_factory,
        settings=settings,
        registry=create_provider_registry(),
        worker_id=worker_id,
        stop_event=stop_event,
    )


def _log(level: int, event: str, **fields: object) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, sort_keys=True))


if __name__ == "__main__":
    run()
