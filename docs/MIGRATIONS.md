# Migration and recovery notes

Scout uses Alembic migrations against the PostgreSQL instance started by the local Supabase CLI. Application objects live in the private `scout` schema; Alembic's own version table lives in the private `scout_internal` schema rather than exposed `public`. The initial M3 migration adds provider discovery, job, budget, and usage tables. Revision `94bf120ac780` adds worker leases, retry scheduling, attempt retryability, one-run-per-job enforcement, and claim/settlement indexes. Every application table has RLS enabled. No migration creates Supabase Auth policies, browser/Data API grants, or hosted resources.

Revision `94bf120ac780` is additive. Existing jobs are backfilled to three attempts and an immediately eligible `next_attempt_at` before temporary server defaults are removed. Its downgrade removes retry metadata and indexes and is destructive to in-flight retry state; prefer a forward correction outside a disposable database.

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

The migration chain through revision `94bf120ac780` was applied from base and verified against an isolated local database on 2026-11-13. Alembic reported no schema drift, all 22 application tables retained RLS, the private schema had no `PUBLIC` grants, and all indexes were valid. The destructive downgrade was not rerun. Do not use downgrade to recover shared or production data.

## Recovery strategy

- For disposable development data, recreate the schema with `alembic upgrade head` and re-import the original versioned CSV fixtures.
- For any future shared environment, prefer a forward corrective migration. Take and verify a database backup before schema changes.
- If a migration fails transactionally, preserve the error and database state, inspect `alembic current`, and correct the migration before retrying.
- If a migration partially succeeds because a future operation cannot be transactional, stop and follow its milestone-specific recovery plan; do not guess or manually edit migration history.
- Supabase deployment work must use the installed CLI version's documented workflow and run database/security advisors before approval. M3 does not configure or mutate a hosted Supabase project.

## RLS review

RLS is enabled with no policies on all 22 application tables. Non-owner roles therefore have no row access, and the schema has no `PUBLIC` access. The direct backend connection operates as the table owner for local development. M2 must introduce workspace membership, explicit grants, policy tests for every role/action, and a non-owner application role before any browser or Data API exposure.
