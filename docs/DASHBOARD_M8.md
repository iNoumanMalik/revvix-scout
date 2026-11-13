# M8 dashboard contract

## Status

M8 is complete for the approved local, provider-free scope as of 2026-11-13. The operator dashboard, API-mediated authentication foundation, unified human-review workflow, safe correction paths, audited exports, and accessibility acceptance pass are implemented for fictional records. It does not enable public access, live providers, hosted infrastructure, or outreach.

## Implemented slice

- React, TypeScript, Vite, and Tailwind-based application under `apps/web`.
- FastAPI-only application-data boundary; the browser does not connect directly to PostgreSQL or the Supabase Data API.
- Business-lead table with disposition and minimum-score filters encoded in the URL.
- Cursor pagination that preserves the active filters.
- Allow-listed, formula-safe CSV export exposed with the active filters and streamed through bounded keyset-paginated database batches.
- Lead detail with deterministic score components and cited claim identifiers.
- Evidence presentation that keeps observed facts, provider assertions, human verification, and inference visually distinct.
- Opportunity hypotheses presented as advisory output, with citations and append-only accept/reject review actions.
- Responsive keyboard-focus treatment and automated accessibility checks for the primary view.
- A development-only safety label that makes the deterministic local-owner mode explicit.
- Supabase email/password session support with no public signup flow.
- Server-side token validation followed by active workspace-membership authorization.
- Deterministic local-owner mode for fixture development without external authentication calls.
- Audited CSV exports with requester, allow-listed fields, filter snapshot, row count, and request correlation.
- Workspace-scoped review queue spanning business qualification, fictional individual candidates, duplicate suggestions, and advisory opportunity hypotheses.
- Individual-candidate promote, possible-match link, and reject decisions through the existing append-only decision record.
- Review-first duplicate decisions with explicit survivor selection; merges remain logical and reversible.
- Shareable `view=reviews` navigation state, viewer read-only behavior, and fictional frontend fixtures.
- Explicit server-side capabilities for ingestion, pipeline execution, human review, privacy actions, and export; automation cannot impersonate a human reviewer.
- API-mediated Supabase session integration coverage proving token validation is followed by active workspace-membership authorization.
- Evidence-rich individual-candidate detail with source links, possible-match context, and a required written rationale before review resolution.
- Memory-bounded server-side CSV streaming with terminal success/failure audit state, exported row count, `no-store` caching, and content-sniffing protection.
- Dialog focus restoration, Escape-key dismissal, and automated accessibility coverage for the individual review flow.
- Append-only correction for advisory opportunity reviews, with one database-enforced active decision and retained reversal actor, reason, and timestamp.
- Safe reopening of plain individual-candidate rejections. Suppression and identity-creating promotion/link decisions remain irreversible by design.
- WCAG 2.2 AA source/automated review with modal focus containment, inert background content, contrast remediation, and mobile review navigation. See [the accessibility review](M8_ACCESSIBILITY_REVIEW.md).

## Role and action matrix

| Role | Read | Export | Ingest | Run pipelines | Human review | Privacy actions |
| --- | --- | --- | --- | --- | --- | --- |
| Owner | Yes | Yes | Yes | Yes | Yes | Yes |
| Admin | Yes | Yes | Yes | Yes | Yes | Yes |
| Operator | Yes | Yes | Yes | Yes | Yes | Yes |
| Reviewer | Yes | No | No | No | Yes | No |
| Viewer | Yes | No | No | No | No | No |
| Automation | Yes | No | No | Yes | No | No |

Capabilities are derived from the persisted workspace role on every request and returned by `/v1/session` for presentation only. The browser never grants authorization.

## Trust boundaries

The dashboard consumes only application API responses. It does not contain provider credentials, database credentials, or service-role keys. In Supabase mode, the browser sends an access token to FastAPI; Supabase Auth validates the token and Scout independently checks an active `workspace_members` record. User-editable token metadata is never used for authorization. Development mode creates a deterministic local owner and remains restricted to loopback use.

AI hypotheses remain separate from deterministic qualification. The UI states that hypotheses are not facts and that AI output does not change the deterministic ICP score. Source URLs and persisted claim identifiers remain visible for operator verification.

## Local development

Use Node.js 20.19 or newer (or 22.12 or newer). Install the pinned frontend dependency graph and start the development server:

```bash
cd apps/web
npm ci
npm run dev
```

The Vite development server proxies `/v1` and `/health` to the local FastAPI process at `http://127.0.0.1:8000`.

For a real local Supabase session, set `SCOUT_AUTH_MODE=supabase` with `SCOUT_SUPABASE_URL` and `SCOUT_SUPABASE_PUBLISHABLE_KEY` for the API. Copy `apps/web/.env.example`, set `VITE_SCOUT_AUTH_MODE=supabase`, and provide the same browser-safe URL and publishable key. The authenticated Supabase user must also have an active profile and workspace-membership row. Public signup remains disabled.

Run the frontend verification suite with:

```bash
cd apps/web
npm test
npm run typecheck
npm run build
```

Tests use fictional in-memory API responses and do not consume provider credits.

## M8 acceptance

- Backend suite: 115 tests passed.
- Frontend suite: 12 tests passed, plus TypeScript checking and production build.
- Alembic reports no schema drift; all 45 application tables retain RLS and the private schema has no `PUBLIC` grant.
- Live ChatGPT in-app-browser review passed at 1440 × 900 and 320 × 800 CSS pixels. The 320-pixel pass is the WCAG reflow equivalent of a 1280-pixel viewport at 400% zoom.
- Keyboard checks passed for the skip link, lead-detail focus containment, forward/reverse modal focus cycling, Escape dismissal, individual-decision validation, and opportunity accept/reopen correction.
- Browser console review reported no warnings or errors.
- The review found and corrected one exact-320-pixel horizontal overflow caused by the body minimum width; the retest measured `innerWidth`, `clientWidth`, `scrollWidth`, and body width at 320 pixels with no overflow.

Detailed evidence is recorded in [the accessibility review](M8_ACCESSIBILITY_REVIEW.md).
