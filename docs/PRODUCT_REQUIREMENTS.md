# Product requirements document

**Product:** Revvix Scout  
**Status:** Proposed for review  
**Planning date:** 2026-11-13  
**Owner:** Revvix AI

## 1. Summary

Revvix Scout helps a small technical-services business find and prioritize legitimate prospects by combining low-cost public discovery, evidence-backed research, selective enrichment, deterministic qualification, and assisted analysis. It supports two independent pipelines:

- **Individual prospects:** professionals whose business identity is primarily personal, such as consultants, creators, educators, freelancers, and founders.
- **Business prospects:** organizations discovered first, followed by relevant decision makers.

Both pipelines share identity resolution, evidence, provider controls, qualification, storage, review, and reporting. The initial product is an internal operator tool; the design should leave a credible path to multi-tenant SaaS without paying that complexity cost immediately.

## 2. Problem

Manual lead research is slow and inconsistent. Broad automation often creates low-quality records, wastes enrichment credits, loses source context, conflates guesses with facts, and encourages unsafe outreach. Revvix AI needs a repeatable way to discover plausible buyers for a broad range of software, AI, automation, and IT services while retaining enough evidence for a human to decide whether an opportunity is real.

## 3. Goals

1. Continuously produce a reviewable queue of relevant, non-duplicate prospects.
2. Minimize paid enrichment by screening inexpensive discovery candidates first.
3. Explain every score and opportunity hypothesis using dated source evidence.
4. Find appropriate business contact channels without inventing personal data.
5. Make provider cost, data freshness, job status, and failure modes visible.
6. Require human approval before any external communication.
7. Support new discovery and enrichment providers without changing core rules.

## 4. Non-goals for the initial product

- Autonomous bulk cold email or social messaging.
- Circumventing gated sites, anti-bot controls, provider licenses, or platform terms.
- A general-purpose consumer people-search database.
- Guaranteed email deliverability or guaranteed buying intent.
- Real-time CRM replacement, sales engagement suite, or marketing automation platform.
- Microservices, Kubernetes, or multi-region infrastructure.
- Training a custom foundation model.

## 5. Users and jobs

### Operator/researcher

- Define an ICP and start a bounded discovery run.
- Review candidates, evidence, duplicates, scores, cost, and failures.
- Promote promising candidates to deep enrichment.
- Correct or reject claims and merge duplicates.
- Export an approved result set.

### Sales approver

- Understand why a lead is relevant.
- Review opportunity hypotheses and supporting/contradicting evidence.
- Edit, approve, or reject an outreach draft.
- Confirm suppression checks before release to a separate sending integration.

### Administrator

- Configure users, provider credentials, quotas, schedules, and retention.
- Audit access, provider use, approvals, and data deletion/suppression actions.

## 6. Core concepts

- **Candidate:** a thin, newly discovered record that may still be incomplete or duplicate.
- **Entity:** a normalized company or person with stable internal identity.
- **Lead:** an entity evaluated under a specific ICP and pipeline.
- **Evidence:** a dated claim from a named source with a URL or provider record, retrieval details, confidence, and verification status.
- **Hypothesis:** an AI- or human-authored interpretation that is not a verified observation.
- **Opportunity:** a reviewable technical need hypothesis linked to evidence.
- **Qualification:** a versioned score and disposition produced under explicit ICP rules.

## 7. Functional requirements

Priority meanings: **P0** is required for a dependable initial platform, **P1** follows once the core works, and **P2** is later optimization.

### 7.1 ICP configuration

- **P0:** Create versioned ICPs with target industries, regions, company sizes, personas, exclusions, required signals, weighted rules, and score thresholds.
- **P0:** Preserve the exact ICP version used by every score.
- **P1:** Offer templates and compare qualification results across versions.

### 7.2 Thin discovery

- **P0:** Run the individual and business pipelines independently.
- **P0:** Accept candidates from manual/CSV import and adapter-provided public sources.
- **P0:** Preserve raw provider/source payload references, import time, run, and terms/license metadata.
- **P0:** Normalize and deduplicate before any deep enrichment request.
- **P1:** Schedule bounded searches with per-source limits and incremental cursors.

### 7.3 Enrichment waterfall

- **P0:** Define ordered enrichment steps with eligibility conditions, cache/freshness policy, per-call estimate, and fallback behavior.
- **P0:** Stop when required fields reach confidence targets or the lead becomes ineligible.
- **P0:** Enforce per-run, daily, monthly, and provider budgets before a call.
- **P1:** Compare conflicting provider assertions and route material conflicts to review.

### 7.4 Research and opportunity detection

- **P0:** Store source documents and atomic evidence claims with observed/retrieved timestamps.
- **P0:** Label claims as observed, provider-asserted, inferred, or human-verified.
- **P0:** Generate opportunity hypotheses only with linked supporting evidence and an uncertainty statement.
- **P0:** Cover broad legitimate technical needs: software delivery, integrations, data/AI, workflow automation, cloud/infrastructure, security hygiene, analytics, IT operations, and digital experience.
- **P1:** Detect contradictory or stale evidence and reduce confidence accordingly.

### 7.5 Entity resolution

