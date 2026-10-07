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
100-company smoke-test result or report URL: [<repo>/tree/<commit>/reports/smoke-100]
One-command run instruction:
  uv sync --frozen && uv run python run_agent.py --input <batch.jsonl> --output out/envelopes.jsonl
  (optional: SIGNALPOST_TIME_BUDGET_SECONDS=<seconds> to match the run budget; default max(900, 2 × companies))
Models / APIs / licences:
  - Brønnøysund Enhetsregisteret and Regnskapsregisteret open APIs (NLOD 2.0), no key
  - NAV Arbeidsplassen public job-vacancy feed (NAV API terms; public token fetched at run time), no account
  - Wikidata API (CC0), no key
  - Company websites, robots.txt enforced, company-reported layer
  - No LLM is required or used by default. Optional local Ollama qwen2.5:7b (Apache-2.0) is off by default.
  - Code: MIT/BSD/Apache-licensed Python packages pinned in uv.lock
Expected cost per official run: USD 0 (no paid APIs)
Contact for results: [name, harishraagav@struzon.com]
```

## Checklist

- [ ] Push to a repository Builderr can clone, then record the exact commit hash
- [ ] Confirm the CI workflow `clean-machine` passes on Ubuntu (fresh clone → `uv sync --frozen` → tests → live run)
- [x] 100-company smoke test: `reports/smoke-100/` (report, envelopes, viewer)
- [x] One command, pinned dependencies (`uv.lock`), Python ≥3.12
- [x] Exactly one terminal envelope per input, including invalid or unknown org numbers and crashes (tested)
- [x] Six availability states only; missing values are never zero
- [x] Claim-level source URL, retrieval time, content hash, span and reporting period
- [x] Refresh: previous snapshot input, typed changes, earlier evidence preserved, idempotent re-run (tested)
- [x] Declared sources, rights and secrets: `docs/SOURCES.md`; no secrets required
