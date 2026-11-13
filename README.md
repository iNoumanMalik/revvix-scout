# Revvix Scout

Revvix Scout is a free-first lead intelligence platform for discovering, researching, enriching, and qualifying potential customers for Revvix AI. It is designed around two independent prospect pipelines—individual professionals and businesses—backed by shared evidence, entity resolution, qualification, budget control, and reporting capabilities.

> Status: M3 through the approved provider-free M7 scope are complete and acceptance-tested against isolated local PostgreSQL. M7 adds grounded fictional opportunity analysis, versioned prompts/taxonomy, citation enforcement, budget accounting, injection exclusion, and final human review. No live personal data, live LLM/provider, outreach, paid-credit, hosted-Supabase, or cloud call is enabled.

## Product principles

- Evidence before inference: verified observations, provider data, and AI hypotheses remain distinguishable.
- Thin discovery before deep enrichment: spend time and provider credits only on promising, non-duplicate candidates.
- Human approval before communication: the system may draft outreach, but it does not send it automatically.
- Provider independence: external services sit behind adapters and can be replaced or disabled.
- Modular monolith first: keep deployment and operations simple while preserving clear domain boundaries.
- Privacy and compliance by design: business-relevant data only, suppression honored everywhere, and access controlled by workspace.

## Planning documents

- [Product requirements](docs/PRODUCT_REQUIREMENTS.md)
- [Proposed architecture](docs/ARCHITECTURE.md)
- [Database design](docs/DATABASE_DESIGN.md)
- [Implementation roadmap](docs/ROADMAP.md)
- [External services and credentials](docs/EXTERNAL_SERVICES.md)
- [CSV import contract](docs/CSV_IMPORT_V1.md)
- [Migration and recovery notes](docs/MIGRATIONS.md)
- [Approved MVP decisions](docs/APPROVED_MVP_DECISIONS.md)
- [Compliance and retention](docs/COMPLIANCE_AND_RETENTION.md)
- [M3 discovery contract](docs/DISCOVERY_M3.md)
- [Discovery CSV v1 contract](docs/DISCOVERY_CSV_V1.md)
- [M4 fictional individual discovery contract](docs/INDIVIDUAL_DISCOVERY_M4.md)
- [M5 fictional decision-maker research contract](docs/DECISION_MAKERS_M5.md)
- [M6 enrichment and entity-resolution foundation](docs/ENRICHMENT_M6.md)
- [M7 AI qualification and opportunity-detection contract](docs/AI_QUALIFICATION_M7.md)
- [Repository instructions](AGENTS.md)

## Implemented M2A workflow

The first vertical slice now supports:

1. Import business candidates from a fixture or CSV.
2. Normalize names, domains, and locations and reject exact duplicates.
3. Attach source-backed evidence supplied in the import.
4. Score candidates with deterministic, versioned ICP rules.
5. Expose list/detail endpoints and a formula-safe CSV export.

