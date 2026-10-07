# Refresh, change detection and evidence preservation

Each run archives its envelopes to `state/runs/<run_id>/envelopes.jsonl` and `state/latest/envelopes.jsonl`.
The next run uses `state/latest` as the previous snapshot automatically, or the file passed with `--previous`
(`--no-previous` disables it).

- **Stable ids.** Claim id = hash(org, field, key, value); evidence id = hash(url, content SHA-256, span).
  Re-running on unchanged sources gives identical claim ids and zero changes (`test_identical_rerun_produces_no_changes`).
- **Typed changes.** Changes are computed per `(field, key)`: `new_role`, `removed_role`, `role_changed`, `new_location`,
  `closed_location`, `new_job`, `closed_job`, `new_activity`, `new_filing`, `financial_value_restated`, `name_changed`,
  `address_changed`, `status_changed`, `employee_count_changed`, `website_found`, `website_lost`, `website_changed`,
  `new_social_profile`, `removed_social_profile`, `description_changed` (non-material) and others. Each change carries the
  old and new values and evidence ids for both sides.
- **Earlier evidence is preserved.** Evidence behind an old value is copied into the new envelope with `superseded: true`,
  and the raw bytes remain in the content-addressed snapshot store.
- **Failed refresh keeps the last value.** If a source fails or is blocked in this run, the previous supported claims for that
  field family are carried forward with `stale: true`, and no removal change is emitted (`test_failed_refresh_carries_forward_last_supported_value`).
- **first_seen / last_verified_at** are tracked per claim.
- **Caches.** The NAV feed caches complete pages and each day's starting page under `state/cache/nav-feed/`, so daily
  runs fetch only new pages.
