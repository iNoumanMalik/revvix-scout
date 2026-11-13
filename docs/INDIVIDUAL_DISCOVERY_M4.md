# M4 fictional individual discovery contract

M4 introduces an independent individual discovery pipeline while real personal-data collection remains disabled. This development slice accepts and emits only fictional professional records. It does not discover contact details, sole traders, private profiles, or real people, and it cannot send outreach.

## Safety state

- The only registered adapter is `fictional_professional_directory`; it is local and makes no network call.
- The individual ICP stores `collection_enabled: false` and `fictional_data_only: true`.
- Provider configuration must also be fictional-only with live calls disabled.
- A live adapter is rejected before execution. A provider record marked non-fictional fails the run and is not persisted.
- No email, telephone, social-message, or other contact field exists in the M4 provider contract or API request.
- All external messaging remains unavailable. Suppression and outreach approval controls remain required before any later contact workflow.

These controls are engineering safeguards, not a lawful-basis determination. Live individual or sole-trader discovery requires a separately approved privacy/source review and a later migration/configuration change.

## Identity and qualification

Professional profile URLs are normalized to HTTPS, lower-case IDNA hosts, non-default ports, canonical paths, sorted identity query parameters, and no fragments or common tracking parameters. Exact normalized profile URLs can resolve a duplicate person. Names are normalized only to produce possible-match review suggestions and never auto-merge people.

The deterministic development score uses four configurable components:

| Component | Points |
|---|---:|
| Professional presence | 35 |
| Business relevance | 35 |
| Approved development persona | 20 |
| GB / England geography | 10 |

A missing professional presence or business relevance rejects the candidate regardless of score. At 80 points a fictional candidate is qualified; 60–79 requires review. Exact profile matches are duplicates, while same-name/country matches require manual review.

The development personas—business coach, consultant, freelancer, founder, content creator, and educator—are fixtures inherited from the initial brief. They are configurable and are not approval to collect live data.

## API

- `POST /v1/individual-discovery-runs` runs one bounded fictional page.
- `GET /v1/individual-discovery-runs/{run_id}` reads an individual run and its candidates.
- `POST /v1/individual-candidates/{candidate_id}/review` records one immutable operator decision: promote a new person, explicitly link an existing person, reject, or suppress the profile.
- `GET /v1/individual-leads` lists person-subject leads independently of business leads.
- `POST /v1/people/{person_id}/suppress` records minimal suppression state and immediately disqualifies the person's lead.

Business and individual read paths filter on `pipeline_kind`, so one pipeline cannot be retrieved through the other's endpoint. Individual discovery has its own provider registry, ICP version, job type, budget operation, and candidate table while reusing the shared job/attempt/usage ledger.

Operator review is final and append-only for each candidate. A same-name suggestion never links automatically: `link_existing` requires the operator to supply the exact person ID. `promote_new` can intentionally create separate people with the same normalized name. Database checks require each lead to have exactly one subject matching its pipeline.

Profile suppression stores only a SHA-256 canonical-profile lookup key. Person suppression stores the person reference and a category, not free-text personal details. Active suppression is checked before promotion and during rediscovery. Physical person deletion is restricted while a person suppression exists; normal lifecycle deletion is soft state.

## Migration and recovery

Revision `410360f37f0b` adds `people`, `person_profiles`, and `individual_discovery_candidates`, plus the discriminator on `discovery_runs`. Existing runs are backfilled as `business`; the temporary default is then removed. RLS is enabled with no policies on all three new tables.

Revision `20a7a62a7d6a` completes the local M4 model with `suppressions`, append-only `individual_review_decisions`, and person-subject leads. It enables RLS on both new tables, indexes every new foreign key, and uses partial unique indexes for one business or individual lead per ICP subject. Its downgrade deletes individual leads before restoring the business-only lead constraint and is therefore destructive.

The migration is additive on upgrade. Its downgrade deletes all M4 people, profile, and individual candidate data and removes the pipeline discriminator, so downgrade is only appropriate for an isolated disposable database. In a shared environment, take a verified backup and prefer a forward corrective migration.

## Approval gates remaining

Before live individual collection, approve the exact personas, permitted sources and fields, lawful purpose/basis assessment, privacy notice, international transfer path, retention/deletion workflow, correction and erasure process, source/provider terms, and suppression behavior. Authentication, workspace membership policies, and non-owner RLS tests are also required before client or hosted access.
