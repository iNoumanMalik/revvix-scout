# M3 discovery contract

M3 executes one bounded discovery page through a vendor-neutral adapter. The only enabled adapter is `fictional_accounting_directory`; its records and `.invalid` source URLs are fictional. Companies House, Firecrawl, search APIs, Apollo, and Clay have no live adapter or credential path in this milestone.

## Invariants

- A workspace provider configuration must be enabled. A live adapter additionally requires `live_calls_allowed` and an approved terms review.
- A matching hard budget policy is mandatory. Units are reserved in the same transaction before calling the adapter and settled on success or failure.
- Jobs and request payloads are idempotent. Provider record IDs are unique within a run.
- Exact registrable-domain deduplication happens before any future enrichment.
- Candidates retain source URL, provider record ID, observed time, assertion classification, and adapter kind. Raw provider payloads and secrets are not stored.
- Dormant/out-of-ICP records are rejected or routed to review by the persisted ICP version.

## API

`POST /v1/discovery-runs` accepts a provider key, bounded query, cursor, limit, and idempotency key. `GET /v1/discovery-runs/{id}` returns run state and allow-listed candidates. M3 processes one page synchronously; `next_cursor` can be submitted in a new run. Later worker milestones will resume partial and transient failures using persisted jobs/attempts.

## Failure behavior

Unknown/disabled providers fail closed. Missing or insufficient budgets fail before adapter execution. Adapter failures are stored on the run and job; a non-billable fixture usage event is still recorded so every attempted provider operation is auditable.
