# Signalpost company research agent

Give it Norwegian organisation numbers. For each one it returns a source-linked company profile:
- legal identity and brand;
- three years of annual accounts with reporting periods;
- leadership and group;
- registered workplaces;
- the verified official website and company-owned profiles;
- active job postings;
- dated public activity;
- official inspections and approvals;
- what changed since the last run.

Every fact is tied to the exact organisation number and carries its source URL, retrieval time, content hash and
an evidence span. Anything not found is stated explicitly as `not_available`, `blocked`, `not_applicable`,
`ambiguous` or `failed`, and never as zero.

## Run it (one command)

Requires Python ≥3.12 and [uv](https://docs.astral.sh/uv/). No API keys.

```bash
uv sync --frozen
uv run python run_agent.py --input companies.jsonl --output out/envelopes.jsonl
```

Without uv (pip, Python ≥3.12, hash-pinned):

```bash
python -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python run_agent.py --input companies.jsonl --output out/envelopes.jsonl
```

`--input` accepts JSONL (`{"organisation_number": "..."}` or plain strings), JSON, CSV or TXT, optionally gzipped.

| Output | Content |
|---|---|
| `out/envelopes.jsonl` | Exactly one terminal envelope per input, in input order ([schema](docs/DATA_SCHEMA.md)) |
| `out/run-report.json` | Contract checks, runtime, p50/p95, requests, third-party cost, per-field coverage and states, connector status |
| `out/viewer.html` | Self-contained viewer (open in any browser, no server): global evidence-coverage and data-freshness indicators, text state badges, per-section facts with sources, compare, light/dark, mobile. Rebuild from existing envelopes with `uv run python scripts/build_viewer.py --envelopes out/envelopes.jsonl --report out/run-report.json` |
| `state/` | Raw snapshots (content-addressed), run history and caches. The next run diffs against `state/latest` |

The agent writes a valid placeholder file at start-up, so an interrupted run still has one envelope per input.
It finishes inside the time budget: `--time-budget` or `SIGNALPOST_TIME_BUDGET_SECONDS`, default
`max(900, 2 × companies)` seconds. Companies not reached in time get `failed` states, never missing rows.

Options: `--previous <envelopes.jsonl>` · `--no-previous` · `--workers 48` · `--state-dir state` · `--llm auto|off` ·
`--no-nav` · `--no-wikidata` · `--no-registers` · `--no-history` · `--registry <frozen snapshot>` (fallback identity).

## How it works

```
input org numbers ──► placeholder envelopes written
  │
  ├─ background: NAV job-feed index + ad-detail sync (declared seed cache) · Wikidata P2333 · sector registers
  │              (Mattilsynet, Arbeidstilsynet) · filing-years lane (rate limited)
  │
  ├─ per company (48 workers): Brønnøysund identity → roles (+ role-change history) → subunits → 3 years of accounts → group
  │     → website ladder: registry → Wikidata → subunit → email domain → name-derived and brand domains
  │     → crawl ≤6 pages under robots.txt (+ contact/about/privacy probes) → exact-entity gate
  │     → brand, description, profiles, careers/jobs, dated news (+ /nyheter, /feed probes)
  │
  ├─ jobs: NAV ads whose employer org number = the company or one of its registered establishments
  ├─ registers: food-safety inspections, cleaning approval, DiBK central approval (construction)
  └─ assemble: claims + explicit states → refresh diff → cited summary (+ optional local LLM) → validate → write
```

- [Identity gates](docs/IDENTITY_RESOLUTION.md): org number, the unique registered legal name with its legal form,
  or the current name plus a registry contact match. Never name similarity alone; group and franchise sites are not
  attributed.
- [Refresh](docs/REFRESH.md): stable claim ids, typed changes rendered as readable sentences with evidence,
  carry-forward of stale values, superseded evidence kept.
- [Sources and rights matrix](docs/SOURCES.md) · [Limitations](docs/LIMITATIONS.md) · [Evaluation log](docs/EVAL.md)

## Models, APIs, licences and cost

| Item | Details |
|---|---|
| APIs and open data | Brønnøysund Enhetsregisteret + Regnskapsregisteret (NLOD 2.0); NAV Arbeidsplassen public job feed (NAV API terms); Wikidata (CC0); Mattilsynet smilefjes (CC BY 4.0); Arbeidstilsynet cleaning register (NLOD); DiBK central-approval API. All free, no keys |
| Declared cache | `data/nav-ad-cache.jsonl.gz`: public NAV ad metadata (employer org number, title, dates), re-validated against the live feed every run |
| Models | **None required.** Summaries are a deterministic template in which every sentence cites claim ids. Where Ollama with `qwen3:8b` (Apache-2.0) is installed, `--llm auto` adds a validated plain-English "what it does" and "what changed" (citations, verbatim source quotes, no new numbers, English only); unknowns always stay deterministic |
| Code dependencies | beautifulsoup4, lxml, extruct, trafilatura, tldextract, pydantic, pypdf (pinned in `uv.lock`) |
| Third-party cost | **USD 0 per official run** |

## Validation

See [`reports/`](reports/), especially [`reports/smoke-100/SUMMARY.md`](reports/smoke-100/SUMMARY.md), for the
100-company smoke test, the 1,000-company production test and the 1,100-company stress test: run reports,
envelopes, viewer and refresh demonstrations.

```bash
uv run --with pytest pytest -q
```

Agent regression tests: six-state mapping, one envelope per input under crashes,
timeouts and invalid input, wrong-company traps (successor, franchise, foreign namesake, parked domain),
accounts ordering, refresh idempotency and carry-forward, readable changes, and summary citations.
