# Compliance and retention baseline

This is an engineering control baseline, not legal advice. Legal review remains required before live personal-data collection or outreach.

## Default retention schedule

| Data class | Default | Engineering treatment |
|---|---:|---|
| Permitted raw website content | 14 days maximum | Record source policy and expiry; do not retain when terms prohibit it. |
| Unqualified personal leads | 90 days | Delete or anonymize when purpose ends. Collection is disabled initially. |
| Qualified personal leads | 180 days before review | Review necessity before extending. Collection is disabled initially. |
| Active opportunities | At least annual review | Retain only fields needed for the active relationship. |
| Technical logs containing personal data | 30 days where feasible | Avoid personal data in logs; redact credentials and contact values. |
| Suppression records | As long as justified | Keep only the minimum stable value/hash and scope needed to honor an opt-out. |

Provider-specific shorter periods override these defaults. Each provider configuration carries a data-policy snapshot. Raw responses are not stored in discovery candidates; only allow-listed normalized fields and provenance metadata are retained.

## Required controls before live enablement

1. Record purpose, lawful-basis assessment, privacy-notice coverage, source terms, geographic transfer path, and data-subject impact.
2. Approve source fields, cache/retention limits, attribution, correction, erasure, export, and provider-deletion workflow.
3. Keep individual and sole-trader collection/outreach disabled until specific legal review.
4. Require suppression checks and recorded human approval for any draft handoff or external message.
5. Support correction, access/export, erasure/anonymization, and opt-out requests without deleting the minimal suppression record needed to prevent re-contact.

M3 uses fictional companies only. The M4 development slice uses invented professional identities under `.invalid` URLs, contains no contact details, and performs no external request. M5 reuses those boundaries for company-scoped fictional decision-maker research and rejects non-fictional results or non-`.invalid` fixture URLs. Profile suppression retains only a SHA-256 canonical-profile key; person suppression retains a person reference and reason category, with no free-text personal note. Active suppression blocks promotion and rediscovery. The M4 schema requires a retention expiry for any future non-fictional person or candidate, but this constraint does not authorize collection; the full legal/source gate above remains mandatory.
