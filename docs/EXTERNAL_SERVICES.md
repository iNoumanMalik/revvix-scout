# External services, credentials, and free-tier considerations

**Status:** Planning inventory  
**Verified:** 2026-11-13 from linked official pages; pricing and quotas are volatile and must be rechecked before enablement.

No external credential is required for M1 or the recommended provider-free M2A slice. Local development should use synthetic fixtures. Creating accounts, projects, OAuth clients, or paid subscriptions is not authorized by this document.

## Service inventory

| Service | Intended use | Credential/configuration | Free-first note and limitation |
|---|---|---|---|
| [Supabase](https://supabase.com/pricing) | Hosted PostgreSQL, Auth, optional Storage | project URL, publishable key for browser auth, server secret/service key, direct DB URL for migrations | Official pricing lists a $0 plan; current page reports 500 MB database and 50k MAU, while [billing docs](https://supabase.com/docs/guides/platform/billing-on-supabase) say two free projects. Free projects may not meet production uptime/backup needs. Data API grants and RLS are separate controls. |
| [Firecrawl](https://www.firecrawl.dev/pricing) | Permitted website search/scrape/research | `FIRECRAWL_API_KEY` | Official page currently advertises 1,000 free credits/month. Actions consume different credits and concurrency is limited; robots/terms and target-site permission still apply. Self-hosting shifts browser, proxy, maintenance, and compliance costs to us. |
| [Apollo](https://www.apollo.io/pricing) | Company/person discovery and enrichment | `APOLLO_API_KEY` plus account/workspace configuration | A free product tier exists, but contact credits, exports, API endpoints, and rate limits vary by plan. Treat UI access and standalone API rights as separate; verify the exact endpoint entitlement and data license before adapter work. |
| [Clay](https://www.clay.com/pricing) | Optional enrichment orchestration/experiments | workspace/API credentials and any bring-your-own provider keys | Official page offers Free/Launch/Growth/Enterprise options, but actions and data credits are metered and integrations differ by plan. Clay should not become the system of record or a required dependency for the first release. |
| [Hunter](https://hunter.io/pricing) | Professional email discovery/verification | `HUNTER_API_KEY` | Official page currently lists 50 free credits/month. Discovery and verification draw credits; free capacity is suitable for manual pilot checks, not broad enrichment. Never represent a generated pattern as verified. |
| Alternative verifier | Fallback email verification | provider-specific server key | Select only after comparing catch-all handling, regional coverage, deletion terms, API access, and cost. Do not chain paid fallbacks without a hard budget. |
| Configurable LLM | Evidence extraction and opportunity hypotheses | provider API key, model IDs, optional base URL | Do not assume a durable free API tier. Start with a fake adapter and deterministic scoring. Real calls require zero-retention/data-use review, token/cost caps, structured output, and prompt-injection defenses. |
| [n8n](https://n8n.io/pricing/) | Optional schedules and coarse workflow integration | self-host auth/encryption key or cloud credentials; webhook secret | Cloud is paid after trial; the official page also identifies a self-hosted Community Edition. Self-hosting is license-limited and not operationally free. Keep business state/retries in Scout. |
| Google Sheets API | Approved reporting projection | Google Cloud OAuth client, redirect URIs, refresh-token storage, limited scopes | API access has quotas rather than a simple paid-per-row model. Use least-privilege OAuth, batch writes, stable Scout IDs, and backoff. Sheets is not canonical storage. |
| Gmail API | Approved draft handoff | Google Cloud OAuth client and restricted Gmail scopes | API quotas apply and sensitive/restricted scopes may require verification depending on distribution. Initial integration should create drafts only; sending requires separate authorization. |
| GitHub Actions | CI | repository permissions; optional environment secrets | Public/private allowances depend on GitHub plan. Tests must not use live provider credentials; production secrets belong in protected environments if deployment is later approved. |
| Hosting (TBD) | API, worker, web, optional n8n | provider account, deployment token, runtime secrets | Do not choose from headline free tiers alone. Long-running workers, sleep/cold starts, egress, persistent disk, background processes, regions, logs, backups, and n8n requirements must be measured first. |
| Object storage (optional) | Licensed raw documents and exports | Supabase Storage or S3-compatible credentials | Avoid storing raw content until terms and retention are known. Encrypt, expire exports, use signed URLs, and keep only content allowed by the source contract. |

## Recommended environment variable names

Names are provisional until application scaffolding is approved. Keep browser-exposed and server-only values visibly separate.

```dotenv
# Application
APP_ENV=
APP_BASE_URL=
DATABASE_URL=

# Supabase server/auth integration
SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SECRET_KEY=

# Optional providers (server only)
FIRECRAWL_API_KEY=
APOLLO_API_KEY=
HUNTER_API_KEY=
CLAY_API_KEY=
LLM_PROVIDER=
LLM_API_KEY=
LLM_MODEL=

# Optional Google integrations
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=

# Optional n8n integration
N8N_WEBHOOK_URL=
N8N_WEBHOOK_SECRET=
```

Never expose `SUPABASE_SECRET_KEY`, provider keys, OAuth client secrets, refresh tokens, database URLs, or n8n secrets in frontend variables. Do not commit real `.env` files. Commit an `.env.example` only after the corresponding integration exists.

## Provider enablement checklist

Before enabling any live adapter, record:

1. Approved operations and purpose.
2. Account plan, exact API entitlement, rate limits, and hard spend cap.
3. Fields collected and whether they are business-relevant.
4. Source terms, attribution, cache/retention, derivative-data, export, and deletion constraints.
5. Supported geographies and known coverage bias.
6. Authentication/rotation owner and incident-revocation procedure.
7. Error, timeout, pagination, idempotency, and charge-on-failure behavior.
8. Fixture provenance and contract test coverage.
9. Data-subject and suppression handling.
10. A kill switch defaulting to disabled in new environments.

## Risks and limitations

- Free tiers can change, pause, expire, omit API access, or prohibit production workloads.
- Provider confidence and verification labels are not interchangeable across vendors.
- Company/person data can be stale, duplicated, licensed for limited uses, or unavailable in some regions.
- Catch-all domains make mailbox verification uncertain; accept `unknown` as a valid result.
- Website content can change after retrieval. Preserve timestamps and content hashes where permitted.
- API access through a ChatGPT connector does not grant the standalone backend credentials or commercial rights it needs.
- Combining providers can compound privacy, retention, and deletion obligations rather than eliminate them.

