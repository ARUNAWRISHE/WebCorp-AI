# Signalpost Round 1 — submission pack (draft)

> Fill in the bracketed fields after pushing the repository. The agent itself needs no keys.

**To:** submit@builderr.ai
**Subject:** Signalpost Round 1 submission

```
Hi,

Signalpost Round 1 submission.

Agent name: [Struzon Signalpost Agent]
Repository URL: [https://github.com/<org>/<repo>]
Exact commit hash: [git rev-parse HEAD]
100-company smoke-test result or report URL: [<repo>/tree/<commit>/reports/smoke-100] (also production-1000, stress-1100, COST.md)
One-command run instruction:
  uv sync --frozen && uv run python run_agent.py --input <batch.jsonl> --output out/envelopes.jsonl
  (optional: SIGNALPOST_TIME_BUDGET_SECONDS=<seconds> to match the run budget; default max(900, 2 × companies))
Models / APIs / licences:
  - Brønnøysund Enhetsregisteret + Regnskapsregisteret open APIs (NLOD 2.0), no key
  - NAV Arbeidsplassen public job-vacancy feed (NAV API terms; public token fetched at run time, no account)
    + declared cache data/nav-ad-cache.jsonl.gz (public ad metadata, re-validated against the live feed each run)
  - Wikidata API (CC0); Mattilsynet smilefjes open data (CC BY 4.0); Arbeidstilsynet cleaning register (NLOD);
    DiBK central-approval API (open; raw responses not stored, at DiBK's request)
  - Company websites under robots.txt (company-reported layer)
  - No model is required. Optional local Ollama qwen3:8b (Apache-2.0) adds a validated plain-English
    "what it does / what changed" where Ollama is installed; otherwise the cited deterministic summary is used
  - Code: MIT/BSD/Apache-licensed Python packages pinned in uv.lock
Expected cost per official run: USD 0 (no paid APIs)
Contact for results: [name, harishraagav@struzon.com]
```

## Checklist

- [ ] Push to a repository Builderr can clone, then record the exact commit hash
- [ ] Confirm the CI workflow `clean-machine` passes on Ubuntu (fresh clone → `uv sync --frozen` → tests → live run)
- [x] 100-company smoke test: `reports/smoke-100/` (report, envelopes, viewer); 1,000 production and 1,100 stress reports; `reports/COST.md`
- [x] One command, pinned dependencies (`uv.lock`), Python ≥3.12
- [x] Exactly one terminal envelope per input, including invalid or unknown org numbers and crashes (tested)
- [x] Six availability states only; missing values are never zero
- [x] Claim-level source URL, retrieval time, content hash, span and reporting period
- [x] Refresh: previous snapshot input, typed changes, earlier evidence preserved, idempotent re-run (tested)
- [x] Declared sources, rights and secrets: `docs/SOURCES.md`; no secrets required
- [ ] **Decide the API-vs-robots policy** for Wikidata, DiBK and Mattilsynet (documented in `docs/SOURCES.md`); if declined, run with `--no-wikidata --no-registers`
