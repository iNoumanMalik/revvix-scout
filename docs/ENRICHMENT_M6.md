# M6 enrichment and entity-resolution foundation

M6 implements the approved provider-free, fictional-only workflow for selective enrichment, durable evidence, and review-first identity resolution. It executes only the local fictional adapter, never calls a live provider or spends credits, and records logical merge history without destructive reference rewrites.

## Implemented foundation

- Versioned enrichment plans and ordered steps with requested fields, freshness windows, eligibility metadata, estimated units, forward-only fallback positions, and stop behavior.
- Enrichment runs tied to the existing idempotent job model.
- A typed enrichment provider port and a metadata-only fictional adapter under `.invalid` URLs.
- Source-document license/cache metadata without raw response storage.
- Claim review, validity, supersession, verification, and extractor-version metadata.
- Company, person, and existing lead evidence links without unsafe polymorphic foreign keys.
- Deterministic waterfall selection that skips fresh fields, requests missing or stale fields, and reports exhaustion.
- Conflict detection that keeps active contradictory values visible.
- Exact and fuzzy match suggestions that both require operator review; fuzzy names can never auto-merge.
- Canonically ordered match pairs and append-only merge/unmerge event snapshots.

## Implemented execution slice

- One published fictional business waterfall is seeded idempotently.
- `POST /v1/leads/{lead_id}/enrichment-runs` executes the next required step, and `GET /v1/enrichment-runs/{run_id}` returns its evidence.
- Fresh required evidence stops the run without a provider call, reservation, or usage event.
- Missing or stale fields select the next eligible step deterministically.
- The provider configuration, fictional-only flag, live-call flag, `.invalid` source, and metadata-only result are validated before persistence.
- A hard run budget is locked and reserved before adapter execution.
- Every attempted provider call settles its reservation and appends usage on success, partial success, validation/persistence failure, or provider failure.
- Source documents and claims are idempotent; contradictory normalized values remain stored and are marked `conflicting` rather than overwritten.

## Evidence boundary

Observed facts, provider assertions, inferred values, and human-verified claims remain separate classifications. A new claim never overwrites an older claim. Corrections use `supersedes_claim_id`; rejected, superseded, expired, conflicting, and invalid claims remain queryable for audit and reconciliation.

The fictional adapter returns only allow-listed normalized claims, source metadata, validity, confidence, and usage units. Its source document is metadata-only and records that raw content was not retained.

## Match and merge boundary

An exact stable identifier produces a high-confidence review suggestion, not an automatic merge. A fuzzy name is only a review signal. Match candidates store their algorithm version and feature summary. Merge events require an operator, a reason, a recovery snapshot, and distinct survivor/merged subjects. An unmerge event must reference the merge it reverses.

Review APIs require an explicit operator decision. Approved matches create append-only logical merge events with recovery snapshots; unmerge appends one idempotent reversal event. Suppressed or deleted people cannot be merged. Physical reference rewrites are deliberately excluded so review decisions remain non-destructive and recoverable.

## Migration and recovery

Revision `9e83bb75d0e3` extends `source_documents` and `evidence_claims` and adds seven tables: `enrichment_plans`, `enrichment_steps`, `enrichment_runs`, `company_evidence`, `person_evidence`, `entity_match_candidates`, and `entity_merge_events`. All new tables enable RLS with no policies, and every foreign key has a supporting primary, unique, or explicit index.

Upgrade backfills existing claims as `unreviewed` and existing import source documents as metadata-only with an explicit no-raw-content policy before enforcing non-null columns. The migration was applied and verified against the isolated local test database on 2026-11-13. Downgrade deletes enrichment-origin source documents and their dependent claims, removes all M6 records, and removes the added claim/source metadata. Use downgrade only on an isolated disposable database; prefer a forward correction for shared data.

Revision `c53cc7e9a80b` extends the shared reservation and usage ledgers with nullable enrichment-run references plus exactly-one-run constraints. Existing discovery references become nullable only after the enrichment reference is available. Its downgrade deletes enrichment ledger rows before restoring discovery-only non-null references. The migration was applied and verified against the isolated local test database on 2026-11-13.

## Completion and deferred gates

The approved M6 scope is complete. Static checks, migration drift checks, 36-table RLS and grant audits, ledger-integrity checks, concurrent hard-cap reservation, and the full 85-test suite pass against isolated local PostgreSQL.

Moving execution to a background worker is an operational scaling change rather than an M6 correctness requirement; the inline path already uses the shared idempotent job model and settlement invariants. Physical entity rewrites remain intentionally out of scope in favor of recoverable logical merge events.

Before any live adapter is implemented or enabled, separately validate its permissions, fields, retention, attribution, deletion behavior, sandbox mode, and free-tier assumptions, then obtain explicit approval. That future gate must include a sandbox smoke test and must not weaken the fictional-only default.
