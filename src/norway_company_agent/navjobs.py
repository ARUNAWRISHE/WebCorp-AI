"""NAV Arbeidsplassen public job-vacancy feed (official, free; terms: https://arbeidsplassen.nav.no/vilkar-api).

The feed is read from a start date with parallel day chains. Candidate ads are matched by employer
name, then each candidate's detail record is fetched and published only when `employer.orgnr` equals
the company's organisation number or one of its registered subunits. Contact persons in ads are not
stored (personal data minimisation); inactive ads are never published.
"""
from __future__ import annotations

import concurrent.futures
import gzip
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from .identity import _tokens
from .net import BudgetExceeded, Meter, Response, get
from .profile import Profile

BASE = "https://pam-stilling-feed.nav.no"
TOKEN_URL = BASE + "/api/publicToken"
FEED_URL = BASE + "/api/v1/feed"
ENTRY_URL = BASE + "/api/v1/feedentry/{uuid}"
TERMS_URL = "https://arbeidsplassen.nav.no/vilkar-api"


def name_key(name: str) -> str:
    return " ".join(sorted(set(_tokens(name))))


class NavJobIndex:
    def __init__(self, *, days: int = 90, deadline: float | None = None, cache_dir: Path | None = None, workers: int = 6):
        self.days = days
        self.deadline = deadline
        self.cache_dir = cache_dir
        self.workers = workers
        self.meter = Meter()
        self.token: str | None = None
        self.entries: dict[str, dict[str, Any]] = {}
        self.by_name: dict[str, list[str]] = {}
        self.by_token: dict[str, set[str]] = {}
        self.status = "pending"
        self.note = ""
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.pages = 0
        self.cached_pages = 0
        self.thread = threading.Thread(target=self._build, daemon=True, name="nav-job-index")

    def start(self) -> None:
        self.thread.start()

    def wait(self, timeout: float | None) -> bool:
        return self.ready.wait(timeout)

    def _headers(self, since: datetime | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if since is not None:
            headers["If-Modified-Since"] = format_datetime(since, usegmt=True)
        return headers

    def _cached(self, page_id: str) -> dict[str, Any] | None:
        if not self.cache_dir:
            return None
        path = self.cache_dir / f"{page_id}.json.gz"
        if path.exists():
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception:
                return None
        return None

    def _store(self, page: dict[str, Any]) -> None:
        if not self.cache_dir or not page.get("id") or not page.get("next_id") or len(page.get("items") or []) < 1000:
            return  # only complete, immutable pages are cached
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{page['id']}.json.gz"
        temporary = path.with_suffix(".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            json.dump(page, handle)
        temporary.replace(path)

    def _fetch(self, url: str, since: datetime | None = None) -> dict[str, Any] | None:
        response = get(url, meter=self.meter, accept="application/json", timeout=40, attempts=3, deadline=self.deadline, headers=self._headers(since))
        if not response.ok:
            return None
        try:
            return response.json()
        except Exception:
            return None

    def _chain_starts(self) -> dict[str, str]:
        if not self.cache_dir:
            return {}
        path = self.cache_dir / "chain-starts.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            return {}

    def _save_chain_starts(self, starts: dict[str, str]) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "chain-starts.json").write_text(json.dumps(starts, sort_keys=True), encoding="utf-8")

    def _chain(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        day_key = start.date().isoformat()
        cached_start = self.chain_starts.get(day_key) if end < datetime.now(timezone.utc) - timedelta(hours=6) else None
        page = self._cached(cached_start) if cached_start else None
        if page is not None:
            with self.lock:
                self.cached_pages += 1
        else:
            page = self._fetch(FEED_URL, since=start)
            if page:
                self._store(page)
                if page.get("id") and page.get("next_id"):
                    with self.lock:
                        self.new_chain_starts[day_key] = page["id"]
        hops = 0
        while page and hops < 60:
            hops += 1
            with self.lock:
                self.pages += 1
            batch = page.get("items") or []
            items.extend(batch)
            last = batch[-1]["date_modified"] if batch else None
            if not page.get("next_id") or (last and datetime.fromisoformat(last) >= end):
                break
            next_id = page["next_id"]
            cached = self._cached(next_id)
            if cached is not None:
                with self.lock:
                    self.cached_pages += 1
                page = cached
                continue
            page = self._fetch(BASE + page["next_url"])
            if page:
                self._store(page)
        return items

    def _build(self) -> None:
        try:
            response = get(TOKEN_URL, meter=self.meter, accept="text/plain", timeout=20, attempts=3, deadline=self.deadline)
            if not response.ok:
                self.status, self.note = "failed", f"public token endpoint returned {response.error or response.status}"
                return
            self.token = response.text().strip().splitlines()[-1].strip()
            self.chain_starts = self._chain_starts()
            self.new_chain_starts: dict[str, str] = {}
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            starts = [today - timedelta(days=day) for day in range(self.days, -1, -1)]
            windows = [(start, start + timedelta(days=1)) for start in starts]
            collected: list[dict[str, Any]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
                for result in pool.map(lambda window: self._chain(*window), windows):
                    collected.extend(result)
            latest: dict[str, dict[str, Any]] = {}
            for item in collected:
                entry = item.get("_feed_entry") or {}
                uuid = entry.get("uuid") or item.get("id")
                if not uuid:
                    continue
                stamp = entry.get("sistEndret") or item.get("date_modified") or ""
                if uuid not in latest or stamp >= (latest[uuid].get("sistEndret") or ""):
                    latest[uuid] = {**entry, "uuid": uuid, "sistEndret": stamp}
            active = {uuid: entry for uuid, entry in latest.items() if entry.get("status") == "ACTIVE"}
            by_name: dict[str, list[str]] = {}
            for uuid, entry in active.items():
                key = name_key(entry.get("businessName") or "")
                if key:
                    by_name.setdefault(key, []).append(uuid)
            by_token: dict[str, set[str]] = {}
            for uuid, entry in active.items():
                for token in set(_tokens(entry.get("businessName") or "")):
                    by_token.setdefault(token, set()).add(uuid)
            self.entries, self.by_name, self.by_token = active, by_name, by_token
            self._save_chain_starts({**self.chain_starts, **self.new_chain_starts})
            self.status = "available"
            self.note = f"{len(active)} active ads indexed from {self.pages} feed pages ({self.cached_pages} cached) covering {self.days} days"
        except BudgetExceeded:
            self.status, self.note = "failed", "run budget exhausted while reading the NAV feed"
        except Exception as exc:
            self.status, self.note = "failed", f"{type(exc).__name__}: {exc}"[:300]
        finally:
            self.ready.set()

    def detail(self, uuid: str, meter: Meter, deadline: float | None) -> Response:
        return get(ENTRY_URL.format(uuid=uuid), meter=meter, accept="application/json", timeout=25, attempts=2, deadline=deadline, headers=self._headers())


# ---- ad-detail cache and sync lane --------------------------------------------------------------
def _ad_record(uuid: str, body: dict[str, Any], response: Response, feed_stamp: str | None = None) -> dict[str, Any] | None:
    """Keep only what is published; contact persons and free-text descriptions are not stored."""
    ad = body.get("ad_content") or {}
    employer = ad.get("employer") or {}
    locations = [loc for loc in ad.get("workLocations") or [] if isinstance(loc, dict)]
    location = next((", ".join(filter(None, [loc.get("city") or loc.get("municipal"), loc.get("county")])) for loc in locations if loc.get("city") or loc.get("municipal")), None)
    occupation = next((f"{item.get('level1')} / {item.get('level2')}" for item in ad.get("occupationCategories") or [] if isinstance(item, dict)), None)
    return {
        "uuid": uuid,
        "sistEndret": feed_stamp or body.get("sistEndret"),  # the feed timestamp that this snapshot answers
        "status": body.get("status"),
        "employer_orgnr": str(employer.get("orgnr") or ""),
        "employer_name": employer.get("name"),
        "title": ad.get("title"),
        "job_title": ad.get("jobtitle"),
        "url": ad.get("link") or f"https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}",
        "published": str(ad.get("published") or "")[:10] or None,
        "expires": str(ad.get("expires") or "")[:10] or None,
        "application_due": ad.get("applicationDue"),
        "location": location,
        "occupation": occupation,
        "positions": ad.get("positioncount"),
        "retrieved_at": response.retrieved_at,
        "content_sha256": response.sha256,
        "source_url": response.url,
    }


class AdDetailCache:
    """uuid -> published ad fields, valid only while the feed's sistEndret is unchanged."""

    def __init__(self, paths: list[Path]):
        self.entries: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.loaded_from: list[str] = []
        for path in paths:
            if path and path.exists():
                try:
                    with gzip.open(path, "rt", encoding="utf-8") as handle:
                        for line in handle:
                            if line.strip():
                                item = json.loads(line)
                                current = self.entries.get(item["uuid"])
                                if current is None or str(item.get("sistEndret") or "") >= str(current.get("sistEndret") or ""):
                                    self.entries[item["uuid"]] = item
                    self.loaded_from.append(str(path))
                except Exception:
                    continue

    def fresh(self, uuid: str, feed_stamp: str | None) -> dict[str, Any] | None:
        with self.lock:
            item = self.entries.get(uuid)
        if item is None or not feed_stamp or str(item.get("sistEndret") or "")[:19] != str(feed_stamp)[:19]:
            return None
        return item

    def put(self, item: dict[str, Any]) -> None:
        with self.lock:
            self.entries[item["uuid"]] = item

    def save(self, path: Path, keep: set[str] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with self.lock:
            items = [item for uuid, item in self.entries.items() if keep is None or uuid in keep]
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            for item in sorted(items, key=lambda value: value["uuid"]):
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        temporary.replace(path)


class AdSyncLane:
    """Background lane that fetches details for active ads missing from the cache (newest first)."""

    def __init__(self, index: NavJobIndex, cache: AdDetailCache, *, deadline: float | None, workers: int = 8):
        self.index, self.cache, self.deadline, self.workers = index, cache, deadline, workers
        self.meter = Meter()
        self.fetched = 0
        self.priority: list[str] = []
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True, name="nav-ad-sync")
        self.stop_flag = threading.Event()

    def start(self) -> None:
        self.thread.start()

    def prioritise(self, uuids: list[str]) -> None:
        with self.lock:
            self.priority = list(dict.fromkeys(uuids + self.priority))

    def _next(self, pending: list[str]) -> str | None:
        with self.lock:
            while self.priority:
                uuid = self.priority.pop(0)
                if uuid in self.index.entries and not self.cache.fresh(uuid, self.index.entries[uuid].get("sistEndret")):
                    return uuid
            while pending:
                uuid = pending.pop()
                if not self.cache.fresh(uuid, self.index.entries[uuid].get("sistEndret")):
                    return uuid
        return None

    def _run(self) -> None:
        self.index.ready.wait(timeout=None if self.deadline is None else max(0.0, self.deadline - time.monotonic()))
        if self.index.status != "available":
            return
        pending = sorted(self.index.entries, key=lambda uuid: self.index.entries[uuid].get("sistEndret") or "")  # pop() = newest first

        def work() -> None:
            while not self.stop_flag.is_set() and (self.deadline is None or time.monotonic() < self.deadline):
                uuid = self._next(pending)
                if uuid is None:
                    return
                try:
                    response = self.index.detail(uuid, self.meter, self.deadline)
                    if response.ok:
                        record = _ad_record(uuid, response.json(), response, self.index.entries.get(uuid, {}).get("sistEndret"))
                        if record:
                            self.cache.put(record)
                            with self.lock:
                                self.fetched += 1
                except BudgetExceeded:
                    return
                except Exception:
                    continue

        threads = [threading.Thread(target=work, daemon=True) for _ in range(self.workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def employer_map(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for uuid, entry in self.index.entries.items():
            item = self.cache.fresh(uuid, entry.get("sistEndret"))
            if item and item.get("employer_orgnr"):
                mapping.setdefault(item["employer_orgnr"], []).append(uuid)
        return mapping

    def coverage(self) -> tuple[int, int]:
        total = len(self.index.entries)
        known = sum(1 for uuid, entry in self.index.entries.items() if self.cache.fresh(uuid, entry.get("sistEndret")))
        return known, total


def name_candidates(profile: Profile, index: NavJobIndex) -> list[str]:
    names = [profile.facts.get("name") or ""]
    names += [unit.get("name") or "" for unit in profile.facts.get("subunits") or []][:20]
    names += [claim["value"] for claim in profile.claims.values() if claim["field"] == "public_brand_name" and isinstance(claim["value"], str)]
    keys = {name_key(name) for name in names if name}
    keys.discard("")
    candidates: list[str] = []
    for key in keys:
        candidates.extend(index.by_name.get(key, []))
    # Employer names often add a department or place ("X AS avd Bergen"): all distinctive name tokens present.
    for name in names[:1] + [unit.get("name") or "" for unit in profile.facts.get("subunits") or []][:5]:
        tokens = sorted(set(_tokens(name)))
        if not tokens or (len(tokens) == 1 and len(tokens[0]) < 6):
            continue
        sets = [index.by_token.get(token, set()) for token in tokens]
        if all(sets):
            matched = set.intersection(*sets)
            if len(matched) <= 60:
                candidates.extend(sorted(matched))
    return list(dict.fromkeys(candidates))


def collect_jobs(profile: Profile, index: NavJobIndex, lane: AdSyncLane | None = None, employer_map: dict[str, list[str]] | None = None, *, max_details: int = 25) -> None:
    if index.status != "available":
        profile.check("job_posting", "failed", f"NAV job feed unavailable in this run: {index.note}")
        return
    org = profile.organisation_number
    valid_orgs = {org} | {str(unit.get("organisation_number")) for unit in profile.facts.get("subunits") or [] if unit.get("organisation_number")}
    by_org = [uuid for valid in valid_orgs for uuid in (employer_map or {}).get(valid, [])]
    candidates = list(dict.fromkeys(by_org + name_candidates(profile, index)))[: max(max_details, len(by_org))]
    if not candidates:
        known, total = lane.coverage() if lane else (0, len(index.entries))
        profile.check("job_posting", "not_available",
                      f"No active NAV Arbeidsplassen ad has this organisation number or a registered subunit as employer "
                      f"(employer known for {known} of {total} active ads; name matching used for the rest).")
        return
    today = datetime.now(timezone.utc).date().isoformat()
    published = 0
    for uuid in candidates:
        feed_entry = index.entries.get(uuid) or {}
        record = lane.cache.fresh(uuid, feed_entry.get("sistEndret")) if lane else None
        response = None
        if record is None:
            try:
                response = index.detail(uuid, profile.meter, profile.deadline)
            except BudgetExceeded:
                profile.check("job_posting", "failed", "Run budget exhausted while verifying NAV job ads.")
                break
            if not response.ok:
                continue
            try:
                record = _ad_record(uuid, response.json(), response, feed_entry.get("sistEndret"))
            except Exception:
                continue
            if lane and record:
                lane.cache.put(record)
        if not record or record.get("status") != "ACTIVE" or record.get("employer_orgnr") not in valid_orgs:
            continue
        if record.get("expires") and record["expires"] < today:
            continue
        span = f"employer.orgnr={record['employer_orgnr']}; status=ACTIVE; sistEndret={feed_entry.get('sistEndret') or record.get('sistEndret')}; title={str(record.get('title'))[:100]}"
        if response is not None:
            ev = profile.evidence_from_response(response, "official_job_feed", "nav_feed_entry_v2", span=span)
        else:
            ev = profile.evidence_ref(source_url=record["source_url"], source_class="official_job_feed", extractor="nav_feed_entry_v2_cached",
                                      retrieved_at=record.get("retrieved_at"), sha=record.get("content_sha256"), span=span + "; still ACTIVE with unchanged sistEndret in today's feed")
        value = {key: record.get(key) for key in ("title", "job_title", "url", "published", "expires", "application_due", "location", "occupation", "positions", "employer_name")}
        value.update({"employer_organisation_number": record["employer_orgnr"], "employer_is_subunit": record["employer_orgnr"] != org, "source": "NAV Arbeidsplassen public job feed"})
        profile.claim("job_posting", f"nav:{uuid}", value, [ev], confidence=0.97, effective_at=value["published"],
                      note="Exact match: the ad's employer organisation number equals this company or one of its registered subunits.")
        published += 1
    if not published:
        profile.check("job_posting", "not_available", f"{len(candidates)} candidate NAV ads checked; none is active with this organisation number as employer.")
