# M5 fictional decision-maker research contract

M5 extends the qualified-business workflow with company-scoped role research. The development adapter returns only invented people under `.invalid` profile and source URLs. It performs no network request, collects no contact details, spends no paid credits, and cannot send outreach.

## Workflow

1. Import or discover and qualify a company through the existing business pipeline.
2. Resolve one stored canonical company domain.
3. Run the fictional decision-maker adapter for configured buyer roles.
4. Score each title deterministically and retain the explanation and provider assertion separately.
5. Promote an eligible candidate into a person and a durable person-company role after suppression checks.

The initial configurable roles are Managing Partner, Director, and Practice Manager. Exact normalized title matches score 100; titles containing a configured role score 80; other titles are rejected. These defaults live in provider configuration rather than domain code.

## Provider and privacy boundaries

- The typed provider port contains company identity, target roles, professional profile identity, role metadata, source, observation time, and a fictional marker.
- It intentionally contains no email, telephone, messaging handle, or other contact field.
- Live adapters, live provider configuration, non-fictional results, and fixture URLs outside `.invalid` fail closed.
- Profile identity may establish an exact duplicate. A name alone never merges people.
- Active person or canonical-profile suppression blocks promotion.
- Provider assertions remain `provider_asserted` and `source_asserted`; promotion does not convert them into verified facts.

## Budgets and isolation

Decision-maker research uses the `decision_maker_discovery` operation and its own reservation and usage ledger entries. Business discovery uses `business_discovery`, so one operation cannot consume the other's run budget. Decision-maker runs use `pipeline_kind=business` with `discovery_kind=decision_maker`; ordinary company runs use `discovery_kind=company`, and individual runs remain independently addressable as `individual`.

## Local API

- `POST /v1/companies/{company_id}/decision-maker-runs`
- `GET /v1/decision-maker-runs/{run_id}`
- `POST /v1/decision-maker-candidates/{candidate_id}/promote`

Creation requires an idempotency key and accepts the fixture provider key and a bounded result limit. Promotion is idempotent for a source candidate and returns the person-company role.

## Schema and recovery

Revision `415f89420420` adds `decision_maker_candidates`, `person_company_roles`, and the required `discovery_runs.discovery_kind` discriminator. Existing business and individual runs are backfilled before the column becomes non-null. Both new tables have RLS enabled with no policies and indexed foreign-key access paths.

The migration was applied and acceptance-tested against the isolated local test database on 2026-11-13. Its downgrade deletes all M5 candidate and role data and removes the discovery-kind discriminator. Use downgrade only on a disposable database; for shared data, take a verified backup and prefer a forward correction.

## Live enablement gate

This contract does not authorize real-person collection. Before any live adapter is implemented or enabled, validate provider permissions, data fields, retention and deletion terms, international transfers, lawful purpose, privacy-notice coverage, correction/erasure procedures, and the applicable quota. Hosted resources, paid credits, and live calls remain separately approved actions.
