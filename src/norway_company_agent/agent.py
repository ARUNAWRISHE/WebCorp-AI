"""Signalpost batch agent: one terminal envelope per input organisation number, within a time budget."""
from __future__ import annotations

import concurrent.futures
import csv
import gzip
import hashlib
import json
import queue
import threading
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import brreg
from .changes import refresh
from .contract import SECTIONS, AVAILABILITY_STATES, summarise_states, validate_envelope
from .navjobs import NavJobIndex, collect_jobs
from .net import AGENT_VERSION, BudgetExceeded, utc_now
from .operations import latency_summary, peak_rss_bytes
from .profile import FIELD_SECTIONS, OPTIONAL_FIELDS, Profile
from .site_extract import extract_site
from .store import SnapshotStore, read_jsonl, write_jsonl_atomic
from .synthesis import llm_summary, ollama_available, template_summary
from .webdiscovery import resolve_website
from .wikidata import WikidataLookup

SECTION_ORDER = list(SECTIONS)


@dataclass
class RunConfig:
    input_path: str
    output: str = "out/envelopes.jsonl"
    report: str = "out/run-report.json"
    viewer: str | None = "out/viewer.html"
    run_id: str = ""
    state_dir: str | None = "state"
    previous_path: str | None = None
    use_previous: bool = True
    time_budget: float | None = None
    workers: int = 48
    registry_path: str | None = None
    llm: str = "auto"
    llm_model: str = "qwen2.5:7b"
    nav_days: int = 90
    use_nav: bool = True
    use_wikidata: bool = True
    use_history: bool = True
    max_crawls: int = 4
    store_raw: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


# ---- inputs -------------------------------------------------------------------------------------
def read_inputs(path: str) -> list[dict[str, Any]]:
    source = Path(path)
    opener = gzip.open if source.suffix == ".gz" else open
    suffixes = [suffix.casefold() for suffix in source.suffixes]
    with opener(source, "rt", encoding="utf-8-sig") as handle:
        text = handle.read()
    raw: list[Any] = []
    if ".json" in suffixes and ".jsonl" not in suffixes:
        body = json.loads(text)
        if isinstance(body, dict):
            body = body.get("organisation_numbers") or body.get("organisations") or body.get("companies") or []
        raw = list(body)
    elif ".jsonl" in suffixes:
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    raw.append(json.loads(line))
                except json.JSONDecodeError:
                    raw.append(line)
    elif ".csv" in suffixes:
        reader = csv.reader(text.splitlines())
        rows = list(reader)
        if rows:
            header = [cell.strip().casefold() for cell in rows[0]]
            column = next((i for i, cell in enumerate(header) if cell in {"organisation_number", "orgnr", "organisasjonsnummer", "org_number"}), None)
            data = rows[1:] if column is not None or not "".join(rows[0]).replace(" ", "").isdigit() else rows
            raw = [row[column or 0] for row in data if row]
    else:
        raw = [line.strip() for line in text.splitlines() if line.strip()]
    inputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in raw:
        candidate = value
        if isinstance(value, dict):
            candidate = value.get("organisation_number") or value.get("orgnr") or value.get("organisasjonsnummer") or value.get("org")
        digits = "".join(ch for ch in str(candidate or "") if ch.isdigit())
        key = digits if len(digits) == 9 else str(candidate or "").strip()
        if key in seen:
            continue
        seen.add(key)
        inputs.append({"organisation_number": key, "valid": len(digits) == 9, "raw": candidate})
    return inputs


def load_registry_rows(path: str | None, wanted: set[str]) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    digest = hashlib.sha256()
    rows: dict[str, dict[str, Any]] = {}
    opener = gzip.open if source.suffix == ".gz" else open
    if ".jsonl" in [suffix.casefold() for suffix in source.suffixes]:
        with opener(source, "rt", encoding="utf-8") as handle:
            for line in handle:
                digest.update(line.encode())
                if '"' not in line:
                    continue
                row = json.loads(line)
                if row.get("organisation_number") in wanted:
                    rows[row["organisation_number"]] = row
    else:
        from .sampling import iter_bulk
        for row in iter_bulk(source):
            if row["organisation_number"] in wanted:
                rows[row["organisation_number"]] = {key: value for key, value in row.items() if key != "raw"}
    sha = digest.hexdigest()
    for row in rows.values():
        row["_snapshot_sha256"] = sha
    return rows


