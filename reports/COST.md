# Cost, requests and runtime

Machine: Windows 11 laptop, 16 logical CPUs, NVIDIA RTX 5060 Laptop GPU (8 GB, used only by the optional local
LLM), residential broadband. All runs use the single evaluator command with default settings unless stated.

| Run | Companies | Budget | Elapsed | Research phase | Requests | Requests / company | Data downloaded | Per-company p50 / p95 | Peak memory | Third-party cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [**Evaluator-equivalent**](evaluator-1000/run-report.json) (cold state, no LLM, final code) | 1,000 | 2,000 s | **710 s** | 577 s | 11,045 | 10.5 | — | 22.0 s / 54.0 s | 805 MB | **USD 0** |
| [Production](production-1000/run-report.json) (default command, local LLM on) | 1,000 | 2,000 s | 1,957 s¹ | 506 s | 11,290 | 11.3 | 366 MB | 18.3 s / 48.3 s | 666 MB | **USD 0** |
| [Stress](stress-1100/run-report.json) (`--llm off`, tight budget) | 1,100 | 1,200 s | 737 s | 611 s | 12,072 | 11.0 | 421 MB | 21.2 s / 52.5 s | 793 MB | **USD 0** |
| [Smoke](smoke-100/run-report.json) | 100 | 900 s | see report¹ | — | about 1,100 | about 11 | — | — | about 500 MB | **USD 0** |

¹ Production and smoke runs used an earlier revision that waited for the filing-years lane, plus local-LLM synthesis
in the remaining budget. The final code does not hold the batch for background lanes: a cold 1,000-company run
without an LLM (as on Builderr's evaluator) finishes in 710 s.

- **Cost per company: USD 0.** Every source is free and no paid API is called. The optional model runs locally.
- **Per official batch of 1,000–1,100: USD 0**, about 11 requests per company plus about 600–900 background requests
  (NAV feed, Wikidata, register downloads, filing-years lane).
- **Rate-limited lane:** filing-year history (about 30 requests/min) runs alongside research and is no longer waited
  for afterwards. It covers about 340 of 1,000 companies; the rest are reported as `blocked` (rate limit) for that one
  field only. The 3 years of normalised accounts are always complete.
- **Budget behaviour:** the default budget is `max(900, 2 × companies)` seconds, overridable with
  `--time-budget` or `SIGNALPOST_TIME_BUDGET_SECONDS`. Under the tight 1,200 s budget for 1,100 companies,
  every company still received a complete, schema-valid envelope.

## Coverage at scale (companies with at least one available value)

| Field family | Production 1,000 | Stress 1,100 |
|---|---:|---:|
| Legal identity, accounts (3 yrs), roles, registry events | 996–1,000 | ≥1,096 |
| Registered workplaces | 760 | see report |
| Verified official website | 116 (11.6%) | 125 (11.4%) |
| Company-linked social profiles | 62 | 75 |
| Dated company news | 30 (193 items) | 44 (299 items) |
| Active job postings (NAV, exact by employer org number) | 2 | 9 (18 postings) |
| Food-safety inspections (Mattilsynet) | 18 | 18 |
| Public approvals (DiBK, Arbeidstilsynet) | 30 | 26 |
| Filed-year history | 582 | 355 (tight budget) |
