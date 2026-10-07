# 100-company smoke test

- **Batch:** `companies.jsonl`, selected with `uv run python select_entry_batch.py --universe <public universe> --count 100`
  (default seed `20260823`). The agent was not tuned on this batch.
- **Command:** `uv run python run_agent.py --input reports/smoke-100/companies.jsonl --output out/envelopes.jsonl`
  (default settings: 48 workers, budget `max(900, 2 × N)` = 900 s, local LLM off).
- **Machine:** Windows 11 laptop, 16 logical CPUs. Network: residential broadband, Norway-facing public APIs.

## Contract checks (run `smoke-100-v3`)

| Check | Result |
|---|---|
| One terminal envelope per input, in input order | ✅ 100 / 100 |
| Unique organisation numbers, zero silent drops | ✅ |
| Schema-valid envelopes (Pydantic + every claim's evidence present) | ✅ 100 / 100 |
| Only the six contract states | ✅ |
| Within time budget | ✅ 205.5 s of 900 s |
| Terminal status | 100 `completed` |
| Requests | 799 (6.9 per company + 108 background) |
| Third-party cost | **USD 0** |
| Peak memory | about 480 MB |

## What was found

| Field family | Companies with a value | Facts |
|---|---:|---:|
| Legal identity (name, form, status, address, industry, activity, founded) | 100 | — |
| Annual accounts (3 years, company and group, each with reporting period) | 100 | 2,825 figures |
| Filing history (filed years + official copy links) | 100 | 100 |
| Roles (board, CEO, auditor, accountant) | 100 | 387 |
| Dated registry events | 100 | 562 |
| Registered workplaces (subunits) | 73 | 76 |
| Group relations | 8 | 12 |
| Verified official website (entity-specific) | 8 | 8 |
| Social profiles (from the verified site or Wikidata) | 3 | 8 |
| Dated company news | 4 | 32 |
| Active job postings (NAV, verified by employer org number) | 0 | 0 |

Totals: 5,659 claims, of which 5,157 are `available`. **All 5,157 available claims carry evidence** (3,574 evidence
records with URL, retrieval time, SHA-256, span and snapshot). Non-available claims: 472 `not_available`,
18 `ambiguous`, 12 `failed`. There are no zeros for missing data.

`ambiguous` websites in this batch include `jott.com`, `sago.com`, `seafood.no` for *A-SEAFOOD AS*, `klinikken.no`
for *E-KLINIKKEN AS*, and franchise/brand sites declared in the registry (`7-eleven.no` for a 7-Eleven
franchisee, `carlin.no`, `betakst.no`). These were deliberately not published as the company's own website.

## Refresh demonstration (same batch, three runs)

| Run | Previous | Changes detected |
|---|---|---|
| `smoke-100-v1` | none | — (first_seen set) |
| `smoke-100-v2` (agent revision) | v1 | `website_lost` × 3 (franchise/group sites reclassified to `ambiguous` by the new rule), `new_activity` × 12 (news items re-keyed by URL) |
| `smoke-100-v3` (same code, minutes later) | v2 | **0 changes**. `first_seen` kept from v1, `last_verified_at` updated |

## Files

- `run-report.json`: v3 report. `run-report-v2-refresh.json`: v2 report with its change counts.
- `envelopes.jsonl.gz`: all 100 v3 envelopes.
- `viewer.html`: open in any browser for search, filters, compare and per-fact sources (desktop and mobile).
- `example-envelope-926790137.json`: one complete envelope, pretty-printed.

## Scale test

`../scale-1000/run-report.json`: 1,000 different companies (seed 99), run with an earlier revision of the same
pipeline. All contract checks passed in 712.7 s of a 2,000 s budget, with 7,225 requests and 563 MB peak memory.
Verified websites: 109 / 1,000.
