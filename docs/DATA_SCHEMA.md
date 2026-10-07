# Envelope schema

`out/envelopes.jsonl` holds exactly one JSON object per input organisation number, in input order. The
typed model is `src/norway_company_agent/contract.py` (Pydantic). It follows `OUTPUT_CONTRACT.md` and
adds sections, a summary and refresh metadata.

```jsonc
{
  "organisation_number": "810034882",
  "run": {"run_id": "...", "started_at": "...", "completed_at": "...", "terminal_status": "completed|failed",
          "agent_version": "signalpost-agent/1.0", "previous_run_id": "... or null"},
  "company": {"name": "...", "legal_form": "AS", "municipality": "...", "website": "https://... (only when verified)"},
  "sections": {"legal_identity": {"title": "...", "availability": "available", "available_claims": 12, "fields": {"legal_name": "available"}}, "...": {}},
  "summary": {"method": "deterministic_template_v1 | local_llm_validated:<model>",
              "sentences": [{"text": "...", "claim_ids": ["cl-..."]}], "text": "...", "changes_text": "...", "unknowns_text": "..."},
  "claims": [{
      "id": "cl-<sha>",                 // stable: hash(org, field, key, value) — reruns produce the same id
      "field": "annual_account_metric", "section": "financials", "key": "company:2025-12-31:revenue",
      "value": 10021242.0, "availability": "available", "confidence": 0.99,
      "evidence_ids": ["ev-<sha>"], "reporting_period": {"from": "2025-01-01", "to": "2025-12-31"},
      "effective_at": "2025-12-31", "first_seen": "...", "last_verified_at": "...", "stale": false, "note": null }],
  "evidence": [{
      "id": "ev-<sha>", "source_url": "...", "final_url": "...", "source_class": "official_accounts",
      "retrieved_at": "...", "content_sha256": "...", "claim_span": "regnskapstype=SELSKAP; ...sumDriftsinntekter=10021242.0",
      "http_status": 200, "extractor": "brreg_accounts_v2", "snapshot": "snapshots/ab/<sha>.gz", "superseded": false }],
  "changes": [{"id": "ch-...", "type": "new_role", "field": "role", "key": "DAGL:Kari Nordmann", "old_value": null, "new_value": {},
               "old_evidence_ids": [], "new_evidence_ids": ["ev-..."], "detected_at": "...", "material": true}],
  "errors": [{"module": "financials", "state": "failed", "message": "Accounts lookup returned HTTP 500", "url": "..."}],
  "operations": {"requests": 9, "runtime_ms": 25140, "third_party_cost_usd": 0.0, "bytes": 412345}
}
```

## Availability

`available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`. Every field family below gets
at least one claim: either available values, or one placeholder claim with `key: "*"`, `value: null`, the
state and a note explaining what was checked. Missing values are never zero.

| Section | Field families |
|---|---|
| legal_identity | legal_name (incl. former names), legal_form (incl. share capital), registry_status, business_address, industry, business_purpose, founded_date, registered_employees, public_brand_name* |
| financials | annual_account_metric, annual_account_filing, filed_account_years |
| leadership | role, group_relation* |
| workplaces | registered_workplace, website_address* |
| web_presence | registry_website* (as declared in Enhetsregisteret), official_website (verified, entity-specific), website_description*, social_profile, knowledge_base_entry* |
| hiring | job_posting, careers_page* |
| activity | news_item, registry_event |

`*` optional families appear only when found.

## Source classes

`official_registry`, `official_registry_bulk`, `official_accounts`, `official_job_feed`, `open_knowledge_base_cc0`, `company_owned`.
