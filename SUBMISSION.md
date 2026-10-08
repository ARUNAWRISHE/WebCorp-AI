# Signalpost Round 1 — submission pack

**To:** submit@builderr.ai
**Subject:** Signalpost Round 1 submission

```
Hi,

Signalpost Round 1 submission.

Agent name: WebCorp-AI
Repository URL: https://github.com/ARUNAWRISHE/WebCorp-AI
Exact commit hash: the commit tagged submission-v1 (full SHA in this email: <SHA>)
100-company smoke-test result or report URL:
  https://github.com/ARUNAWRISHE/WebCorp-AI/tree/submission-v1/reports/smoke-100
  (also reports/evaluator-1000, reports/production-1000, reports/stress-1100 and reports/COST.md)
One-command run instruction:
  uv sync --frozen && uv run python run_agent.py --input <batch.jsonl> --output out/envelopes.jsonl
  (pip alternative: python -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.txt
   && .venv/bin/python run_agent.py --input <batch.jsonl> --output out/envelopes.jsonl)
  (optional: SIGNALPOST_TIME_BUDGET_SECONDS=<seconds> to match the run budget; default max(900, 2 × companies))
Models / APIs / licences:
  - Brønnøysund Enhetsregisteret + Regnskapsregisteret open APIs (NLOD 2.0), no key
  - NAV Arbeidsplassen public job-vacancy feed (NAV API terms; public token fetched at run time, no account)
    + declared cache data/nav-ad-cache.jsonl.gz (public ad metadata, re-validated against the live feed each run)
  - Wikidata API (CC0); Mattilsynet smilefjes open data (CC BY 4.0); Arbeidstilsynet cleaning register (NLOD);
    DiBK central-approval API (open; raw responses not stored, at DiBK's request)
  - Company websites under robots.txt (company-reported layer)
  - No model is required. An optional local Ollama qwen3:8b (Apache-2.0) adds a validated plain-English
    "what it does / what changed" where Ollama is installed; otherwise the cited deterministic summary is used
  - Code: MIT/BSD/Apache-licensed Python packages pinned in uv.lock
  - Rights matrix: docs/SOURCES.md
Expected cost per official run: USD 0 (no paid APIs; about 11 requests per company)
Contact for results: ARUNAWRISHE <arunawrishe@gmail.com>
```

## Results in this commit

| Run | Companies | Envelopes | Schema-valid | Elapsed / budget | Cost |
|---|---:|---:|---|---|---|
| [**Evaluator-equivalent**](reports/evaluator-1000/run-report.json) (cold, no LLM, final code) | 1,000 | 1,000 | ✅ | **710 s** / 2,000 s | USD 0 |
| [Smoke](reports/smoke-100/SUMMARY.md) | 100 | 100 | ✅ | 381.5 s / 900 s (cold) | USD 0 |
| [Production](reports/production-1000/run-report.json) | 1,000 | 1,000 | ✅ | 1,957 s / 2,000 s | USD 0 |
| [Stress](reports/stress-1100/run-report.json) | 1,100 | 1,100 | ✅ | 737 s / 1,200 s | USD 0 |

## Checklist

- [x] Repository pushed; submission commit tagged `submission-v1`
- [x] CI workflow `clean-machine` passes on Ubuntu (fresh clone, `uv sync --frozen`, tests, live run)
- [x] 100-company smoke test, 1,000 production and 1,100 stress reports; `reports/COST.md`
- [x] One command, pinned dependencies (`uv.lock`), Python ≥3.12, clean-install tested
- [x] Exactly one terminal envelope per input, including invalid or unknown org numbers and crashes (tested)
- [x] Six availability states only; missing values are never zero
- [x] Claim-level source URL, retrieval time, content hash, span and reporting period
- [x] Refresh: previous snapshot input, typed changes, earlier evidence preserved, idempotent re-run (tested on live data)
- [x] Declared sources, rights and secrets: `docs/SOURCES.md`; no secrets required
- [x] Robots policy decided: documented public APIs and open data (Wikidata, DiBK, Mattilsynet) are used under their
      published terms; rationale in `docs/SOURCES.md`
