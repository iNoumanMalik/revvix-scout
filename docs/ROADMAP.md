# Implementation roadmap

**Status:** M1, M2A, and the provider-free M3 core are implemented. M2 authentication remains required before client or hosted access.

## Delivery approach

Each milestone should end in a demonstrable vertical outcome, automated tests, updated documentation, and a go/no-go review. Provider adapters begin as fixtures. Live credentials, paid credits, hosted infrastructure, migrations against shared databases, deployments, and external messages are separate approvals.

## M1 — Architecture, requirements, repository foundation

**Outcome:** A reviewed technical and product baseline.

**Dependencies:** Product brief.

**Scope:** PRD, architecture, logical database design, roadmap, repository instructions, README, proposed folder structure, service/credential inventory, assumptions, risks, and first-slice recommendation.

**Acceptance criteria:**

- The two pipelines and shared capabilities have explicit boundaries.
- Facts, provider assertions, and hypotheses have distinct lifecycle rules.
- Database entities, relationships, constraints, indexes, and RLS approach are documented.
- Every later milestone has dependencies, expected outcome, acceptance criteria, and test intent.
- No infrastructure, migration, provider spend, deployment, or substantial application code is introduced.

**Tests/review:** Document link check, terminology consistency review, security/privacy review, stakeholder sign-off on open decisions.

## Recommended first build: M2A provider-free business qualification slice

**Implementation status:** Complete on 2026-11-13. The acceptance suite passes against local PostgreSQL with no network or provider credentials.

This is the smallest functional milestone worth implementing. It validates the core model before authentication complexity or vendor integration.

**User-visible outcome:** An operator can load a synthetic or manually prepared business CSV, receive normalized/deduplicated candidates, see evidence-backed deterministic scores through an API, and export the qualified set.

**Included:**

- Python workspace and pinned dependencies.
- Local PostgreSQL schema for a single development workspace: companies, domains, ICP/version, leads, source documents, evidence claims, score runs/components, and import job records.
- Versioned CSV contract with source URL, observed time, and evidence fields.
- Exact normalization/deduplication for registrable domain plus safe fallback fingerprints.
- One deterministic ICP rule set with explainable components and explicit missing-data behavior.
- FastAPI health, import, lead list/detail, and CSV export endpoints.
- Synthetic fixtures, migrations, unit/integration tests, and OpenAPI documentation.

**Excluded:** live scraping, Supabase Auth, hosted Supabase, fuzzy auto-merge, people/contacts, LLMs, paid/free provider APIs, n8n, frontend, Gmail, and deployment.

**Acceptance criteria:**

- Re-importing the same file is idempotent and does not create duplicate companies/leads/evidence.
- Same normalized domain resolves to one company; ambiguous no-domain records remain separate or enter review.
- Every score identifies the exact ICP version and component inputs.
- Every accepted score input links to imported evidence with source and timestamps.
- A malformed row fails clearly without losing valid rows; import result reports partial success.
- Export contains only allow-listed fields and neutralizes spreadsheet formulas.
- Tests run without network access, secrets, or paid credits.
- Migration can build a clean database and a documented downgrade/recovery path exists.

**Tests:** normalization and international domain cases; duplicate/idempotency properties; ICP boundary values and disqualifiers; missing evidence; malformed CSV; transaction rollback/partial success; pagination; export injection; migration smoke test.

**Decision gate:** Completed. The M2A schema/CSV contract and the approved England accounting-firm ICP now govern local development.

## M2 — Database, authentication, and backend foundation

**Outcome:** Secure multi-user backend foundation based on the proven M2A model.

**Dependencies:** M1 approval and M2A evidence; target tenant/role decisions.

**Scope:** Full initial schema, Supabase Auth integration, workspace membership, RLS/grants, migrations/seeds, typed settings, API error model, audit foundation, CI checks.

**Acceptance criteria:** Cross-workspace access is denied; roles match the approved matrix; secrets stay server-only; migrations reproduce schema from zero; health/readiness expose no sensitive data; audit captures privileged changes.

**Tests:** RLS matrix by role/resource/action, auth token validation, migration up/down or recovery, constraints/indexes, configuration failure, API contract, security advisor review.

## M3 — Provider interfaces and free-first discovery engine

