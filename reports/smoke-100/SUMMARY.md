# 100-company smoke test (final)

- **Batch:** `companies.jsonl`, selected with `uv run python select_entry_batch.py --universe <public universe> --count 100`
  (default seed `20260823`). The agent was not tuned on this batch.
- **Command:** `uv run python run_agent.py --input reports/smoke-100/companies.jsonl --output out/envelopes.jsonl`
  (defaults: 48 workers, budget `max(900, 2 × N)` = 900 s, `--llm auto`; cold state, no Ollama running, so the cited deterministic summary was used).
- **Machine:** Windows 11 laptop, 16 logical CPUs, RTX 5060 8 GB (local LLM only), residential broadband.

## Contract checks (run `smoke-100-final`, file `run-report.json`)

| Check | Result |
|---|---|
| One terminal envelope per input, in input order | ✅ 100 / 100 |
| Unique organisation numbers, zero silent drops | ✅ |
| Schema-valid envelopes (Pydantic, plus every claim's evidence present) | ✅ 100 / 100 |
| Only the six contract states | ✅ |
| Within time budget | ✅ 381.5 s of 900 s (cold state) |
| Terminal status | 100 `completed` |
| Requests | 1,380 (10.6 per company + 317 background) |
| Per-company runtime | p50 23.6 s, p95 46.4 s, max 69.0 s |
| Third-party cost | **USD 0** |
| Peak memory | 651 MB |

## What was found

6,197 claims, of which 5,497 are `available`. **All 5,497 available claims carry evidence** (3,676 evidence
records with URL, retrieval time, SHA-256, span and snapshot). Non-available claims are explicit:
483 `not_available`, 189 `not_applicable`, 16 `ambiguous`, 12 `failed`. There are no zeros for missing data.

| Field family | Companies | Facts |
|---|---:|---:|
| Legal identity (name, form, status, address, NACE, registered activity, founded) | 100 | — |
| Annual accounts: 3 years, company and group, each with reporting period | 100 | 2,825 figures |
| Filing history (filed years + official copy links) | 100 | 100 |
| Roles (board, CEO, auditor, accountant) | 100 | 387 |
| Dated registry events (registration, articles, capital, role changes) | 100 | 900 |
| Registered workplaces | 73 | 76 |
| Registered employees | 10 | 10 |
| Group relations | 8 | 12 |
| Registry-declared website / verified own website | 7 / 7 | — |
| Social profiles (verified site or Wikidata) | 3 | 8 |
| Dated company news | 4 | 32 |
| Food-safety inspection (Mattilsynet) | 1 | 1 |
| Public approvals (DiBK, Arbeidstilsynet) | 2 | 2 |
| Active NAV job postings | 0 | 0 (none exist for this batch; see the stress test for 9 companies with 18 postings) |

**Synthesis:** all 100 profiles carry the cited deterministic summary, readable "what changed" sentences and the
deterministic list of unknowns. The optional local LLM paraphrase was off in this run (no Ollama running);
it is not needed for any contract field.

`ambiguous` websites were deliberately not published as the company's own website. Examples: `jott.com`,
`sago.com`, franchise or brand sites declared in the registry such as `7-eleven.no`, `carlin.no` and `betakst.no`,
and pages inside other organisations' sites. Each withheld site states its reason in plain language.

## Refresh check (same batch, second run)

| Run | Previous | Elapsed | Changes detected |
|---|---|---:|---|
| `smoke-100-final` (cold) | none | 381.5 s | — (first seen) |
| `smoke-100-final-rerun` (warm state, same code) | previous run | 166.4 s | **0 changes** across 100 companies |

Change detection, carry-forward and idempotency are also covered by the regression tests (`tests/test_agent.py`).

## Files

- `run-report.json`: report of the cold run above.
- `envelopes.jsonl.gz`: all 100 envelopes of that run.
- `viewer.html`: open in any browser for search, filters, compare and per-fact sources (desktop and mobile).
- `example-envelope-827340162.json`, `example-envelope-926790137.json`: complete envelopes, pretty-printed.

See also [`../COST.md`](../COST.md), [`../production-1000/`](../production-1000/run-report.json) and
[`../stress-1100/`](../stress-1100/run-report.json).
