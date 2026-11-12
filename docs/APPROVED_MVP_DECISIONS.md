# Approved MVP decisions

**Approved:** 2026-11-13

These decisions supersede the provisional assumptions in the original M1 documents.

## Market and ICP

- Initial market: England, United Kingdom.
- Initial targets: independent accounting and bookkeeping practices with roughly 5–30 employees.
- Prefer active incorporated Ltd and LLP entities. Dormant entities, duplicates, unrelated firms, major chains, and insufficiently evidenced records are disqualified or routed to review.
- Relevant buyers are Managing Partners, Directors, and Practice Managers.
- Potential solutions include workflow automation, CRM integration, client onboarding, scheduling, AI assistants, document processing, and custom software.
- Every filter, weight, threshold, exclusion, and solution taxonomy is versioned configuration. Code must not silently redefine the ICP.

The architecture retains an independent individual-prospect pipeline. Collection or outreach for individuals and sole traders is disabled until an appropriate legal review approves it. Every external message requires recorded human approval.

## Sources and spend

Public business websites, permitted search APIs, Firecrawl, Companies House, Apollo, and Clay may be considered only after source-specific terms, licensing, access, quota, retention, and deletion review. Providers remain disabled and replaceable through adapters until approved. Free/thin discovery precedes enrichment; paid units default to a hard limit of zero.

No unrestricted scraping, access-control bypass, prohibited-source collection, paid-credit use, live collection, or outreach is approved by this decision record.

## Workspace and access

The MVP has one internal Revvix AI workspace. Owner/Admin is the human management role; Automation Service is restricted machine access. There are no public signups or multi-organization features. Workspace keys remain on domain records so future multi-workspace migration does not require redesign.

## Local environment

Development uses local Supabase PostgreSQL through the Supabase CLI and Docker-compatible runtime. Alembic migrations in Git remain the canonical application schema history. No hosted Supabase resource may be created or modified without separate approval.

## Compliance baseline

UK GDPR, PECR, international transfer obligations, and provider terms are gates, not after-launch tasks. See [compliance and retention](COMPLIANCE_AND_RETENTION.md). A privacy notice and documented lawful-basis assessment are required before live personal-data collection or outreach.