This proves the core data boundaries and business rules without paid credits, web scraping, LLM use, email discovery, or outbound communication. The accepted scope and test criteria remain in [the roadmap](docs/ROADMAP.md#recommended-first-build-m2a-provider-free-business-qualification-slice).

## Local development

Prerequisites are Python 3.12, Docker Desktop (or a compatible runtime), and the Supabase CLI. M3 has no external-service credentials. Alembic remains the canonical schema migration history inside the local Supabase PostgreSQL instance.

Create an environment and install the fully pinned dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
```

Start the local Supabase stack after installing the CLI. Homebrew installation may require current Xcode Command Line Tools; the pinned official npm runner is the supported fallback. Always confirm commands against the pinned version:

```bash
npx --yes supabase@3.1.0 --help
npx --yes supabase@3.1.0 start
npx --yes supabase@3.1.0 status
```

Copy the local direct PostgreSQL connection from `supabase status`, configure `SCOUT_DATABASE_URL` with the `postgresql+psycopg://` SQLAlchemy scheme, and apply migrations:

```bash
export SCOUT_DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'
.venv/bin/alembic upgrade head
```

Run the API:

```bash
.venv/bin/uvicorn revvix_scout.main:app --host 127.0.0.1 --port 8000
```

Run the separate local discovery worker after the database is migrated:

```bash
.venv/bin/revvix-scout-worker
```

The worker drains at most 25 due jobs per cycle and waits one second when the queue is not full. Override those bounded settings with `SCOUT_WORKER_BATCH_SIZE` and `SCOUT_WORKER_POLL_SECONDS`. `SIGINT` and `SIGTERM` stop it gracefully after the current adapter operation settles.

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`. Import a fixture with:

```bash
curl -F 'file=@tests/fixtures/businesses_v1.csv;type=text/csv' \
  http://127.0.0.1:8000/v1/imports/business-csv
```

Run a fictional discovery page with:

```bash
curl -X POST http://127.0.0.1:8000/v1/discovery-runs \
  -H 'content-type: application/json' \
  -d '{"provider_key":"fictional_accounting_directory","search_text":"independent accounting firms","country_code":"GB","region":"England","limit":25,"idempotency_key":"local-discovery-001"}'
```

With the M4 migration applied to an isolated database, run fictional individual discovery with:

```bash
curl -X POST http://127.0.0.1:8000/v1/individual-discovery-runs \
  -H 'content-type: application/json' \
  -d '{"provider_key":"fictional_professional_directory","search_text":"fictional consultants","country_code":"GB","region":"England","limit":25,"idempotency_key":"local-individual-discovery-001"}'
```

Import validated discovery candidates without a provider call with:

```bash
curl -F 'file=@tests/fixtures/discovery_candidates_v1.csv;type=text/csv' \
  -F 'idempotency_key=local-csv-discovery-001' \
  http://127.0.0.1:8000/v1/discovery-runs/csv
```

For tests, create a separate database. Integration tests truncate data in the configured database and must never target a shared or production database.

```bash
createdb revvix_scout_test
SCOUT_DATABASE_URL='postgresql+psycopg://localhost/revvix_scout_test' \
  .venv/bin/alembic upgrade head
SCOUT_DATABASE_URL='postgresql+psycopg://localhost/revvix_scout_test' \
  .venv/bin/pytest
```

Run static checks with:

```bash
.venv/bin/ruff check src tests alembic
.venv/bin/ruff format --check src tests alembic
.venv/bin/mypy src/revvix_scout
```

See [migration and recovery notes](docs/MIGRATIONS.md) before changing the schema.

## Repository shape

Scout uses a compact modular-monolith layout:

```text
revvix-scout/
├── src/revvix_scout/
│   ├── api/                    # FastAPI routes
│   ├── application/            # CSV import, queries, bootstrap, contracts
│   ├── db/                     # SQLAlchemy models and sessions
│   ├── domain/                 # Pure normalization and scoring rules
│   └── providers/              # Vendor-neutral ports and fictional adapters
├── alembic/                    # Reviewed PostgreSQL migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/                       # Product, architecture, and contracts
├── pyproject.toml
├── requirements.lock
├── AGENTS.md
└── README.md
```

## Scope boundary

M3 uses one deterministic development workspace and the approved configurable England accounting-firm ICP. M4 adds a separate fictional-only individual candidate path. M5 adds fictional-only, company-scoped decision-maker role research with a separate operation budget and no contact fields. M6 adds fictional enrichment and review-first entity resolution. M7 adds deterministic, fictional, tool-free opportunity analysis; it does not enable a live LLM. Authentication/RLS membership policies remain an M2 dependency before any client or hosted use. The system does not include live people/contact collection, fuzzy auto-merging, live AI analysis, recurring scheduling, a frontend, deployment, or outreach. No paid service, hosted infrastructure, production migration, deployment, or external message is authorized.
