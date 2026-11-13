# Discovery CSV v1

`POST /v1/discovery-runs/csv` accepts a UTF-8 CSV with exactly these columns:

```text
schema_version,provider_record_id,company_name,domain,country_code,region,industry,employee_count,legal_form,company_status,source_url,observed_at
```

`schema_version` must be `1`. `provider_record_id`, `company_name`, an absolute HTTP(S) `source_url`, and timezone-aware `observed_at` are required. Other values may be blank. `country_code` is normalized to uppercase. Employee count must be a non-negative integer.

The parser rejects missing, duplicate, or unexpected columns; invalid UTF-8; extra row values; duplicate provider record IDs; empty files; and configured byte/row limit violations. Validation is all-or-nothing before a job is created. Only the typed allow-list is persisted in `request_json`; original file bytes and unknown columns are never retained.

The fixture at `tests/fixtures/discovery_candidates_v1.csv` is fictional and safe for local testing.