- **P0:** Exact-match normalized domains, verified emails, provider IDs, and source IDs.
- **P0:** Produce possible-match suggestions for fuzzy name/location/profile similarity; never auto-merge uncertain matches.
- **P0:** Record merge decisions and allow recovery from an incorrect merge.
- **P1:** Learn operator-approved aliases without hiding the underlying match evidence.

### 7.6 Decision makers and contact points

- **P0:** Associate multiple roles and people with a company.
- **P0:** Record contact origin, purpose, verification method/status, last checked time, and confidence.
- **P0:** Never treat a guessed email pattern as verified.
- **P0:** Apply suppression at workspace, company, person, domain, and contact-value levels.

### 7.7 Qualification

- **P0:** Produce an explainable deterministic score with per-rule contributions, disqualifiers, missing-data effects, and the rule-set version.
- **P0:** Maintain qualification history rather than overwriting prior results.
- **P1:** Add AI-assisted fit commentary as a separate, non-authoritative assessment.

### 7.8 Jobs, budgets, and audit

- **P0:** Track job state, attempts, idempotency key, input fingerprint, output summary, error class, and next retry.
- **P0:** Retry transient failures with bounded exponential backoff; do not retry policy, validation, or exhausted-budget failures.
- **P0:** Record provider units and monetary estimates even for failed calls where the provider charges.
- **P0:** Audit sensitive reads, writes, merges, exports, approvals, suppressions, and credential/config changes.

### 7.9 Dashboard and reporting

- **P0:** Filter leads by pipeline, stage, ICP, score, geography, industry, freshness, evidence status, and review state.
- **P0:** Show entity details, evidence, score explanation, opportunities, contacts, job history, and spend.
- **P0:** Export authorized filtered records to CSV without hidden fields.
- **P1:** Google Sheets reporting with stable record IDs and update semantics.

### 7.10 Outreach controls

- **P0:** Drafts are separate from sent messages and include the evidence used for personalization.
- **P0:** Approval records identify approver, exact content hash, decision, and time.
- **P0:** Re-check suppression and approval validity immediately before handoff.
- **P1:** Gmail integration creates drafts first; sending remains a distinct, explicitly authorized action.

## 8. Data quality rules

1. A claim without a source is a note or hypothesis, not verified evidence.
2. Confidence expresses system certainty, while verification status expresses process state; they are not interchangeable.
3. `observed_at` is when the fact applied or appeared; `retrieved_at` is when Scout fetched it.
4. Original provider values are retained where licensing permits; normalized values never replace originals.
5. Staleness thresholds vary by field (for example, role and email status expire faster than founding year).
6. Negative or conflicting evidence is retained and visible.
7. LLM output cannot create a verified contact point or deterministic score input without an accepted source claim.

## 9. Non-functional requirements

- **Security:** deny-by-default authorization, workspace isolation, least-privilege credentials, encrypted transport/storage, secret rotation, and safe logging.
- **Privacy:** data minimization, purpose limitation, documented retention, access/export/delete workflows, and suppression that survives ordinary record deletion.
- **Reliability:** idempotent jobs, recoverable imports, explicit partial-success states, and no silent provider fallback.
- **Performance:** initial target of p95 under 500 ms for paginated lead reads excluding external calls; async work for discovery/enrichment.
- **Maintainability:** typed boundaries, provider contract tests, architecture decisions, and a single deployable backend initially.
- **Observability:** structured logs with correlation IDs, job/provider metrics, budget alerts, and auditable state transitions.
- **Accessibility:** dashboard targets WCAG 2.2 AA for primary review workflows.

## 10. Success measures

Baselines should be measured during pilot; initial targets are hypotheses, not promises.

- At least 90% of surfaced opportunity briefs have one or more directly linked supporting evidence items.
- Fewer than 2% confirmed duplicate entities remain after operator review of a pilot dataset.
- At least 70% of paid enrichment calls are made only after a candidate passes the thin-discovery threshold.
- 100% of provider calls have a usage event and 100% of scores identify their ICP version.
- 100% of outbound handoffs have current approval and suppression checks.
- Operators can understand a score and its strongest evidence without opening provider dashboards.

## 11. Explicit assumptions

- The initial deployment serves one Revvix AI workspace, but every business record is scoped so multi-tenancy can be enabled later.
- English-language sources and operator UI are sufficient for the first pilot.
- The first pilot focuses on business prospects; individual discovery follows once shared rules prove sound.
- PostgreSQL is the system of record. n8n may trigger workflows but does not own business state or qualification logic.
- Provider payload retention and caching will be configured per contract; not all raw responses may be stored indefinitely.
- AI providers are optional. Core intake, deduplication, scoring, review, and export work without an LLM.

## 12. Unknowns requiring product decisions

1. First target countries and applicable privacy/marketing regimes.
2. Initial industries, exclusions, employee/revenue ranges, and buyer personas.
3. What constitutes a qualified lead and which negative signals are hard disqualifiers.
4. Which public discovery sources are permitted and commercially acceptable.
5. Data retention periods by source, contact type, and lead disposition.
6. Whether users need multiple workspaces or roles in the first release.
7. Expected daily candidate volume and acceptable operator review load.
8. Whether outreach integration should stop at Gmail draft creation or later permit an approved send action.

## 13. Release boundary

M1, M2A, and the provider-free M3 core are approved for local implementation using fictional fixtures. Production/live ingestion, personal-data collection, paid provider use, hosted infrastructure, deployment, and external communication require separate approval.
