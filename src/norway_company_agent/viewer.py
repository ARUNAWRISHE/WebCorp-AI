"""Self-contained HTML viewer for a run: search, filter, compare and verify every fact on desktop or mobile."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .nace import division_label

FIELD_LABELS = {
    "legal_name": "Legal name", "legal_form": "Legal form / capital", "registry_status": "Registry status", "business_address": "Address",
    "industry": "Industry (NACE)", "business_purpose": "Registered activity", "founded_date": "Founded", "registered_employees": "Registered employees",
    "public_brand_name": "Public brand", "annual_account_metric": "Accounts", "annual_account_filing": "Annual account filing",
    "filed_account_years": "Filed account years", "role": "Role", "group_relation": "Group", "registered_workplace": "Registered workplace",
    "website_address": "Address on website", "registry_website": "Registry-declared website", "official_website": "Official website (verified)", "website_description": "Website description",
    "social_profile": "Social profile", "knowledge_base_entry": "Wikidata", "job_posting": "Job posting", "careers_page": "Careers page",
    "news_item": "News / press", "registry_event": "Registry event",
    "food_safety_inspection": "Food-safety inspection (Mattilsynet)", "public_approval": "Public approval",
}
METRIC_LABELS = {"revenue": "Revenue", "operating_expenses": "Operating expenses", "payroll_expenses": "Payroll", "operating_result": "Operating result",
                 "net_financial_items": "Net financial items", "profit_before_tax": "Profit before tax", "annual_result": "Annual result",
                 "total_assets": "Total assets", "cash_and_bank": "Cash and bank", "equity": "Equity", "total_debt": "Total debt"}


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _value_text(claim: dict[str, Any]) -> tuple[str, str]:
    """Return (label, value text)."""
    field = claim["field"]
    value = claim.get("value")
    label = FIELD_LABELS.get(field, field)
    if value is None:
        return label, claim.get("note") or ""
    if field == "annual_account_metric":
        _, period, metric = (claim["key"].split(":") + ["", ""])[:3]
        scope = claim.get("scope", "company")
        return f"{METRIC_LABELS.get(metric, metric)} ({'group' if scope == 'group' else 'company'})", f"{claim.get('unit') or 'NOK'} {_money(value)}"
    if isinstance(value, dict):
        if field == "role":
            return value.get("role") or label, value.get("name") or ""
        if field == "legal_form":
            if "amount" in value:
                return "Share capital", f"{value.get('currency') or ''} {_money(value.get('amount'))}"
            return label, f"{value.get('description') or ''} ({value.get('code')})"
        if field == "business_address":
            return f"{label} ({claim['key']})", value.get("formatted") or ""
        if field == "industry":
            division = division_label(value.get("code"))
            return label, f"{value.get('code')} {value.get('description') or ''}" + (f" · {division}" if division else "")
        if field == "registry_status":
            return label, value.get("status") or ""
        if field == "registered_workplace":
            address = (value.get("address") or {}).get("formatted") or ""
            extra = f" · {value.get('registered_employees')} employees" if value.get("registered_employees") else ""
            return label, f"{value.get('name')} ({value.get('organisation_number')}) · {address}{extra}"
        if field == "group_relation":
            return f"Group: {value.get('relation')}", f"{value.get('name')} ({value.get('organisation_number')})"
        if field == "job_posting":
            bits = [value.get("title") or "", value.get("location") or "", f"expires {value['expires']}" if value.get("expires") else ""]
            return label, " · ".join(bit for bit in bits if bit)
        if field == "news_item":
            return label, f"{value.get('date')} · {value.get('title')}"
        if field in {"social_profile"}:
            return f"{label}: {value.get('platform')}", value.get("url") or ""
        if field == "knowledge_base_entry":
            return label, f"{value.get('id')} · {value.get('label') or ''} {('— ' + value['description']) if value.get('description') else ''}"
        if field == "annual_account_filing":
            return f"Filing ({value.get('scope')})", f"Year {value.get('year')}" + (" · audit opted out" if value.get("audit_opted_out") else "")
        if field == "filed_account_years":
            return label, ", ".join(value.get("years") or [])
        if field == "food_safety_inspection":
            return f"{label}", f"{value.get('establishment')} · {value.get('latest_inspection_date')} · {value.get('result')} ({value.get('inspections_on_record')} inspections)"
        if field == "public_approval":
            if "approved" in value:
                areas = ", ".join(f"{item.get('subject_area')} (class {item.get('grade')})" for item in (value.get("approval_areas") or [])[:4])
                return value.get("register") or label, f"{'Approved' if value.get('approved') else 'Not approved'} until {value.get('valid_until')} · {areas}"
            return value.get("register") or label, str(value.get("status") or "")
        if field == "registry_event":
            return label, f"{value.get('date')} · {value.get('event')}"
        if field == "careers_page":
            return label, value.get("url") or ""
        if field == "website_address":
            return label, ", ".join(str(v) for v in value.values())
        if field == "legal_name" and "former_name" in value:
            return "Former name", f"{value.get('former_name')} (until {str(value.get('to') or '')[:10]})"
        return label, json.dumps(value, ensure_ascii=False)[:300]
    return label, str(value)


def _link(claim: dict[str, Any]) -> str | None:
    value = claim.get("value")
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, dict):
        for key in ("url", "wikipedia"):
            if isinstance(value.get(key), str) and value[key].startswith("http"):
                return value[key]
    return None


STATE_KEYS = ("available", "ambiguous", "blocked", "failed", "not_available", "not_applicable")


def _short_money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign, size = ("-" if number < 0 else ""), abs(number)
    if size >= 1e9:
        return f"{sign}{size / 1e9:.1f} bn"
    if size >= 1e6:
        return f"{sign}{size / 1e6:.1f} m"
    if size >= 1e3:
        return f"{sign}{size / 1e3:.0f} k"
    return f"{sign}{size:.0f}"


def _accounts_table(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact year x (revenue, result, equity) table for the latest scope (company, else group)."""
    periods: dict[str, dict[str, dict[str, Any]]] = {"company": {}, "group": {}}
    for claim in claims:
        if claim["field"] != "annual_account_metric" or claim["availability"] != "available":
            continue
        scope, end, metric = (claim["key"].split(":") + ["", "", ""])[:3]
        if scope not in periods:
            continue
        entry = periods[scope].setdefault(end, {"period": claim.get("reporting_period") or {}})
        entry[metric] = claim["value"]
    scope = "company" if periods["company"] else "group"
    rows = []
    for end in sorted(periods[scope], reverse=True)[:4]:
        entry = periods[scope][end]
        period = entry.get("period") or {}
        start = str(period.get("from") or "")
        span = f"{start[8:10]}.{start[5:7]}–{end[8:10]}.{end[5:7]}" if len(start) >= 10 and len(end) >= 10 else end
        rows.append([end[:4], span, _short_money(entry.get("revenue")) if "revenue" in entry else "—",
                     _short_money(entry.get("annual_result")) if "annual_result" in entry else "—",
                     _short_money(entry.get("equity")) if "equity" in entry else "—"])
    return {"scope": scope, "rows": rows} if rows else {"scope": scope, "rows": []}


