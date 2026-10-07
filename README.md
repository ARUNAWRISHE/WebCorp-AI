# Signalpost company research agent

Give it Norwegian organisation numbers. For each one it returns a source-linked company profile: legal identity
and brand, annual accounts with reporting periods, leadership and group, registered workplaces, the verified
official website and company-owned profiles, active job postings, and dated public activity. It also records
what changed since the last run.

Every fact is tied to the exact organisation number and carries its source URL, retrieval time, content
hash and an evidence span. Anything not found is stated explicitly as `not_available`, `blocked`,
`not_applicable`, `ambiguous` or `failed`, and never as zero.

## Run it (one command)

Requires Python ≥3.12 and [uv](https://docs.astral.sh/uv/). No API keys or downloads are needed.

```bash
uv sync --frozen
uv run python run_agent.py --input companies.jsonl --output out/envelopes.jsonl
```

`--input` accepts JSONL (`{"organisation_number": "..."}` or plain strings), JSON, CSV or TXT, optionally gzipped.

| Output | Content |
|---|---|
| `out/envelopes.jsonl` | Exactly one terminal envelope per input, in input order ([schema](docs/DATA_SCHEMA.md)) |
| `out/run-report.json` | Contract checks, runtime, p50/p95, requests, third-party cost, per-field coverage and states |
| `out/viewer.html` | Self-contained viewer: search, filter, compare and verify every fact on desktop or mobile |
| `state/` | Raw snapshots (content-addressed), run history and caches. The next run diffs against `state/latest` |

The agent writes a valid placeholder file at start-up, so an interrupted run still has one envelope per
input. It finishes inside the time budget: `--time-budget` or `SIGNALPOST_TIME_BUDGET_SECONDS`, default
`max(900, 2 × companies)` seconds. Companies not reached in time get `failed` states, never missing rows.

Useful options: `--previous <envelopes.jsonl>` · `--no-previous` · `--workers 48` · `--state-dir state` ·
`--llm off|auto` · `--no-nav` · `--no-wikidata` · `--no-history` · `--registry <frozen snapshot>` (fallback identity).

## How it works

```
input org numbers ──► placeholder envelopes written
   │
   ├─ background: NAV job-feed index (90 days) · Wikidata P2333 lookup · filing-years lane (rate limited)
   │
   ├─ per company (48 workers):  Brønnøysund identity → roles → subunits → accounts (3 yrs, company+group) → group
   │                             → website ladder: registry → Wikidata → subunit → email domain → name-derived domain
   │                             → crawl ≤6 pages (robots.txt) → exact-entity gate → brand, profiles, jobs, news
   │
   ├─ jobs: NAV ads matched by name, published only when employer.orgnr == company or its subunit
   └─ assemble: claims + explicit states → refresh diff vs previous run → cited summary → validate → write
```

- [Identity gates](docs/IDENTITY_RESOLUTION.md): the organisation number, or the current legal name plus a registry contact match. Never name similarity alone.
- [Refresh](docs/REFRESH.md): stable claim ids, typed changes, carry-forward of stale values, superseded evidence kept.
- [Sources and rights](docs/SOURCES.md): official open APIs (NLOD 2.0), NAV public job feed, Wikidata (CC0) and company websites under robots.txt.
- [Limitations](docs/LIMITATIONS.md).

## Models, APIs, licences and cost

| Item | Details |
|---|---|
| APIs | Brønnøysund Enhetsregisteret + Regnskapsregisteret (NLOD 2.0), NAV Arbeidsplassen public feed (NAV API terms), Wikidata API (CC0). All free, no keys |
| Models | **None.** The summary is a deterministic template in which every sentence cites claim ids. An optional local Ollama overview (`--llm auto`, `qwen2.5:7b`, Apache-2.0, GPU) exists but is off by default: in our audit it mistranslated Norwegian activity text, see [docs/EVAL.md](docs/EVAL.md) |
| Code dependencies | beautifulsoup4, lxml, extruct, trafilatura, tldextract, pydantic, pypdf (pinned in `uv.lock`) |
| Third-party cost | **USD 0 per official run** |

## Smoke test

[`reports/smoke-100/`](reports/smoke-100/SUMMARY.md): 100/100 envelopes, schema-valid, 205 s, USD 0. All 5,157
available claims are evidence-backed. An unchanged re-run detects 0 changes. A 1,000-company scale run is in
[`reports/scale-1000/`](reports/scale-1000/run-report.json): all checks passed in 713 s.

## Tests

```bash
uv run --with pytest pytest -q
```

The starter-kit tests, plus agent regression tests: six-state mapping, one envelope per input under crashes,
timeouts and invalid input, wrong-company traps, accounts ordering, refresh idempotency and carry-forward,
and summary citations.

The original starter-kit README is kept at [`docs/starter-kit-README.md`](docs/starter-kit-README.md).