**Implementation status:** Complete for the approved provider-free scope on 2026-11-13. The core, manual/CSV adapters, resumable job claims, separate local worker, and the full acceptance matrix—including budget races, permanent/transient failures, retry exhaustion, and lease recovery—are validated against isolated local PostgreSQL. Recurring schedules, operational deployment, and live adapters remain later gated work rather than M3 blockers.

**Outcome:** Bounded discovery runs work through adapters without binding core logic to a vendor.

**Dependencies:** Approved public-source policy and candidate contract. The user approved server-only M3 work ahead of unfinished M2 authentication; no browser/Data API or hosted access is enabled.

**Scope:** provider ports, adapter registry, discovery runs/candidates, cursors, thin eligibility, budgets, cache/license metadata, mock/manual/CSV adapters, job framework.

**Acceptance criteria:** Provider can be disabled/replaced by configuration; candidates preserve provenance; dedupe precedes enrichment; budget prevents calls before execution; partial provider failure is visible and resumable.

**Tests:** adapter contracts, pagination/cursor replay, idempotency, budget race, transient/permanent errors, disabled provider, raw payload redaction.

## M4 — Individual prospect discovery pipeline

**Implementation status:** Complete on 2026-11-13 for the approved fictional-only scope. Domain rules, typed adapter contract, fixture adapter, isolated discovery API, person promotion, explicit duplicate decisions, person-subject leads, hashed profile/person suppression, and acceptance tests are implemented. Revisions `410360f37f0b` and `20a7a62a7d6a` are applied to the isolated test database. The full 63-test suite passes with no schema drift. Live personal-data collection remains blocked on the dependency approvals below.

**Outcome:** Operators can discover and qualify public professional-business candidates independently of organizations.

**Dependencies:** M3; approved target personas/sources and privacy basis.

**Scope:** individual queries, person identity, public profiles, service/offering evidence, person-level lead workflow, manual duplicate review.

**Acceptance criteria:** Person names alone never auto-merge; professional presence and business relevance have evidence; pipeline can run with business discovery disabled; irrelevant/private-only records are rejected.

**Tests:** common-name collisions, profile URL normalization, individual/company ambiguity, source restrictions, suppression, pipeline isolation.

## M5 — Business discovery and decision-maker pipeline

**Implementation status:** Complete on 2026-11-13 for the approved fictional-only scope. The provider port and adapter, configurable and explainable role scoring, company-scoped API, separate budget operation, suppression-aware idempotent promotion, current/historical person-company role model, and pipeline-isolation controls are implemented. Revision `415f89420420` is applied to the isolated test database; the full 69-test suite and database security/drift checks pass. Live person research remains blocked by the provider and privacy gates below.

**Outcome:** Organizations are discovered and qualified first, then appropriate professional roles are identified.

**Dependencies:** M3; industry/company-size ICP decisions.

**Scope:** company discovery, domain identity, firmographic evidence, decision-maker role definitions, person-company roles, business lead workflow.

**Acceptance criteria:** One company can have multiple current/historical roles; role relevance is explainable; company and contact research have separate budgets; individual pipeline remains independent.

**Tests:** domain aliases/redirects, subsidiaries/franchises, role history, multiple decision makers, company-person dedupe, pipeline isolation.

## M6 — Enrichment waterfall, evidence, and entity resolution

**Implementation status:** Complete on 2026-11-13 for the approved provider-free, fictional-only scope. Versioned waterfalls, freshness and conflict handling, metadata-only enrichment, pre-call budget reservation, terminal usage settlement, durable evidence, exact/fuzzy review suggestions, operator review, and logical merge/unmerge recovery are implemented. Revisions `9e83bb75d0e3` and `c53cc7e9a80b` are applied to isolated local PostgreSQL; schema drift, RLS, grants, indexes, ledger integrity, concurrent reservation, and the full 85-test suite pass. A live adapter remains separately gated by provider-permission, privacy, sandbox, budget, and explicit enablement approval and is not required for the approved fictional milestone.

**Outcome:** Promising leads are enriched selectively with durable provenance and recoverable matching.

**Dependencies:** M4/M5 data; provider contract/license review.

**Scope:** versioned waterfalls, field freshness, source documents/claims, conflict handling, exact/fuzzy matching review, merge/unmerge, and an adapter boundary that permits at most one separately approved live provider at a time.

**Acceptance criteria:** No provider call without budget reservation; waterfall stops correctly; stale/conflicting claims remain visible; uncertain matches need review; merge history is recoverable; usage settles on all outcomes.

