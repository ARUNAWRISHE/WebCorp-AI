#!/usr/bin/env python3
"""Rebuild the HTML viewer from existing envelopes (no research needed).

    uv run python scripts/build_viewer.py --envelopes out/envelopes.jsonl --report out/run-report.json --output out/viewer.html
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.viewer import build_viewer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelopes", required=True, help="envelopes.jsonl or envelopes.jsonl.gz")
    parser.add_argument("--report", required=True, help="run-report.json written next to the envelopes")
    parser.add_argument("--output", default="out/viewer.html")
    args = parser.parse_args()
    opener = gzip.open if args.envelopes.endswith(".gz") else open
    with opener(args.envelopes, "rt", encoding="utf-8") as handle:
        envelopes = [json.loads(line) for line in handle if line.strip()]
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    build_viewer(envelopes, report, args.output)
    print(f"Wrote {args.output} ({len(envelopes)} companies)")


if __name__ == "__main__":
    main()
