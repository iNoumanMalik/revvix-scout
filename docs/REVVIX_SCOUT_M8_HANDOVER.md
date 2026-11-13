# Revvix Scout — M8 Completion & Project Handover

**Status as reported:** Milestone 8 complete (of 11)  
**Document date:** November 13, 2026  
**Purpose:** Preserve important product status, operating instructions, limitations, and next steps independently of any Codex or ChatGPT conversation or subscription.

> **Important distinction:** Revvix Scout is currently a usable local lead-processing and qualification application, but it does **not** autonomously discover or scrape real leads from the internet. All implementation and test claims below are a snapshot supplied by the project's developer, not an independent code audit.

## 1. Executive summary

Revvix Scout is complete through M8 and usable locally. It supports business CSV import, validation, deterministic ICP scoring, evidence records, qualification, filtering, review workflows, exports, job controls, quotas, and a local React dashboard. However, its discovery, enrichment, decision-maker research, and opportunity analysis currently use fictional adapters or manually supplied data. No live Firecrawl, Companies House, Apollo, Clay, or LLM connection is yet implemented. No outreach is sent.

**Reported tests:** 115 backend tests and 12 frontend tests.

**Recommended priority:** Before starting the full M9, consider a tightly scoped live, business-only discovery pilot using Companies House and/or Firecrawl, with a very small hard quota, no personal contacts, no paid credits, and no outreach. M9's scheduling and monitoring will not, by itself, provide real web discovery.

## 2. What is already built

- Business CSV import with validation and deduplication.
- Deterministic ICP scoring for accounting and bookkeeping firms based in England.
- Evidence URLs and observation timestamps.
- Lead qualification, filtering, detail views, and CSV export.
- Provider-adapter architecture.
- Jobs, retries, idempotency, quotas, usage tracking, and hard budget controls.
- Fictional business and individual discovery.
- Fictional decision-maker research.
- Fictional enrichment and duplicate/entity review.
- Evidence-grounded opportunity hypotheses.
- Human review queues and reversible review decisions.
- Local React dashboard with authentication and role foundations.
- Responsive and keyboard-accessible interface.
- PostgreSQL migrations, row-level security safeguards, and audit records.
- 115 backend tests and 12 frontend tests.

## 3. Real internet lead discovery — current capability

### What the system can do

- Import manually prepared business CSV files.
- Process fictional discovery adapters.
- Normalize, deduplicate, score, review, and export imported records.
- Store source attribution supplied with records.

### What the system cannot yet do

- Visit or verify a supplied `source_url`; currently this is stored as provenance only.
- Search Google or the wider web.
- Call Firecrawl, Companies House, Apollo, or Clay.
- Collect real decision-makers or professional contact details.
- Run a live LLM.
- Send outreach.

**Conclusion:** It is a strong lead-processing and qualification foundation, but not yet a live lead collection tool.

## 4. Repository and runtime

Repository root (local Mac):

```
/Users/nouman/Documents/Code/Revvix/Github/revvix-scout
```

The development environment uses Python 3.12, a local Supabase PostgreSQL instance, a FastAPI application, a separate worker process, and a Vite React dashboard. Use four terminal tabs for database, API, worker, and dashboard after the initial installation.

### 4.1 First-time installation

```bash
cd /Users/nouman/Documents/Code/Revvix/Github/revvix-scout

python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation

cd apps/web
npm ci
cd ../..
```

### 4.2 Start the local database

```bash
cd /Users/nouman/Documents/Code/Revvix/Github/revvix-scout

npx --yes supabase@3.1.0 start
npx --yes supabase@3.1.0 status
```

Configure the database connection and apply migrations:

```bash
export SCOUT_DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'

.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

Keep the local database running.

### 4.3 Start the API (separate terminal)

```bash
cd /Users/nouman/Documents/Code/Revvix/Github/revvix-scout

export SCOUT_DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'

.venv/bin/uvicorn revvix_scout.main:app \
  --host 127.0.0.1 \
  --port 8000
```

Verification URLs:

- API health: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

### 4.4 Start the worker (separate terminal)

```bash
cd /Users/nouman/Documents/Code/Revvix/Github/revvix-scout

export SCOUT_DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres'

.venv/bin/revvix-scout-worker
```

Keep the worker running while testing queued discovery jobs.

### 4.5 Start the dashboard (separate terminal)

```bash
cd /Users/nouman/Documents/Code/Revvix/Github/revvix-scout/apps/web

npm run dev
```

Open http://127.0.0.1:5173. The local application automatically uses the deterministic development owner, so a login is not required in this development mode. This behavior is **not** a production authentication recommendation.

## 5. Load and test sample data

Run the following commands from the repository root with the API (and for queued jobs, the worker) running.

### 5.1 Import sample business leads

```bash
curl -F 'file=@tests/fixtures/businesses_v1.csv;type=text/csv' \
  http://127.0.0.1:8000/v1/imports/business-csv
```

Refresh the dashboard to view imported and scored businesses.

### 5.2 Run fictional business discovery

```bash
curl -X POST http://127.0.0.1:8000/v1/discovery-runs \
  -H 'content-type: application/json' \
  -d '{
    "provider_key": "fictional_accounting_directory",
    "search_text": "independent accounting firms",
    "country_code": "GB",
    "region": "England",
    "limit": 25,
    "idempotency_key": "local-discovery-001"
  }'
