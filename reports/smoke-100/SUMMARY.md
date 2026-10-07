# 100-company smoke test (final)

- **Batch:** `companies.jsonl`, selected with `uv run python select_entry_batch.py --universe <public universe> --count 100`
  (default seed `20260823`). The agent was not tuned on this batch.
- **Command:** `uv run python run_agent.py --input reports/smoke-100/companies.jsonl --output out/envelopes.jsonl`
  (defaults: 48 workers, budget `max(900, 2 × N)` = 900 s, `--llm auto`).
- **Machine:** Windows 11 laptop, 16 logical CPUs, RTX 5060 8 GB (local LLM only), residential broadband.

## Contract checks (run `smoke-100-v5`, file `run-report.json`)

| Check | Result |
|---|---|
| One terminal envelope per input, in input order | ✅ 100 / 100 |
| Unique organisation numbers, zero silent drops | ✅ |
| Schema-valid envelopes (Pydantic, plus every claim's evidence present) | ✅ 100 / 100 |
| Only the six contract states | ✅ |
| Within time budget | ✅ 774 s of 900 s (idle time used by the local LLM; 207 s with `--llm off`, see v6) |
| Terminal status | 100 `completed` |
| Requests | 1,158 (10.5 per company + 108 background) |
| Third-party cost | **USD 0** |
| Peak memory | 685 MB |

## What was found

6,194 claims, of which 5,494 are `available`. **All 5,494 available claims carry evidence** (3,673 evidence
records with URL, retrieval time, SHA-256, span and snapshot). Non-available claims are explicit:
480 `not_available`, 189 `not_applicable`, 17 `ambiguous`, 12 `failed`, 2 `blocked`. There are no zeros for missing data.

| Field family | Companies | Facts |
|---|---:|---:|
| Legal identity (name, form, status, address, NACE, registered activity, founded) | 100 | — |
| Annual accounts: 3 years, company and group, each with reporting period | 100 | 2,825 figures |
| Filing history (filed years + official copy links) | 100 | 100 |
| Roles (board, CEO, auditor, accountant) | 100 | 387 |
| Dated registry events (registration, articles, capital, role changes) | 100 | 899 |
| Registered workplaces | 73 | 76 |
| Group relations | 8 | 12 |
| Registry-declared website / verified own website | 7 / 7 | — |
| Social profiles (verified site or Wikidata) | 3 | 8 |
| Dated company news | 4 | 32 |
| Food-safety inspection (Mattilsynet) | 1 | 1 |
| Public approvals (DiBK, Arbeidstilsynet) | 2 | 2 |
| Active NAV job postings | 0 | 0 (none exist for this batch; see the stress test for 9 companies with 18 postings) |

**Synthesis:** 96 of 100 profiles carry a validated local-LLM "what it does" (plain-English paraphrase of the cited
registered purpose, with verbatim source quotes). All 100 have the cited deterministic summary, readable
"what changed" sentences and the deterministic list of unknowns.

`ambiguous` websites were deliberately not published as the company's own website. Examples: `jott.com`,
`sago.com`, franchise or brand sites declared in the registry such as `7-eleven.no`, `carlin.no` and `betakst.no`,
and pages inside other organisations' sites.

## Refresh demonstration (same batch, six runs)

| Run | Previous | Changes detected |
|---|---|---|
| v1 | none | — (first_seen set) |
| v2–v5 | previous run | Code-driven: franchise sites reclassified (`website_lost` × 3), new connectors' first observations (non-material registry events, approvals, inspections) |
| v3 (same code as v2) | v2 | **0 changes** |
| **v6** (`--llm off`, same code as v5, about 45 minutes later) | v5 | **One genuine registry change caught:** *TEAMTEC WASTE TO ENERGY AS* changed accountant (Cedra Norge Momentum AS → Cedra Norge AS), registered 2026-10-07. Summary: "New Regnskapsfører: CEDRA NORGE AS. Regnskapsfører CEDRA NORGE MOMENTUM AS is no longer registered." Nothing else changed across 100 companies |

## Files

- `run-report.json`: v5 report. `run-report-v6-idempotency.json`: v6 report with its change counts.
- `envelopes.jsonl.gz`: all 100 v5 envelopes.
- `viewer.html`: open in any browser for search, filters, compare and per-fact sources (desktop and mobile).
- `example-envelope-827340162.json`, `example-envelope-926790137.json`: complete envelopes, pretty-printed.

See also [`../COST.md`](../COST.md), [`../production-1000/`](../production-1000/run-report.json) and
[`../stress-1100/`](../stress-1100/run-report.json).