# ---- research ------------------------------------------------------------------------------------
def _guard(profile: Profile, module: str, fields: list[str], fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except BudgetExceeded:
        profile.error(module, "failed", "Run budget exhausted before this module completed.")
        for name in fields:
            profile.check(name, "failed", "Run budget exhausted before this source was checked.")
    except Exception as exc:  # never lose the company because one module crashed
        profile.error(module, "failed", f"{type(exc).__name__}: {exc}")
        profile.facts.setdefault("tracebacks", []).append(traceback.format_exc()[-1500:])
        for name in fields:
            profile.check(name, "failed", f"Module error: {type(exc).__name__}")
    return None


def research_company(profile: Profile, *, bulk_row: dict[str, Any] | None, wikidata: WikidataLookup | None, max_crawls: int) -> None:
    identity_fields = ["legal_name", "legal_form", "registry_status", "business_address", "industry", "business_purpose", "founded_date", "registered_employees"]
    entity = _guard(profile, "registry", identity_fields, brreg.collect_entity, profile, bulk_row)
    if entity is None and profile.modules.get("registry") != "available":
        for name in FIELD_SECTIONS:
            if name not in identity_fields:
                profile.check(name, "not_applicable" if profile.modules.get("registry") == "not_available" else "failed",
                              "Entity not found in Enhetsregisteret." if profile.modules.get("registry") == "not_available" else "Identity lookup failed; dependent sources were not queried.")
        return
    _guard(profile, "roles", ["role"], brreg.collect_roles, profile)
    _guard(profile, "workplaces", ["registered_workplace"], brreg.collect_subunits, profile)
    _guard(profile, "financials", ["annual_account_metric", "annual_account_filing"], brreg.collect_accounts, profile)
    _guard(profile, "group", ["group_relation"], brreg.collect_group, profile)
    wiki_hit = None
    if wikidata is not None:
        left = profile.budget_left()
        wikidata.ready.wait(timeout=max(0.0, min(90.0, (left or 90.0) - 10)))
        if wikidata.ready.is_set():
            wiki_hit = _guard(profile, "wikidata", ["knowledge_base_entry"], wikidata.apply, profile)
        else:
            profile.check("knowledge_base_entry", "failed", "Wikidata lookup did not finish in time.")
    else:
        profile.check("knowledge_base_entry", "not_applicable", "Wikidata connector disabled for this run.")

    web_fields = ["official_website", "social_profile", "news_item"]
    result = _guard(profile, "website", web_fields, resolve_website, profile, wiki_hit, max_crawls=max_crawls)
    if result is None:
        return
    capture, assessment, attempts = result
    profile.facts["website_attempts"] = attempts
    if capture is not None and assessment is not None:
        _guard(profile, "website_extract", ["social_profile", "news_item", "job_posting"], extract_site, profile, capture, assessment)
        profile.modules["website"] = "available"
        return
    # No verified website: record what was tried, honestly.
    states = [item.get("outcome") for item in attempts]
    if assessment is not None and assessment.get("status") == "ambiguous":
        candidate = assessment["candidate"]
        state = "ambiguous"
        note = f"Candidate {candidate['url']} (from {candidate['source']}) could not be tied to this organisation number: {'; '.join(assessment.get('reasons', [])[:2])}."
    elif not attempts:
        state, note = "not_available", "No website is registered and no candidate domain could be derived from official data."
    elif any(item == "blocked" for item in states) and not any(item in {"rejected", "ambiguous"} for item in states):
        state, note = "blocked", "Candidate website refused automated access (robots.txt or access control)."
    elif all(item == "failed" for item in states):
        state, note = "failed", "Candidate website could not be fetched in this run."
    else:
        state = "not_available"
        note = "No verified official website: " + "; ".join(f"{item['domain']} ({item['source']}): {item.get('outcome')}" for item in attempts[:5])
    if facts_registry := profile.facts.get("registry_website"):
        note += f" Registry-declared website: {facts_registry}."
    profile.check("official_website", state, note[:500], [item["evidence_id"] for item in attempts if item.get("evidence_id")])
    dependent = "not_available" if state in {"not_available", "ambiguous"} else state
    profile.check("social_profile", dependent, "No verified company website to read profile links from.")
    profile.check("news_item", dependent, "No verified company website to read dated news from.")
    profile.modules["website"] = state


# ---- assembly ------------------------------------------------------------------------------------
def build_envelope(profile: Profile, *, run_id: str, started_at: str, completed_at: str, terminal_status: str, runtime_ms: int) -> dict[str, Any]:
    with profile.lock:
        available = [dict(item) for item in profile.claims.values()]
        evidence = {key: dict(item) for key, item in profile.evidence.items()}
        placeholders = profile.placeholder_claims()
        errors = [dict(item) for item in profile.errors]
        company = dict(profile.company)
    claims = available + placeholders
    section_rank = {name: index for index, name in enumerate(SECTION_ORDER)}
    claims.sort(key=lambda item: (section_rank.get(item["section"], 99), item["field"], item["availability"] != "available", item["key"]))
    used = {eid for item in claims for eid in item["evidence_ids"]}
    evidence_list = sorted((item for key, item in evidence.items() if key in used), key=lambda item: item["id"])
    for error in errors:
        if error["state"] not in AVAILABILITY_STATES:
            error["state"] = "failed"
    return {
        "organisation_number": profile.organisation_number,
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": completed_at, "terminal_status": terminal_status, "agent_version": AGENT_VERSION},
        "company": company,
        "sections": {},
        "summary": {},
        "claims": claims,
        "evidence": evidence_list,
        "changes": [],
        "errors": errors,
        "operations": {"requests": profile.meter.requests, "runtime_ms": runtime_ms, "third_party_cost_usd": 0.0, "bytes": profile.meter.bytes},
    }


def compute_sections(envelope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for section, title in SECTIONS.items():
        fields: dict[str, str] = {}
        counts: Counter[str] = Counter()
        for claim in envelope["claims"]:
            if claim["section"] != section:
                continue
            counts[claim["availability"]] += 1
            fields[claim["field"]] = summarise_states([fields[claim["field"]], claim["availability"]]) if claim["field"] in fields else claim["availability"]
        sections[section] = {"title": title, "availability": summarise_states(list(fields.values())) if fields else "not_available",
                             "available_claims": counts.get("available", 0), "fields": fields}
    return sections


def failed_envelope(organisation_number: str, *, run_id: str, started_at: str, message: str) -> dict[str, Any]:
    now = utc_now()
    claims = [{"id": f"cl-failed-{field_name}", "field": field_name, "section": FIELD_SECTIONS[field_name], "key": "*", "value": None,
               "availability": "failed", "confidence": None, "evidence_ids": [], "reporting_period": None, "effective_at": None, "note": message}
              for field_name in FIELD_SECTIONS if field_name not in OPTIONAL_FIELDS]
    envelope = {
        "organisation_number": organisation_number,
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": now, "terminal_status": "failed", "agent_version": AGENT_VERSION},
        "company": {}, "sections": {}, "summary": {"method": "none", "text": None, "unknowns_text": message},
        "claims": claims, "evidence": [], "changes": [],
        "errors": [{"module": "agent", "state": "failed", "message": message, "url": None}],
        "operations": {"requests": 0, "runtime_ms": 0, "third_party_cost_usd": 0.0, "bytes": 0},
    }
    envelope["sections"] = compute_sections(envelope)
    return envelope


# ---- main run ------------------------------------------------------------------------------------
def run(config: RunConfig) -> dict[str, Any]:
    t0 = time.monotonic()
    started_at = utc_now()
    run_id = config.run_id or "run-" + started_at.replace(":", "").replace("-", "")
    inputs = read_inputs(config.input_path)
    organisations = [item["organisation_number"] for item in inputs]
    valid = [item["organisation_number"] for item in inputs if item["valid"]]
    budget = config.time_budget if config.time_budget and config.time_budget > 0 else max(900.0, 2.0 * len(inputs))
    safety = min(max(15.0, 0.03 * budget), 0.1 * budget)
    reserve = min(max(45.0, 0.12 * budget), 0.3 * budget)  # time kept for jobs, assembly and writing
    deadline = t0 + budget - safety
    phase_a_deadline = deadline - reserve
    output_path = Path(config.output)

    # Crash safety: a complete, valid file exists from the first second of the run.
    write_jsonl_atomic(output_path, (failed_envelope(org, run_id=run_id, started_at=started_at, message="Run did not finish (placeholder written at start).") for org in organisations))

    store = SnapshotStore(config.state_dir if (config.state_dir and config.store_raw) else None)
    history_store = SnapshotStore(config.state_dir) if config.state_dir else SnapshotStore(None)
    previous: dict[str, dict[str, Any]] = {}
    previous_source = None
    if config.use_previous:
        previous_path = Path(config.previous_path) if config.previous_path else history_store.latest_envelopes_path()
        if previous_path and previous_path.exists():
            previous = {row["organisation_number"]: row for row in read_jsonl(previous_path)}
            previous_source = str(previous_path)
    bulk_rows = load_registry_rows(config.registry_path, set(valid))

    cache_dir = Path(config.state_dir) / "cache" / "nav-feed" if config.state_dir else None
    nav = NavJobIndex(days=config.nav_days, deadline=deadline - 30, cache_dir=cache_dir) if config.use_nav else None
    wiki = WikidataLookup(valid, deadline=phase_a_deadline) if config.use_wikidata and valid else None
    lane = brreg.FilingYearsLane(deadline) if config.use_history and valid else None
    for component in (nav, wiki):
        if component:
            component.start()
    if lane:
        lane.start(valid)

    profiles: dict[str, Profile] = {}
    finished: dict[str, float] = {}
    work: queue.Queue[str] = queue.Queue()
    for org in valid:
        profiles[org] = Profile(org, store, deadline=phase_a_deadline)
        work.put(org)

    def worker() -> None:
        while True:
            try:
                org = work.get_nowait()
            except queue.Empty:
                return
            profile = profiles[org]
            started = time.monotonic()
            try:
                if time.monotonic() < phase_a_deadline:
                    research_company(profile, bulk_row=bulk_rows.get(org), wikidata=wiki, max_crawls=config.max_crawls)
                else:
                    profile.error("agent", "failed", "Run budget exhausted before this company was started.")
            except Exception as exc:
                profile.error("agent", "failed", f"{type(exc).__name__}: {exc}")
            finally:
                finished[org] = time.monotonic() - started
                work.task_done()

    threads = [threading.Thread(target=worker, daemon=True, name=f"worker-{index}") for index in range(max(1, min(config.workers, len(valid) or 1)))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(0.0, min(phase_a_deadline + 20, deadline - 0.25 * reserve) - time.monotonic()))
    phase_a_seconds = time.monotonic() - t0

    # Phase B: hiring from the official NAV feed (needs identity + subunits from phase A).
    nav_note = "disabled"
    if nav is not None:
        nav.wait(timeout=max(0.0, deadline - 60 - time.monotonic()))
        nav_note = nav.note if nav.ready.is_set() else "NAV feed index not ready within the run budget"
        if not nav.ready.is_set():
            nav.status, nav.note = "failed", nav_note
        eligible = [org for org in valid if profiles[org].modules.get("registry") == "available"]
        for org in eligible:
            profiles[org].deadline = deadline - 20

        def jobs(org: str) -> None:
            _guard(profiles[org], "jobs", ["job_posting"], collect_jobs, profiles[org], nav)

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(jobs, org) for org in eligible]
            concurrent.futures.wait(futures, timeout=max(1.0, deadline - 15 - time.monotonic()))
    else:
        for org in valid:
            profiles[org].check("job_posting", "not_applicable", "NAV job connector disabled for this run.")

    if lane is not None:
        lane.stop_flag.set()
        for org in valid:
            if profiles[org].modules.get("registry") == "available":
                lane.apply(profiles[org])
    else:
        for org in valid:
            profiles[org].check("filed_account_years", "not_applicable", "Filing-year connector disabled for this run.")

    # Phase C: assemble, refresh, summarise, validate, write.
    completed_at = utc_now()
    envelopes: list[dict[str, Any]] = []
    llm_enabled = config.llm != "off" and ollama_available(config.llm_model)
    llm_used = 0
    validation_failures: list[dict[str, Any]] = []
    for item in inputs:
        org = item["organisation_number"]
        if not item["valid"]:
            envelopes.append(failed_envelope(org, run_id=run_id, started_at=started_at, message=f"Input {item['raw']!r} is not a 9-digit Norwegian organisation number."))
            continue
        profile = profiles[org]
        terminal = "completed" if profile.modules.get("registry") in {"available", "not_available"} else "failed"
        envelope = build_envelope(profile, run_id=run_id, started_at=started_at, completed_at=completed_at, terminal_status=terminal,
                                  runtime_ms=int(finished.get(org, time.monotonic() - profile.started) * 1000))
        failed_fields = {claim["field"] for claim in envelope["claims"] if claim["key"] == "*" and claim["availability"] in {"failed", "blocked"}}
        refresh(previous.get(org), envelope, detected_at=completed_at, failed_fields=failed_fields)
        envelope["sections"] = compute_sections(envelope)
        envelope["summary"] = template_summary(envelope)
        problems = validate_envelope(envelope)
        if problems:
            validation_failures.append({"organisation_number": org, "problems": problems[:5]})
            envelope = failed_envelope(org, run_id=run_id, started_at=started_at, message="Envelope failed schema validation: " + "; ".join(problems[:2]))
        envelopes.append(envelope)

    if llm_enabled:
        def enrich(envelope: dict[str, Any]) -> None:
            nonlocal llm_used
            if time.monotonic() > deadline - 10 or not envelope["summary"].get("sentences"):
                return
            result = llm_summary(envelope, envelope["summary"], model=config.llm_model, timeout=min(60.0, max(5.0, deadline - 10 - time.monotonic())))
            if result:
                envelope["summary"] = result
                llm_used += 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(enrich, envelope) for envelope in envelopes if envelope["run"]["terminal_status"] == "completed"]
            concurrent.futures.wait(futures, timeout=max(1.0, deadline - 5 - time.monotonic()))

    write_jsonl_atomic(output_path, envelopes)
    if config.state_dir:
        history_store.archive_run(run_id, output_path)

    report = build_report(config, envelopes, inputs, profiles, finished, run_id=run_id, started_at=started_at, completed_at=utc_now(), budget=budget,
                          elapsed=time.monotonic() - t0, phase_a_seconds=phase_a_seconds, nav=nav, nav_note=nav_note, wiki=wiki, lane=lane,
                          previous_source=previous_source, llm_enabled=llm_enabled, llm_used=llm_used, validation_failures=validation_failures)
    Path(config.report).parent.mkdir(parents=True, exist_ok=True)
    Path(config.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if config.viewer:
        from .viewer import build_viewer
        build_viewer(envelopes, report, config.viewer)
    return report


def build_report(config: RunConfig, envelopes: list[dict[str, Any]], inputs: list[dict[str, Any]], profiles: dict[str, Profile], finished: dict[str, float], *,
                 run_id: str, started_at: str, completed_at: str, budget: float, elapsed: float, phase_a_seconds: float, nav: NavJobIndex | None,
                 nav_note: str, wiki: WikidataLookup | None, lane: Any, previous_source: str | None, llm_enabled: bool, llm_used: int,
                 validation_failures: list[dict[str, Any]]) -> dict[str, Any]:
    field_states: dict[str, Counter[str]] = {}
    field_companies: Counter[str] = Counter()
    field_claims: Counter[str] = Counter()
    for envelope in envelopes:
        families: dict[str, list[str]] = {}
        for claim in envelope["claims"]:
            families.setdefault(claim["field"], []).append(claim["availability"])
            if claim["availability"] == "available":
                field_claims[claim["field"]] += 1
        for name, states in families.items():
            state = summarise_states(states)
            field_states.setdefault(name, Counter())[state] += 1
            if state == "available":
                field_companies[name] += 1
    n = len(envelopes) or 1
    website_sources = Counter()
    for envelope in envelopes:
        for claim in envelope["claims"]:
            if claim["field"] == "official_website" and claim["availability"] == "available":
                website_sources[claim.get("discovery_source") or "unknown"] += 1
    lane_requests = sum(component.meter.requests for component in (nav, wiki, lane) if component is not None)
    company_requests = sum(profile.meter.requests for profile in profiles.values())
    orgs = [envelope["organisation_number"] for envelope in envelopes]
    expected = [item["organisation_number"] for item in inputs]
    return {
        "run_id": run_id,
        "agent_version": AGENT_VERSION,
        "started_at": started_at,
        "completed_at": completed_at,
        "input": config.input_path,
        "input_count": len(inputs),
        "emitted_envelopes": len(envelopes),
        "checks": {
            "one_envelope_per_input": orgs == expected,
            "unique_organisation_numbers": len(set(orgs)) == len(orgs),
            "zero_silent_drops": len(envelopes) == len(inputs),
            "schema_valid": not validation_failures,
            "only_contract_states": all(claim["availability"] in AVAILABILITY_STATES for envelope in envelopes for claim in envelope["claims"]),
            "within_time_budget": elapsed <= budget,
        },
        "terminal_status": dict(Counter(envelope["run"]["terminal_status"] for envelope in envelopes)),
        "validation_failures": validation_failures[:20],
        "time_budget_seconds": round(budget, 1),
        "elapsed_seconds": round(elapsed, 1),
        "phase_a_seconds": round(phase_a_seconds, 1),
        "per_company_runtime": latency_summary([value * 1000 for value in finished.values()]),
        "requests": {"total": company_requests + lane_requests, "per_company_mean": round(company_requests / n, 1), "background_lanes": lane_requests},
        "bytes": sum(profile.meter.bytes for profile in profiles.values()),
        "third_party_cost_usd": 0.0,
        "peak_rss_bytes": peak_rss_bytes(),
        "coverage": {
            name: {"companies_available": field_companies.get(name, 0), "company_coverage": round(field_companies.get(name, 0) / n, 4),
                   "available_claims": field_claims.get(name, 0), "states": dict(field_states.get(name, {}))}
            for name in FIELD_SECTIONS
        },
        "website_discovery_sources": dict(website_sources),
        "changes": dict(Counter(change["type"] for envelope in envelopes for change in envelope.get("changes", []))),
        "previous_snapshot": previous_source,
        "connectors": {
            "nav_job_feed": {"status": nav.status if nav else "disabled", "note": nav_note},
            "wikidata": {"status": wiki.status if wiki else "disabled", "note": wiki.note if wiki else ""},
            "filing_years_lane": {"checked": len(lane.results) if lane else 0},
            "local_llm": {"enabled": llm_enabled, "model": config.llm_model if llm_enabled else None, "summaries": llm_used},
        },
        "summary_methods": dict(Counter((envelope.get("summary") or {}).get("method") for envelope in envelopes)),
    }
