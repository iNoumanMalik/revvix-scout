# M7 AI qualification and opportunity detection

M7 augments deterministic qualification with evidence-grounded opportunity hypotheses. The deterministic ICP score remains authoritative and reproducible without an AI provider. AI output is advisory, visibly unverified until human review, and cannot create a verified fact or buying signal.

## Approved development boundary

- Use only the deterministic fictional adapter during development.
- Do not call a live LLM, send source data externally, spend credits, or enable provider tools.
- Keep provider behavior behind typed ports with no SDK types in domain or application code.
- Treat all evidence values as untrusted data, never instructions.
- Exclude instruction-like evidence before provider execution and record excluded claim IDs in the future run record.
- Require every opportunity hypothesis to cite one or more claim IDs from its exact input snapshot.
- Reject unknown taxonomy categories, hallucinated citations, uncited hypotheses, duplicate citations, malformed confidence, and excessive output.
- Preserve prompt key/version, output schema version, taxonomy version, provider/model version, evidence fingerprint, token usage, and review history.

## Initial opportunity taxonomy

The first version reuses the configurable ICP technology-needs taxonomy:

- `manual_processes`
- `legacy_systems`
- `integration_gap`
- `data_ai_opportunity`
- `cloud_it_gap`
- `digital_experience`

These are solution hypotheses, not observed buying intent. Taxonomy definitions will be persisted and versioned before execution is exposed through the API.

## Implemented foundation

- Typed evidence snapshots, structured analysis results, hypothesis drafts, and provider ports.
- A deterministic fictional adapter that has no tools and makes no external request.
- Fail-closed grounding validation against the exact supplied claim IDs.
- Deterministic prompt-injection marker detection that excludes suspicious source claims.
- No-evidence behavior that returns missing-data guidance instead of inventing an opportunity.
- Unit coverage for grounded citations, hallucinated citations, unknown categories, uncited output, prompt injection, no-evidence behavior, and fictional output.

## Implemented execution and review

- A published prompt/taxonomy definition is seeded with its content hash and schema versions.
- Analysis runs persist the provider/model versions, token counts, exact claim-ID snapshot, excluded injection claims, input fingerprint, missing fields, contradictions, and terminal errors.
- The API executes only the fictional provider and reuses an existing run for the same prompt and evidence fingerprint.
- The budget is reserved before the adapter call and every attempted call settles immutable usage on success, invalid output, provider failure, or timeout.
- Each hypothesis is stored as unreviewed and has foreign-key-backed citation links to claims from its exact input snapshot.
- An operator can accept or reject a hypothesis once; the final decision is append-only and does not convert the hypothesis into a verified factual claim.
- Empty evidence stops without provider usage, and tool-enabled or live providers fail closed before execution.

## Migration, verification, and deferred gate

Revision `1857fd4e0d6e` adds five RLS-enabled tables and extends the shared ledgers so a record references exactly one discovery, enrichment, or opportunity-analysis run. Its downgrade deletes M7 ledger rows, restores the M6 ledger constraints, and then removes all M7 analysis/review data. Revision `5e550b440693` additively indexes the three shared-ledger foreign keys identified by the schema audit; its downgrade removes only those indexes.

Both revisions were applied only to the isolated local test database. Alembic reports no drift; all 41 application tables have RLS; there are no public schema grants, invalid indexes, unvalidated constraints, unindexed M7/shared-ledger foreign keys, or invalid ledger references. The full 100-test suite passes.

The approved M7 scope is complete. A real LLM adapter remains blocked until its data use, international transfer, retention, model-training, deletion, regional processing, structured-output, timeout, tool-disablement, and cost terms are reviewed and explicitly approved. A sandbox smoke test is required after that approval.
