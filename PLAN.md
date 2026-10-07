# Signalpost Round 1 — implementation plan

Target: an official run with **≥65/100**, **zero wrong-company publications**, and one envelope for every input.
Deadlines: revisions close **18 Oct 2026**, the round ends 21 Oct. Up to 5 versions in total, and
earlier batch scores are never replaced. A weak v1 therefore lowers the final mean.

Score weights: recall/coverage 50 (70% company coverage, 30% fact count) · precision/evidence 30 ·
synthesis 12 · UX 8.

---

## Stage 0 — Repo setup (prerequisite, about 1 hour)

| Task | Detail |
|---|---|
| `git init` and a private GitHub repo | The submission needs a repo URL and an exact commit hash |
| `.gitignore` | `out/`, `state/`, `.venv/`, `._*` (macOS junk), `*.jsonl.gz`, `docs/financial-filer-master-2025.jsonl` (131 MB, over GitHub's 100 MB limit) |
| Delete `._*` files | AppleDouble metadata, no content |
| Baseline test run | `uv run --with pytest pytest -q`, recording what fails on Windows |

**Done when:** first commit is pushed and the baseline test result is recorded.

---

## P0 — Contract and reliability (gates qualification)

### 1. Six states
- New `src/norway_company_agent/states.py`, with one mapping used everywhere:

| Internal | Contract state |
|---|---|
| `available` + identity `exact` | `available` |
| `available` + identity `review` (0.8–0.9) | `ambiguous` (facts withheld) |
| `available` + identity `related_or_uncertain` | `ambiguous` or `not_available` (decided by score) |
| `not_found`, 404/410, no registry URL | `not_available` |
| `blocked`, robots, SSRF guard, size limit | `blocked` |
| No accounts and the form is not always obliged (accounting-obligation rule) | `not_applicable` |
| `source_error`, exception, timeout, budget exhausted | `failed` |

- Replace `TERMINAL_STATES` in `batch.py`. Validation accepts only the six.
- **Done when:** a unit test covers every internal state, and no other value can reach output.

### 2. Envelope guarantee
- Each company is processed inside `try/except BaseException`. Any crash produces a `failed` envelope with the error text, never a missing row.
- Output is written **incrementally** (append plus fsync per company), and the final pass pads anything missing with `failed`.
- Input loader: accept JSON, JSONL, TXT or CSV. Any org number absent from the registry snapshot falls back to the live Brreg API. If that also fails, emit `failed` and keep the row.
- **Done when:** a fault-injection test (crash, timeout, unknown org, invalid org) produces N in and N out.

### 3. Time budget
- `--time-budget-seconds` (also read from an env variable). The global deadline is the start time plus the budget minus a safety margin.
- Per-company soft budget = remaining time / remaining companies, with a hard cap per HTTP call (10 s, already used in Scrapy).
- Modules run in priority order: registry → financials → roles → locations → website → discovery → external. At the deadline, remaining modules become `failed` with `budget_exhausted`.
- The `financial_history` serial lock (2.1 s per request) is off by default.
- **Done when:** a 100-company run with a 60-second budget still emits 100 envelopes.

### 4. Windows compatibility
- `operations.py`: `resource` is imported only when available. Elsewhere it falls back to `psutil` or `None`.
- `iter_bulk`: accept `.csv`, `.csv.gz`, `.jsonl` and `.jsonl.gz` (the universe file is JSONL).
- README commands become cross-platform (`python`, not `python3`/`cp`).
- **Done when:** the full test suite passes on Windows. The evaluator is likely Linux, so also check under WSL or Docker.

### 5. Resume and idempotency
- Stable IDs: `claim_id = sha256(org | field | normalised value | source_url)` and `evidence_id = sha256(content bytes)`.
- Ledger upserts are keyed by ID, with `first_seen` and `last_seen`.
- Re-running on the same snapshot gives zero new claims, zero changes and byte-identical claims and evidence (excluding run timestamps).
- **Done when:** the same run executed twice yields 0 duplicates and 0 false changes, verified by a test.

### 6. Snapshot integration
- `--previous <envelopes.jsonl>` input, which defaults to the last run in `state/`.
- Content-addressed raw store at `state/snapshots/<sha256>`. Raw bytes are kept, so prior evidence is never overwritten.
- A failed refresh carries forward the last supported value, marked `stale` with the failure shown, and is never erased.
- **Done when:** the refresh-replay fixture still passes (2 expected changes, 0 false changes) through the main runner.

**P0 exit:** one command, the six states, N in and N out under fault injection, budget-safe, Windows plus Linux, idempotent.

---

## P1 — Recall (the big score)

### 7. Website discovery (89% of the universe has no registry website)
Strategy ladder. Each step runs only when the previous one fails, and every candidate must pass the identity gate.

| Order | Strategy | Cost | Notes |
|---|---|---|---|
| a | Registry website | free | Existing code |
| b | Domain guessing: `{name}.no` and `{name-with-hyphens}.no`, plus `.com` | free | Includes a DNS check; the name comes from legal-name tokens |
| c | Search API (Brave; `run_brave_discovery.py` exists) | paid | Ask Builderr for a key and keep queries within budget |
| d | Brreg subunit names used as brand aliases → b/c | free | Bridges a legal name to a trading name |

**Identity gate tightening** (wrong-company matches block qualification):
- `exact` requires the org number on the site, **or** the full legal name plus one corroborator: postcode/address, phone, or a Brreg role-holder name.
- Directory, parent and franchise detection: if multiple org numbers are on the page, or the page belongs to a known directory host, the result is `ambiguous`.
- **Done when:** on a hand-labelled set of 200 (100 positive, 100 hard negatives) there are **0 wrong-company matches**, with recall measured and reported.

### 8. External intelligence (from verified sources only)

| Information type | Source | Method |
|---|---|---|
| Social handles | Verified site links and JSON-LD `sameAs` | Existing; normalise and gate |
| People | Brreg roles plus the site's `ledelse`/team pages | Match names against Brreg roles |
| Locations | Brreg subunits plus site contact/JSON-LD `PostalAddress` | Normalise addresses |
| Jobs | Site `/karriere` and `/jobs` pages, JSON-LD `JobPosting`, NAV Arbeidsplassen public feed (official) | Filter by org number where the feed carries it; **verify feed terms** |
| Dated activity | Site news pages, RSS/Atom feeds, sitemap `lastmod` (`extract_company_site_news.py` exists) | Requires a dated item, URL and hash |
| Video | YouTube Data API (official) for handles linked from the verified site | Optional, if a key is available |

Excluded from published claims: LinkedIn guest, Google News RSS and Fagfolkguiden scripts (source-terms risk). These stay private experiments.

- **Done when:** each information type reports company coverage and fact count on a 100-company development set, with 0 wrong-company matches in a manual audit of 50 published facts.

### 9. Claim-level evidence
- Pydantic models in `src/norway_company_agent/schema.py`: `Envelope`, `Claim`, `Evidence`, `Change`, `ErrorItem`, `Operations`.
- `Claim`: `field`, `value`, `availability`, `confidence`, `evidence_ids`, `reporting_period` (financials), `effective_at`, `extractor` and version.
- `Evidence`: `source_url`, `final_url`, redirect chain, `source_class`, `retrieved_at`, `content_sha256`, `claim_span` / selector / JSON path.
- Converter from today's per-module records to claims.
- **Done when:** every published claim has ≥1 evidence item with a span or path, and the schema validates 100%.

### 10. Change detection
- Typed changes: `new_role`, `removed_role`, `new_filing`, `financial_value_changed`, `new_location`, `closed_location`, `new_job`, `closed_job`, `new_activity`, `website_changed`, `description_changed`, `state_changed`.
- Each change carries old and new values, evidence IDs for both sides, `first_seen` / `last_seen` and a materiality flag.
- Extends `refresh.diff_profile` to work at claim level.
- **Done when:** a seeded-change fixture reaches ≥95% precision and recall, with 0 false changes on an identical re-run.

---

## P2 — Synthesis and UX (20 points)

### 11. LLM synthesis (12 points)
- Input: **verified claims only**, each with a claim ID. Output: a summary of what the company does, key numbers, what changed and what is unknown. Every sentence cites claim IDs.
- Validator: reject any sentence with no citation, or any number or name not present in the cited claims. On rejection, fall back to a deterministic template.
- No key, or budget exhausted → template summary. The run never fails because of the LLM.
- The model is pinned and the key comes from an env variable only. Ask Builderr for the key, since a personal key is not allowed. Prefer a small, cheap model and size token budgets per company.
- **Done when:** 50 summaries manually checked show 0 unsupported statements, and cost per 1,000 companies is measured.

### 12. Mobile UX (8 points)
- Extend the existing `scripts/build_prototype.py`, which already emits responsive HTML, into one self-contained `out/viewer/index.html`.
- Features: search by name or org number; filter by state, legal form and municipality; compare 2–3 companies; per-fact source link, date and hash; change timeline; state badges.
- Generated automatically at the end of every run.
- **Done when:** it works at 375 px and on desktop, and every fact is clickable through to its source.

---

## FINAL — Submission

| # | Task | Done when |
|---|---|---|
| 13 | **Clean-machine test:** fresh clone at the pinned commit → empty venv → `uv sync --frozen` → run command, on Linux (Docker) and Windows | Both pass with no manual step |
| 14 | **100-company smoke test:** hash-seeded sample from the universe, using the official command | Report published in the repo: per-state counts, per-type coverage, p50/p95, requests, cost, errors |
| 15 | **Cost report:** search queries × price plus LLM tokens × price, measured from `operations` | Per-100 and per-1,000 cost stated |
| 16 | **Rights report** `SOURCES.md`: source, access mode, terms link, retention, rights status | Every connector used in output is listed |
| 17 | **Submission pack:** README one-command, models/APIs/licences, commit hash, email draft | Email sent by you after review (I draft it, not send it) |

Additional repo docs suggested by the playbook: `AGENT.md`, `IDENTITY_RESOLUTION.md`, `DATA_SCHEMA.md`, `REFRESH.md`, `EVAL.md`, `LIMITATIONS.md`.

---

## Timeline (today is 7 Oct)

| Dates | Work | Milestone |
|---|---|---|
| 7–8 Oct | Stage 0 + P0 items 1–4 | Runner contract-compliant |
| 9 Oct | P0 items 5–6 + item 9 (schema) | Idempotent refresh |
| 10–11 Oct | Item 7 website discovery + gold labels | 0 wrong-company matches on the labelled set |
| 12 Oct | Items 8, 10 | All information types collected |
| 13 Oct | Items 13–17 | **Submit v1** (strong enough to protect the mean) |
| 14–15 Oct | Items 11–12 | v2 |
| 16–17 Oct | Recall tuning from smoke and audit error buckets | v3 |
| 18 Oct | Final freeze | Last revision |

---

## Risks

| Risk | Mitigation |
|---|---|
| Wrong-company match on a guessed or search-found domain | Org number or full name plus a corroborator is required; ambiguous cases abstain |
| Unknown time budget | Ask Builderr. The deadline guard means any budget still gives N out |
| No search or LLM key | Free strategies (b, d) and the template synthesis keep the run valid |
| Source-terms violation | Only permitted, official or company-owned sources are published; the rest stay private experiments |
| Evaluator on Linux, development on Windows | Docker clean-machine test before each submission |

## Open questions for Builderr / you
1. Time and resource budget per official run (seconds, CPU, memory, network allowlist)?
2. Can they supply search-API and LLM keys, and what are the env-var names?
3. Exact envelope schema: is `OUTPUT_CONTRACT.md` authoritative?
4. Has v1 already been submitted?
