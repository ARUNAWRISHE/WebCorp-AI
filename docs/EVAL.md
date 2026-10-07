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
- **Local LLM summary (GPU).** In a development audit, `qwen2.5:7b` mistranslated Norwegian activity text: a housing
  cooperative ("borettslag") was rendered as "borehole drilling", and "malertjenester" (painting) as "malarial services".
  The LLM is therefore **off by default**. The cited deterministic template is the summary.

## Promotion rule used

A change was kept only when it did not add a wrong-company publication on the audited corpora, kept every
published claim evidence-backed (schema validation enforces this), and added coverage or fixed a contract
gap. Each fix comes with a regression test in `tests/test_agent.py`.