```

### 5.3 Import fictional discovery candidates

```bash
curl -F 'file=@tests/fixtures/discovery_candidates_v1.csv;type=text/csv' \
  -F 'idempotency_key=local-csv-discovery-001' \
  http://127.0.0.1:8000/v1/discovery-runs/csv
```

Use a new `idempotency_key` when intentionally initiating a separate run.

## 6. Import your own business CSV

Authoritative reference in repository:

```
docs/CSV_IMPORT_V1.md
```

Required CSV columns, in documented order:

```text
schema_version
source_record_id
company_name
domain
country_code
employee_count
industry
technology_need
excluded_reason
source_url
observed_at
```

Import example:

```bash
curl -F 'file=@/absolute/path/to/your-leads.csv;type=text/csv' \
  http://127.0.0.1:8000/v1/imports/business-csv
```

**Data quality warning:** The importer trusts supplied fields as assertions from the input source. It does not verify the linked web page. Only import data obtained and retained in accordance with applicable laws and source terms.

## 7. Dashboard usage

1. Import a CSV or run fictional discovery.
2. Open **Lead intelligence**.
3. Filter by score and qualification status.
4. Select a lead to inspect its score and evidence.
5. Check that each assertion has a credible source.
6. Run fictional opportunity analysis where available.
7. Open **Review queues**.
8. Accept, reject, correct, or reopen eligible decisions.
9. Export the filtered lead list to CSV.
10. Conduct actual contact research outside Scout for now.

Authoritative dashboard manual in repository:

```
docs/DASHBOARD_M8.md
```

## 8. Milestone status and next development decision

| Milestone | Status | Notes |
| --- | --- | --- |
| M1–M4 | Complete (reported) | Architecture and foundational discovery features established. |
| M5–M8 | Complete (reported) | Lead processing, enrichment abstractions, AI hypothesis foundations, and UI. |
| Live discovery adapter | Not implemented | Needed before autonomous internet lead collection. |
| M9 | Not started in this handover | Scheduling, monitoring, and operational reliability. |
| M10 | Not started in this handover | Outreach drafts, approval, reporting. |
| M11 | Not started in this handover | Integration tests, security, production readiness. |

### Recommended narrowly scoped live discovery pilot

Implement **one** permitted business-only discovery adapter using Companies House and/or Firecrawl. Requirements:

- Search real companies, initially within the approved England accounting/bookkeeping ICP.
- No personal contact collection or enrichment.
- No outreach and no live LLM calls.
- No paid credits or infrastructure spend without approval.
- Tiny hard quota and fail-closed budget guardrails.
- Preserve source URLs, retrieval timestamps, and provider errors.
- Deduplicate and score through existing core services.
- Test with mocked provider responses first, then a small explicit pilot.
- Verify provider terms, allowed retention, and API access before connecting.
- Keep the adapter separate from core logic and include integration tests.

**Rationale:** M9 scheduling becomes more useful when at least one genuine data source is already integrated. The pilot should be a standalone, approved change rather than an unplanned scope expansion.

## 9. Continuity instructions for a future coding agent

When continuing this repository in Codex or another coding assistant:

1. Read this handover, `README.md`, `AGENTS.md`, `docs/CSV_IMPORT_V1.md`, `docs/DASHBOARD_M8.md`, the migration history, and the current implementation before proposing changes.
2. Treat this document as a dated snapshot. The repository and tests are the authoritative source of the **current** code state.
3. Do not assume real web scraping, real enrichment, live LLM calls, or sending has been implemented.
4. Run the test suite and inspect provider adapters, API routes, and jobs before stating a capability is ready.
5. Preserve hard budget caps, idempotency, retries, RLS, evidence provenance, and reversible human review decisions.
6. Obtain explicit approval before live data collection, nonzero spending, sending emails, external deployment, or destructive migrations.
7. Prefer the small live business discovery pilot if real lead collection is now the immediate product goal; otherwise follow the approved milestone roadmap.
8. Update this handover (or write a dated successor) after significant changes. Do not overwrite historical facts silently.

## 10. Quick verification checklist

- [ ] Local Supabase starts and `alembic current` confirms migration state.
- [ ] API responds at `/health` and documentation at `/docs`.
- [ ] Worker starts and can process fictional queued discovery.
- [ ] React dashboard loads on port 5173.
- [ ] Sample business CSV imports successfully.
- [ ] Leads are scored, filtered, reviewed, and exported correctly.
- [ ] Provider quotas and hard budget controls stop unapproved spending.
- [ ] Backend and frontend tests pass (historical baseline: 115 and 12).
- [ ] No claim of real discovery is made until a live adapter has been implemented and tested.

---

**Preservation recommendation:** Commit this Markdown file as `docs/PROJECT_HANDOVER_M8.md` in the private GitHub repository, and keep an exported `.docx` copy separately. The Git repository is the best durable source of truth for future coding agents even when a Codex subscription or chat history is unavailable.
