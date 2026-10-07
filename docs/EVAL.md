# Evaluation and control loop

## Corpora

| Corpus | How it was selected | Purpose |
|---|---|---|
| 5 / 40-company probes | Hand-picked large companies plus a random sample | Smoke and connector debugging |
| Development 100 | `select_entry_batch.py --seed 1` | Error-bucket review: website gate, news extraction, LLM audit |
| Smoke 100 | `select_entry_batch.py` default seed `20260823` | Submission smoke test; no tuning was done on this batch |

## What is measured

The run report (`out/run-report.json`) records contract checks (one envelope per input, unique, schema-valid,
contract-only states, within budget), per-field company coverage and claim counts, the state distribution per
field, website discovery sources, request counts, bytes, p50/p95 per-company runtime, peak memory, connector
status and third-party cost.

## Precision audits performed

- **Website gate.** Every verified site in the 40-company probe and the development 100 was reviewed. Two classes of
  risk were found and fixed:
  1. A *former* name plus a role-holder name matched a successor company's domain. Discovered domains now need the
     *current* legal name plus a contact corroborator.
  2. Registry-declared group/parent sites. These are now linked, but their profiles, news and jobs are not
     attributed (`site_specific` flag).
  Plausible but unproven candidates, such as a newspaper with the same name or foreign `.com` namesakes, are
  returned as `ambiguous`.
- **Accounts.** The starter's `normalize_financials` took the oldest record as the latest. The agent now sorts by
  period, keeps company and group scope apart, and puts the reporting period on every figure (regression test).
- **Local LLM summary, audit 1 (GPU, `qwen2.5:7b`).** In a development audit, `qwen2.5:7b` mistranslated Norwegian activity text: a housing
  cooperative ("borettslag") was rendered as "borehole drilling", and "malertjenester" (painting) as "malarial services".
  The LLM was therefore turned off at that point (superseded by audit 2 below: `qwen3:8b` with grounding checks, on by default where Ollama exists; the cited template always remains the factual summary).

## Promotion rule used

A change was kept only when it did not add a wrong-company publication on the audited corpora, kept every
published claim evidence-backed (schema validation enforces this), and added coverage or fixed a contract
gap. Each fix comes with a regression test in `tests/test_agent.py`.

## Round 2 (website recall, jobs, registers, LLM)

- **Website recall.** Re-running the 233 uncertain companies from the 1,000-company test with identity-page probes,
  www/apex fallback and registered-name proof verified 9 more sites, all checked by hand. 29 former "ambiguous"
  candidates became `not_available` once the hostname stopped counting as name evidence: they were foreign or parked
  namesakes such as `hms365.com` (a Chinese music school) and `bemaco.com` (a Spanish florist). The remaining
  ambiguous cases are mostly parked domains or name matches without any proof.
- **Jobs root cause.** Every one of the 6,031 employer numbers on active NAV ads is an *establishment* (subunit) number;
  none is a main-entity number. Name matching found 1 in 1,000. The agent now matches through registered subunits
  against a full employer map (9,656 of 9,667 active ads). A sample estimate puts about 0.7% of universe companies
  in active NAV ads.
- **LLM audit 2 (`qwen3:8b`, glossary, verbatim-quote grounding, English check).** 40 companies: 39 accepted. The
  earlier errors were fixed: "malertjenester" → painting, "hylleselskap" → shelf company, "rørlegger" → plumbing,
  "borettslag" → housing cooperative, and "may" kept for purpose clauses. The remaining issue was broad English NACE
  division labels leaking into the paraphrase ("land transport and transport via pipelines" for road haulage), so
  English division labels were removed from the LLM input.
