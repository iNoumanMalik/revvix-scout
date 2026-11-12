# Business CSV import contract v1

M2A accepts UTF-8 CSV files with one header row and at most 5,000 data rows. Every column below is required in the header; fields marked optional may have an empty value.

| Column | Required value | Meaning |
|---|---:|---|
| `schema_version` | Yes | Must be `1`. |
| `source_record_id` | Yes | Stable identifier assigned by the import author. |
| `company_name` | Yes | Original public business name. |
| `domain` | No | Website hostname or URL. Converted to an IDNA registrable domain using an offline public-suffix snapshot. |
| `country_code` | No | Two-letter country code. |
| `employee_count` | No | Non-negative integer. |
| `industry` | No | A supported industry value; the current approved targets are `accounting` and `bookkeeping`. |
| `technology_need` | No | One recognized, source-supported technical-need category. |
| `excluded_reason` | No | Explicit source-backed reason the business must be disqualified. |
| `source_url` | Yes | Public HTTP(S) evidence URL supplied by the import author. |
| `observed_at` | Yes | ISO 8601 timestamp with timezone indicating when the source was observed. |

Allowed industries are `professional_services`, `software`, `healthcare`, `legal`, `education`, `retail`, `manufacturing`, `real_estate`, `hospitality`, and `other`.

Allowed technology needs are `manual_processes`, `legacy_systems`, `integration_gap`, `data_ai_opportunity`, `cloud_it_gap`, and `digital_experience`.

The importer does not fetch `source_url`. It treats supplied values as `provider_asserted`, stores their provenance, and never upgrades them to verified facts automatically.

Rows with valid domains deduplicate by normalized registrable domain. Rows without domains use a fingerprint containing the normalized name, country, and `source_record_id`; same-name businesses therefore remain distinct unless their source ID also matches. They are marked `needs_review`.
