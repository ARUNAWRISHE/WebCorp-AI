#!/usr/bin/env python3
"""Signalpost company research agent — the one evaluator command.

    uv run python run_agent.py --input companies.jsonl --output out/envelopes.jsonl

Reads organisation numbers (JSONL/JSON/CSV/TXT, optionally .gz), researches each company from official
and permitted sources, and writes exactly one terminal envelope per input, plus a run report and an
HTML viewer. Exit code is 0 when every input has a valid envelope.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.agent import RunConfig, run  # noqa: E402


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    try:
        return float(value) if value else None
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Signalpost company research agent")
    parser.add_argument("--input", required=True, help="Organisation numbers: .jsonl/.json/.csv/.txt (optionally .gz)")
    parser.add_argument("--output", default="out/envelopes.jsonl", help="Terminal envelope JSONL (one per input)")
    parser.add_argument("--report", default="out/run-report.json", help="Machine-readable run report")
    parser.add_argument("--viewer", default="out/viewer.html", help="HTML viewer path ('' to skip)")
    parser.add_argument("--run-id", default=os.environ.get("SIGNALPOST_RUN_ID", ""))
    parser.add_argument("--state-dir", default=os.environ.get("SIGNALPOST_STATE_DIR", "state"), help="Snapshots, run history and caches ('' disables)")
    parser.add_argument("--previous", default=None, help="Previous envelopes JSONL for refresh (default: latest run in --state-dir)")
    parser.add_argument("--no-previous", action="store_true", help="Ignore earlier runs (no change detection)")
    parser.add_argument("--time-budget", type=float, default=_env_float("SIGNALPOST_TIME_BUDGET_SECONDS"),
                        help="Wall-clock budget in seconds (default: max(900, 2 × companies))")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SIGNALPOST_WORKERS", "48")))
    parser.add_argument("--registry", default=os.environ.get("SIGNALPOST_REGISTRY_SNAPSHOT"), help="Optional frozen registry snapshot (fallback identity)")
    parser.add_argument("--llm", choices=("auto", "off"), default=os.environ.get("SIGNALPOST_LLM", "auto"),
                        help="auto (default): when a local Ollama model is available, add validated plain-English synthesis (what it does / what changed / unknowns); off: cited deterministic summary only")
    parser.add_argument("--llm-model", default=os.environ.get("SIGNALPOST_LLM_MODEL", "qwen3:8b"))
    parser.add_argument("--nav-days", type=int, default=90)
    parser.add_argument("--no-nav", action="store_true", help="Disable the NAV job-feed connector")
    parser.add_argument("--no-wikidata", action="store_true")
    parser.add_argument("--no-history", action="store_true", help="Disable the rate-limited filing-years lane")
    parser.add_argument("--no-registers", action="store_true", help="Disable sector registers (Mattilsynet, Arbeidstilsynet, DiBK)")
    parser.add_argument("--no-raw-snapshots", action="store_true", help="Do not store raw response bytes")
    args = parser.parse_args()

    config = RunConfig(
        input_path=args.input, output=args.output, report=args.report, viewer=args.viewer or None, run_id=args.run_id,
        state_dir=args.state_dir or None, previous_path=args.previous, use_previous=not args.no_previous, time_budget=args.time_budget,
        workers=args.workers, registry_path=args.registry, llm=args.llm, llm_model=args.llm_model, nav_days=args.nav_days,
        use_nav=not args.no_nav, use_wikidata=not args.no_wikidata, use_history=not args.no_history, use_registers=not args.no_registers, store_raw=not args.no_raw_snapshots,
    )
    report = run(config)
    print(json.dumps({key: report[key] for key in ("run_id", "input_count", "emitted_envelopes", "checks", "terminal_status", "elapsed_seconds", "requests")},
                     ensure_ascii=False, indent=2))
    return 0 if report["checks"]["one_envelope_per_input"] and report["checks"]["schema_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
