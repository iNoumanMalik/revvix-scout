import json
import logging
import threading

from sqlalchemy.orm import Session, sessionmaker

from revvix_scout.config import Settings
from revvix_scout.providers.registry import create_provider_registry
from revvix_scout.worker import WorkerCycleResult, _log, run_worker_loop


def test_worker_loop_stops_without_sleeping_after_signal() -> None:
    stop_event = threading.Event()
    calls = 0

    def one_cycle(**_: object) -> WorkerCycleResult:
        nonlocal calls
        calls += 1
        stop_event.set()
        return WorkerCycleResult(processed=0, succeeded=0, failed=0, requeued=0, idle=True)

    logger = logging.getLogger("revvix_scout.worker")
    logger.setLevel(logging.INFO)
    run_worker_loop(
        session_factory=sessionmaker(class_=Session),
        settings=Settings(worker_poll_seconds=60),
        registry=create_provider_registry(),
        worker_id="test-worker",
        stop_event=stop_event,
        cycle=one_cycle,
    )

    assert calls == 1


def test_worker_operational_log_shape_contains_no_payload(caplog: object) -> None:
    with caplog.at_level(logging.INFO, logger="revvix_scout.worker"):  # type: ignore[attr-defined]
        _log(
            logging.INFO,
            "discovery_run_processed",
            worker_id="test-worker",
            run_id="run-id",
            status="succeeded",
            provider_key="manual_input",
        )

    payload = json.loads(caplog.records[-1].message)  # type: ignore[attr-defined]
    assert payload == {
        "event": "discovery_run_processed",
        "provider_key": "manual_input",
        "run_id": "run-id",
        "status": "succeeded",
        "worker_id": "test-worker",
    }
