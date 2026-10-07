#!/usr/bin/env python3
"""Build the declared NAV ad-metadata seed cache (data/nav-ad-cache.jsonl.gz).

The agent works without it (its background lane syncs details at run time); the seed only makes a cold
first run complete. It holds public ad metadata from NAV's public job feed (employer organisation number,
title, dates, location), keyed by the feed timestamp so stale entries are re-fetched automatically.
Contact persons and ad descriptions are not stored.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.navjobs import AdDetailCache, AdSyncLane, NavJobIndex  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "data" / "nav-ad-cache.jsonl.gz"))
    parser.add_argument("--feed-cache", default=str(ROOT / "state" / "cache" / "nav-feed"))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    started = time.monotonic()
    index = NavJobIndex(days=args.days, cache_dir=Path(args.feed_cache))
    index.start()
    index.wait(None)
    print(index.status, index.note, flush=True)
    cache = AdDetailCache([Path(args.output)])
    lane = AdSyncLane(index, cache, deadline=None, workers=args.workers)
    lane.start()
    while lane.thread.is_alive():
        time.sleep(30)
        known, total = lane.coverage()
        print(f"{known}/{total} active ads with employer known; fetched {lane.fetched}; {time.monotonic() - started:.0f}s", flush=True)
    cache.save(Path(args.output), keep=set(index.entries))
    print("saved", args.output, lane.coverage())


if __name__ == "__main__":
    main()
