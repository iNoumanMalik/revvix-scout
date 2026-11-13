# M3 discovery contract

M3 executes one bounded discovery page through a vendor-neutral adapter. The enabled adapters are the fictional accounting directory, validated manual input, and strict CSV input. All are non-live and non-billable. Companies House, Firecrawl, search APIs, Apollo, and Clay still have no credential path or live adapter.

## Invariants

- A workspace provider configuration must be enabled. A future live adapter additionally requires `live_calls_allowed` and an approved terms review.
- A matching hard budget policy is mandatory, including zero-unit manual and CSV operations. Units are reserved in the claim transaction before an adapter call and settled on every success or failure.
- Jobs and request payloads are idempotent. One discovery run belongs to one job, and provider record IDs are unique within a run.
- Workers claim due jobs with `FOR UPDATE OF jobs SKIP LOCKED`, commit the short claim transaction, and call adapters outside database locks.
- Each worker cycle is bounded by `SCOUT_WORKER_BATCH_SIZE`; each job uses a short-lived SQLAlchemy session backed by the process connection pool.
- Every attempt is immutable after settlement. Transient provider errors retry at one and two seconds, up to three total attempts. A five-minute lease permits recovery after a worker crash.
- Exact registrable-domain deduplication happens before any future enrichment.
- Candidates retain source URL, provider record ID, observed time, assertion classification, and adapter kind. Raw CSV bytes, raw provider payloads, and secrets are not stored.
- Dormant/out-of-ICP records are rejected or routed to review by the persisted ICP version.

## API

- `POST /v1/discovery-runs` runs the fictional provider.
- `POST /v1/discovery-runs/manual` accepts allow-listed JSON records.
- `POST /v1/discovery-runs/csv` accepts the [discovery CSV v1 contract](DISCOVERY_CSV_V1.md).
- `POST /v1/discovery-runs/{id}/resume` attempts to claim a due queued or lease-expired run. An already running, terminal, or not-yet-due run is returned unchanged.
- `GET /v1/discovery-runs/{id}` returns run, retry, and allow-listed candidate state.

The inline API and `revvix-scout-worker` use the same enqueue/claim/settle flow. The worker polls with an interruptible wait, does not hold a database connection while idle, and exits gracefully on `SIGINT` or `SIGTERM` after the current adapter operation settles. It processes one page per run. A returned `next_cursor` can be supplied to a new idempotent run.

Worker logs are structured JSON and contain only event names, worker/run identifiers, provider keys, statuses, signal numbers, and exception class names. Candidate payloads, query text, source content, secrets, and exception messages are excluded.

## Failure behavior

Unknown or disabled providers fail closed. Missing or insufficient budgets fail before adapter execution. Stable adapter failures record category, retryability, attempt, reservation, and usage outcome. Candidate persistence uses a savepoint so a malformed page cannot leave only a prefix of its candidates. Retry exhaustion is terminal with the run-level code `attempts_exhausted`; the final provider category remains on the attempt record.

Lease recovery marks abandoned attempts as `lease_expired` and releases their unspent reservation before a new attempt. It does not fabricate usage for an adapter whose outcome is unknown; a future live adapter must use provider request IDs or reconciliation when its terms permit ambiguous billable outcomes.

The acceptance suite covers adapter pagination, idempotency, provider disablement, pre-call budget denial, overlapping-worker reservation safety, transient recovery, permanent failure, retry exhaustion, expired-lease recovery, raw-file omission, safe logs, and row-lock concurrency.
