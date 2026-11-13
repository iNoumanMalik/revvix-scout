# Migration and recovery notes

Scout uses Alembic migrations against the PostgreSQL instance started by the local Supabase CLI. Application objects live in the private `scout` schema; Alembic's own version table lives in the private `scout_internal` schema rather than exposed `public`. The initial M3 migration adds provider discovery, job, budget, and usage tables. Revision `94bf120ac780` adds worker leases, retry scheduling, attempt retryability, one-run-per-job enforcement, and claim/settlement indexes. Every application table has RLS enabled. No migration creates Supabase Auth policies, browser/Data API grants, or hosted resources.

Revision `94bf120ac780` is additive. Existing jobs are backfilled to three attempts and an immediately eligible `next_attempt_at` before temporary server defaults are removed. Its downgrade removes retry metadata and indexes and is destructive to in-flight retry state; prefer a forward correction outside a disposable database.

Revision `410360f37f0b` is the M4 foundation migration. It adds three fictional-individual tables and a required `discovery_runs.pipeline_kind`. Existing runs are backfilled as `business` through a temporary server default, then the default is removed. The new tables have RLS enabled with no policies. Its downgrade destroys all M4 people/profile/candidate records and removes the discriminator; use it only on a disposable database and prefer a forward correction elsewhere.

Revision `20a7a62a7d6a` is the M4 completion migration. It adds suppressions and immutable individual review decisions, enables RLS on both, and extends `leads` to require exactly one company or person subject matching `pipeline_kind`. Existing business rows remain valid and receive no data rewrite. Its downgrade explicitly deletes all individual leads before restoring the business-only constraint, so it is destructive and suitable only for an isolated disposable database.

Revision `415f89420420` is the M5 fictional decision-maker migration. It adds decision-maker candidates and person-company roles, enables RLS on both, and adds a discovery-kind discriminator. Existing individual runs are backfilled as `individual` and existing business runs as `company` before the new column becomes non-null. The discriminator constraint permits `decision_maker` only inside the business pipeline. Its downgrade destroys all M5 candidates and roles and removes the discriminator.

Revision `9e83bb75d0e3` is the M6 foundation migration. It adds seven RLS-enabled waterfall, subject-evidence, match-candidate, and merge-history tables and extends source documents and claims with license, cache, freshness, review, and supersession metadata. Existing rows receive explicit metadata-only/no-raw-content and unreviewed backfills before non-null enforcement. Its downgrade deletes enrichment-origin source documents and dependent claims before restoring the import-only source constraint, destroys all M6 records, and removes the added metadata.

Revision `c53cc7e9a80b` is the M6 execution-ledger migration. It lets budget reservations and immutable usage events reference exactly one discovery or enrichment run, with indexed enrichment-run foreign keys. Existing discovery records remain valid without data rewriting. Its downgrade deletes enrichment usage events and reservations before restoring discovery-only non-null references. It was applied only to the approved isolated local test database.

## Apply and inspect

Set `SCOUT_DATABASE_URL` to the intended database, then run:

```bash
alembic current
alembic upgrade head
alembic check
```

Always inspect the URL and current revision before applying a migration. Hosted, shared, or production application requires separate approval, a backup, and a reviewed execution plan.

## Development downgrade

Downgrading to the M2A revision removes the eight M3 tables. Downgrading to base removes all application tables and the `scout` schema. These operations are suitable only for an isolated disposable development/test database.

```bash
alembic downgrade base
alembic upgrade head
```

The migration chain through revision `415f89420420` was applied and verified against an isolated local database on 2026-11-13. Alembic reported no schema drift, all 29 application tables retained RLS, the private schema had no `PUBLIC` grants, all indexes were valid, every M5 foreign key had a supporting primary, unique, or explicit index, and no discovery run violated the pipeline-kind discriminator. The full suite passed 69 tests. The destructive downgrade was not rerun. Do not use downgrade to recover shared or production data.

Revision `9e83bb75d0e3` was then applied to the same isolated test database. Alembic reported no schema drift; all 36 application tables have RLS; there are no `PUBLIC` schema grants, invalid indexes, unvalidated M6 constraints, or unindexed M6 foreign-key columns. The expanded suite passed 76 tests. The destructive M6 downgrade was not run.

Revision `c53cc7e9a80b` was subsequently applied to the same isolated test database. Alembic remained at head with no schema drift; all 36 application tables retained RLS; there are no `PUBLIC` schema grants, invalid indexes, or invalid discovery/enrichment ledger references. Concurrent reservations respect the hard cap, and the full suite passed 85 tests. Its destructive downgrade was not run.

## Recovery strategy

- For disposable development data, recreate the schema with `alembic upgrade head` and re-import the original versioned CSV fixtures.
- For any future shared environment, prefer a forward corrective migration. Take and verify a database backup before schema changes.
- If a migration fails transactionally, preserve the error and database state, inspect `alembic current`, and correct the migration before retrying.
- If a migration partially succeeds because a future operation cannot be transactional, stop and follow its milestone-specific recovery plan; do not guess or manually edit migration history.
- Supabase deployment work must use the installed CLI version's documented workflow and run database/security advisors before approval. M3 does not configure or mutate a hosted Supabase project.

## RLS review

RLS is enabled with no policies on all 36 application tables. Non-owner roles therefore have no row access, and the schema has no `PUBLIC` access. The direct backend connection operates as the table owner for local development. M2 must introduce workspace membership, explicit grants, policy tests for every role/action, and a non-owner application role before any browser or Data API exposure.
