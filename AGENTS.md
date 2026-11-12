# Repository instructions

## Scope and safety

- Revvix Scout is an evidence-backed lead intelligence system. Never fabricate facts, contact data, buying signals, or source attribution.
- Keep verified observations, provider assertions, and AI hypotheses separate in code, storage, and UI.
- Use only official APIs and permitted public sources. Do not bypass authentication, rate limits, robots controls, or access restrictions.
- Use business-relevant contact information only. Suppression and opt-out checks are mandatory before any outreach workflow.
- Never send messages, spend paid credits, deploy, create cloud infrastructure, or make destructive database changes without explicit approval.
- External communication always requires a recorded human approval. Bulk cold sending is out of scope.

## Architecture

- Start as a modular monolith. Respect domain boundaries; do not add networked services without an accepted architecture decision record.
- Keep individual and business discovery as independent application modules. Reuse shared enrichment, evidence, identity, qualification, jobs, usage, and reporting modules.
- Put vendor behavior behind typed ports/adapters. Domain and application code must not import provider SDKs.
- Prefer deterministic rules for normalization, deduplication, budgets, and base scoring. Treat LLM output as unverified until evidence or human review supports it.
- Persist provenance, timestamps, verification state, confidence, and provider usage for every externally derived claim.

## Engineering standards

- Use typed Python and TypeScript. Keep functions small, names explicit, and public interfaces documented.
- Validate data at system boundaries. Use UTC timestamps and canonical normalized values alongside original values.
- Make jobs idempotent, retry only transient failures with bounded backoff, and record every attempt.
- Pin dependencies, commit lockfiles, and keep secrets out of source control and logs.
- Add tests for business rules, provider contracts, entity resolution, scoring, budget enforcement, suppression, and authorization.
- Every schema change needs a migration, rollback/recovery notes, database tests, and an RLS review. Do not apply migrations without approval.
- Update relevant documentation and architecture decisions in the same change as behavior.

## Working practice

- Preserve unrelated user changes and keep commits narrowly scoped.
- Before coding, read `README.md` and the relevant file under `docs/`.
- Prefer fixtures or mocks for paid and rate-limited providers. Tests must not consume provider credits or send email.
- Run the narrowest relevant checks during development, then the full documented suite before handoff.
- If a required command is not documented and verified in the repository, do not invent it; add it only after the tooling exists and the command has been tested.