def _first(by: dict[str, list[dict[str, Any]]], field: str, key: str | None = None) -> dict[str, Any] | None:
    for claim in by.get(field, []):
        if key is None or claim["key"] == key:
            return claim
    return None


ROLE_ORDER = {"DAGL": 0, "LEDE": 1, "NEST": 2, "MEDL": 3, "VARA": 4, "OBS": 5, "REVI": 6, "REGN": 7}


def _previews(envelope: dict[str, Any], by: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    org = envelope["organisation_number"]
    previews: dict[str, dict[str, Any]] = {}

    rows: list[list[str]] = []
    name = _first(by, "legal_name", "current")
    if name:
        rows.append(["Name", str(name["value"]), ""])
    rows.append(["Org no", org, ""])
    form = _first(by, "legal_form", "current")
    if form:
        value = form["value"] or {}
        rows.append(["Legal form", str(value.get("description") or value.get("code") or ""), ""])
    address = _first(by, "business_address", "business") or _first(by, "business_address", "postal")
    if address:
        rows.append(["Address", str((address["value"] or {}).get("formatted") or ""), ""])
    industry = _first(by, "industry", "nace1")
    if industry:
        value = industry["value"] or {}
        rows.append(["Industry", f"{value.get('code')} {value.get('description') or ''}".strip(), ""])
    founded = _first(by, "founded_date")
    if founded:
        rows.append(["Founded", str(founded["value"]), ""])
    status = _first(by, "registry_status", "current")
    if status and (status["value"] or {}).get("status") not in (None, "active"):
        rows.append(["Status", str(status["value"]["status"]).upper(), ""])
    previews["legal_identity"] = {"rows": rows[:6]}

    groups: dict[tuple[Any, Any], list[str]] = {}
    for claim in by.get("role", []):
        value = claim["value"] or {}
        groups.setdefault((value.get("role_code"), value.get("role")), []).append(str(value.get("name")))
    rows = []
    for (code, label), names in sorted(groups.items(), key=lambda item: (ROLE_ORDER.get(item[0][0], 9), str(item[0][1]))):
        rows.append([str(label or code), names[0] if len(names) == 1 else f"{len(names)} people", ""])
    for claim in by.get("group_relation", []):
        value = claim["value"] or {}
        if value.get("relation") in {"parent", "top parent"}:
            rows.append(["Parent", f"{value.get('name')} ({value.get('organisation_number')})", ""])
            break
    previews["leadership"] = {"rows": rows[:6]}

    workplaces = by.get("registered_workplace", [])
    rows = []
    if workplaces:
        value = workplaces[0]["value"] or {}
        rows.append(["Workplace", f"{value.get('name')} ({value.get('organisation_number')})", ""])
        if (value.get("address") or {}).get("formatted"):
            rows.append(["Address", value["address"]["formatted"], ""])
        if value.get("registered_employees") is not None:
            rows.append(["Employees", str(value["registered_employees"]), ""])
        if len(workplaces) > 1:
            rows.append(["More", f"+{len(workplaces) - 1} registered workplace(s)", ""])
    previews["workplaces"] = {"rows": rows}

    rows = []
    site = _first(by, "official_website")
    registry_site = _first(by, "registry_website")
    if site:
        rows.append(["Website", str(site["value"]), str(site["value"])])
    elif registry_site:
        rows.append(["Registry says", str(registry_site["value"]), ""])
    for claim in by.get("social_profile", [])[:4]:
        value = claim["value"] or {}
        rows.append([str(value.get("platform", "")).capitalize(), str(value.get("url", "")).replace("https://", ""), str(value.get("url", ""))])
    wiki = _first(by, "knowledge_base_entry")
    if wiki:
        value = wiki["value"] or {}
        rows.append(["Wikidata", str(value.get("id")), str(value.get("url") or "")])
    previews["web_presence"] = {"rows": rows[:6]}

    rows = []
    for claim in by.get("job_posting", [])[:4]:
        value = claim["value"] or {}
        rows.append(["Job", " · ".join(item for item in (str(value.get("title") or ""), str(value.get("location") or "")) if item), str(value.get("url") or "")])
    careers = _first(by, "careers_page")
    if careers:
        rows.append(["Careers page", str((careers["value"] or {}).get("url") or ""), str((careers["value"] or {}).get("url") or "")])
    previews["hiring"] = {"rows": rows[:5]}

    news = sorted(by.get("news_item", []), key=lambda claim: (claim["value"] or {}).get("date") or "", reverse=True)[:3]
    events = sorted(by.get("registry_event", []), key=lambda claim: (claim["value"] or {}).get("date") or "", reverse=True)
    rows = [[str((c["value"] or {}).get("date")), str((c["value"] or {}).get("title")), str((c["value"] or {}).get("url") or "")] for c in news]
    rows += [[str((c["value"] or {}).get("date")), str((c["value"] or {}).get("event")), ""] for c in events[: max(0, 4 - len(rows))]]
    previews["activity"] = {"rows": rows}

    rows = []
    for claim in by.get("food_safety_inspection", [])[:3]:
        value = claim["value"] or {}
        rows.append(["Food safety", f"{value.get('establishment')}: {value.get('result')} ({value.get('latest_inspection_date')})", ""])
    for claim in by.get("public_approval", [])[:3]:
        value = claim["value"] or {}
        detail = (f"{'Approved' if value.get('approved') else 'Not approved'} until {value.get('valid_until')}" if "approved" in value else str(value.get("status") or ""))
        rows.append([str(value.get("register") or "Approval"), detail, str(value.get("certificate") or "")])
    previews["assessments"] = {"rows": rows}

    # Reason text for sections without facts: the recorded note of a placeholder claim in the section's own state.
    for section, preview in previews.items():
        state = (envelope.get("sections") or {}).get(section, {}).get("availability")
        notes = [c.get("note") for c in envelope.get("claims", []) if c["section"] == section and c["key"] == "*" and c.get("note") and c["availability"] == state]
        notes = notes or [c.get("note") for c in envelope.get("claims", []) if c["section"] == section and c["key"] == "*" and c.get("note")]
        preview["note"] = (notes[0] if notes else "")[:420]
    return previews


def view_model(envelope: dict[str, Any]) -> dict[str, Any]:
    evidence = {item["id"]: item for item in envelope.get("evidence", [])}
    ev_index: dict[str, int] = {}
    ev_rows: list[list[Any]] = []
    claims = []
    by: dict[str, list[dict[str, Any]]] = {}
    for claim in envelope.get("claims", []):
        if claim["availability"] == "available":
            by.setdefault(claim["field"], []).append(claim)
        refs = []
        for eid in claim.get("evidence_ids") or []:
            item = evidence.get(eid)
            if not item:
                continue
            if eid not in ev_index:
                ev_index[eid] = len(ev_rows)
                ev_rows.append([item.get("source_url"), item.get("retrieved_at"), (item.get("content_sha256") or "")[:12], item.get("source_class"),
                                (item.get("claim_span") or "")[:240], bool(item.get("superseded"))])
            refs.append(ev_index[eid])
        label, text = _value_text(claim)
        period = claim.get("reporting_period") or {}
        date = f"{period.get('from')} – {period.get('to')}" if period else (claim.get("effective_at") or "")
        verified = str(claim.get("last_verified_at") or "")[:10]
        if not verified and refs:
            verified = max(str(ev_rows[i][1] or "")[:10] for i in refs)
        claims.append([claim["section"], claim["field"], label, text, claim["availability"], str(date or "")[:25], refs, _link(claim),
                       bool(claim.get("stale")), claim.get("confidence"), verified])
    available = [claim for claim in envelope.get("claims", []) if claim["availability"] == "available"]
    evidenced = sum(1 for claim in available if any(eid in evidence for eid in claim.get("evidence_ids") or []))
    company = envelope.get("company") or {}
    summary = envelope.get("summary") or {}
    readable = {item.get("change_id"): item.get("text") for item in summary.get("changes") or []}
    purpose = _first(by, "business_purpose")
    return {
        "o": envelope["organisation_number"], "n": company.get("name") or envelope["organisation_number"], "f": company.get("legal_form") or "",
        "fd": company.get("legal_form_description") or company.get("legal_form") or "",
        "m": (company.get("municipality") or "").title(), "w": company.get("website") or "", "t": envelope["run"].get("terminal_status"),
        "rd": str(envelope["run"].get("completed_at") or "")[:10], "pr": envelope["run"].get("previous_run_id") or "",
        "s": {name: section.get("availability") for name, section in (envelope.get("sections") or {}).items()},
        "wd": ((summary.get("synthesis") or {}).get("what_it_does") or {}).get("text") or "",
        "wp": str(purpose["value"])[:320] if purpose else "",
        "sum": " ".join(item["text"] for item in summary.get("sentences") or [] if not item.get("generated")) or summary.get("text") or "",
        "sm": summary.get("method") or "", "chg": summary.get("changes_text") or "", "unk": summary.get("unknowns_text") or "",
        "cl": claims, "ev": ev_rows, "ec": [evidenced, len(available)], "sp": _previews(envelope, by), "ac": _accounts_table(envelope.get("claims", [])),
        "ch": [[item["type"], readable.get(item["id"], item["key"]), json.dumps(item.get("old_value"), ensure_ascii=False)[:160], json.dumps(item.get("new_value"), ensure_ascii=False)[:160], item.get("material")]
               for item in envelope.get("changes", [])],
        "rq": (envelope.get("operations") or {}).get("requests"),
    }


def batch_stats(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    """Global evidence-coverage and freshness figures, computed from the envelopes themselves."""
    states = {key: 0 for key in STATE_KEYS}
    available = evidenced = stale = 0
    newest = oldest = ""
    for envelope in envelopes:
        evidence = {item["id"]: item for item in envelope.get("evidence", [])}
        for claim in envelope.get("claims", []):
            states[claim["availability"]] = states.get(claim["availability"], 0) + 1
            if claim["availability"] != "available":
                continue
            available += 1
            ids = [eid for eid in claim.get("evidence_ids") or [] if eid in evidence]
            evidenced += bool(ids)
            stale += bool(claim.get("stale"))
            day = str(claim.get("last_verified_at") or "")[:10] or max((str(evidence[eid].get("retrieved_at") or "")[:10] for eid in ids), default="")
            if day:
                newest = max(newest, day)
                oldest = day if not oldest else min(oldest, day)
    return {"companies": len(envelopes), "available": available, "evidenced": evidenced, "states": states, "stale": stale, "newest": newest, "oldest": oldest}


def build_viewer(envelopes: list[dict[str, Any]], report: dict[str, Any], path: str) -> None:
    template = (Path(__file__).with_name("viewer_template.html")).read_text(encoding="utf-8")
    data = [view_model(envelope) for envelope in envelopes]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    summary = {key: report.get(key) for key in ("run_id", "agent_version", "emitted_envelopes", "completed_at", "elapsed_seconds", "requests", "third_party_cost_usd")}
    summary["stats"] = batch_stats(envelopes)
    report_payload = json.dumps(summary, ensure_ascii=False).replace("</", "<\\/")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace("__DATA__", payload).replace("__REPORT__", report_payload), encoding="utf-8")


__all__ = ["build_viewer", "view_model", "batch_stats", "html"]