**Tests:** stop/fallback branches, cache expiry, conflicting claims, concurrent reservation, duplicate suggestions, and merge/unmerge integrity. A live-adapter sandbox smoke test is required only after a provider is separately approved.

## M7 — AI qualification and opportunity detection

**Outcome:** Evidence-grounded opportunity briefs augment deterministic qualification.

**Dependencies:** M6 evidence quality; approved LLM provider/data policy and opportunity taxonomy.

**Scope:** LLM port, structured outputs, prompt/version registry, evidence retrieval, opportunity hypotheses, contradiction/missing-data reporting, human review.

**Acceptance criteria:** Every hypothesis cites claim IDs; unsupported statements are rejected or marked; prompt/model version is stored; deterministic score remains reproducible without LLM; malicious source instructions cannot invoke tools or alter policy.

**Tests:** schema validation, hallucinated citation rejection, prompt injection corpus, no-evidence behavior, deterministic scoring regression, provider timeout/cost cap, golden fixtures with tolerant semantic review.

## M8 — Dashboard, filtering, and exports

**Outcome:** Operators can efficiently review, filter, correct, and export leads.

**Dependencies:** Stable M4–M7 APIs; design/accessibility review.

**Scope:** React application, auth/session, queues, lead detail, evidence/conflict UI, score explanation, duplicate review, filters, CSV export.

**Acceptance criteria:** Primary workflows meet WCAG target; filters are shareable/paginated; verified versus inferred content is visually unmistakable; exports honor RLS/field allow-list and are audited.

**Tests:** component/unit, API mocks, end-to-end review flow, keyboard/accessibility checks, authorization, filter correctness, CSV injection and large export behavior.

## M9 — Scheduling, budgets, retries, and monitoring

**Outcome:** Recurring workflows operate predictably within hard limits.

**Dependencies:** Measured job/provider behavior; operational destination chosen.

**Scope:** schedules, worker leases, retry policies, dead-letter/review queue, quota dashboard, alerts, structured telemetry; optional n8n trigger integration.

**Acceptance criteria:** Duplicate scheduler delivery is safe; stale jobs recover; hard caps hold under concurrency; operators see failure reason and next action; alerts avoid personal data.

**Tests:** clock-controlled schedules, worker crash/lease expiry, concurrent cap races, retry exhaustion, cancellation, metrics/log redaction, n8n contract if enabled.

## M10 — Outreach drafts, approval, and reporting

**Outcome:** Approved leads can produce evidence-based drafts and controlled reporting without autonomous bulk sends.

**Dependencies:** Legal/compliance review, M8 review workflow, approved Google OAuth scopes.

**Scope:** draft generation/editing, content-hash approval, suppression, Gmail draft creation, Sheets reporting, audit trail.

**Acceptance criteria:** Editing invalidates approval; suppression is checked at draft and handoff; only authorized approvers act; initial Gmail integration creates drafts, not sends; every handoff is idempotent and audited.

**Tests:** approval state machine, stale approval, concurrent edit, suppression at all scopes, OAuth denial/revocation, Gmail/Sheets mocks, idempotent handoff, no-send invariant.

## M11 — Integration, security, and deployment readiness

**Outcome:** A production candidate with explicit operating limits and recovery procedures.

**Dependencies:** Completed pilot, measured workload, chosen hosting, legal/provider approval.

**Scope:** end-to-end tests, threat model, dependency/container scanning, load/cost tests, backups/restore, runbooks, retention/deletion, staged deployment, observability/SLOs.

**Acceptance criteria:** Restore drill succeeds; tenant isolation and secret handling pass review; provider/LLM budgets survive load test; rollback is documented/tested; data retention jobs work; deployment requires human approval; no real outreach occurs in test.

**Tests:** full synthetic journey, penetration/security review, RLS/advisor scan, dependency/SAST/secret scan, load/soak, backup restore, migration rollback/recovery, provider outage, disaster and incident exercises.

## Cross-milestone gates

- **Provider gate:** terms, data fields, caching/retention, attribution, geography, quota, cost, and deletion behavior documented before live enablement.
- **Privacy gate:** lawful purpose, minimization, retention, subject-request process, and suppression policy approved before real contact data.
- **Spend gate:** hard cap defaults to zero until credentials and budget are explicitly enabled.
- **Outreach gate:** legal review plus explicit channel-specific authorization; human approval remains mandatory.
- **Deployment gate:** hosting choice follows measurements, not the existence of a nominal free tier.
