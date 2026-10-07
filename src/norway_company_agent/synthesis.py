"""Decision-useful profile summary built only from verified claims.

Default: a deterministic template in which every sentence cites claim ids. Optional: a local LLM via
Ollama (GPU) rewrites the same cited facts; every LLM sentence is validated (cited ids must exist, and
every number it states must appear in the cited claims) and the template is used on any failure.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from .nace import division_label

OLLAMA_URL = "http://127.0.0.1:11434"


def _fmt_nok(amount: Any) -> str:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}NOK {value / 1_000_000_000:.1f} billion"
    if value >= 1_000_000:
        return f"{sign}NOK {value / 1_000_000:.1f} million"
    if value >= 1_000:
        return f"{sign}NOK {value / 1_000:.0f} thousand"
    return f"{sign}NOK {value:.0f}"


LEGAL_FORMS_EN = {
    "AS": "private limited company (AS)", "ASA": "public limited company (ASA)", "ENK": "sole proprietorship (ENK)",
    "ANS": "general partnership (ANS)", "DA": "partnership with shared liability (DA)", "SA": "cooperative (SA)", "STI": "foundation (STI)",
    "NUF": "Norwegian branch of a foreign company (NUF)", "BRL": "housing cooperative (BRL)", "ESEK": "condominium owners' association (ESEK)",
    "FLI": "association (FLI)", "KS": "limited partnership (KS)", "SF": "state enterprise (SF)", "KF": "municipal enterprise (KF)",
    "IKS": "inter-municipal company (IKS)", "BBL": "housing association (BBL)", "SPA": "savings bank (SPA)", "GFS": "mutual insurance company (GFS)",
}


def _by_field(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        if claim["availability"] == "available":
            output.setdefault(claim["field"], []).append(claim)
    return output


def _val(value: Any, *keys: str) -> str:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return str(value[key])
        return ""
    return "" if value is None else str(value)


def _address_text(value: Any) -> str:
    address = value.get("address") if isinstance(value, dict) else None
    return _val(address, "formatted")


def describe_change(change: dict[str, Any]) -> dict[str, Any]:
    """One readable, evidence-linked sentence per detected change."""
    kind, old, new = change["type"], change.get("old_value"), change.get("new_value")
    key_parts = str(change.get("key") or "").split(":")
    metric = key_parts[-1].replace("_", " ").capitalize()
    period = key_parts[1] if len(key_parts) > 2 else ""
    location = _val(new, "location")
    years = (new or {}).get("years", []) if isinstance(new, dict) else []
    texts = {
        "new_role": lambda: f"New {_val(new, 'role')}: {_val(new, 'name')}.",
        "removed_role": lambda: f"{_val(old, 'role')} {_val(old, 'name')} is no longer registered.",
        "role_changed": lambda: f"Role record changed for {_val(new, 'name') or _val(old, 'name')}.",
        "new_location": lambda: f"New registered workplace: {_val(new, 'name')} ({_address_text(new)}).",
        "closed_location": lambda: f"Registered workplace no longer listed: {_val(old, 'name')}.",
        "new_job": lambda: f"New job posting: {_val(new, 'title')}" + (f" ({location})" if location else "") + ".",
        "closed_job": lambda: f"Job posting closed: {_val(old, 'title')}.",
        "new_activity": lambda: f"New dated item ({_val(new, 'date')}): {_val(new, 'title')}.",
        "new_filing": lambda: f"New annual accounts filed for {_val(new, 'year') or (years[0] if years else 'a new period')}.",
        "financial_value_restated": lambda: f"{metric} for the period ending {period} changed from {old} to {new}.",
        "name_changed": lambda: f"Registered name changed from {_val(old, 'former_name') or old} to {_val(new, 'former_name') or new}.",
        "address_changed": lambda: f"Registered address changed to {_val(new, 'formatted')}.",
        "status_changed": lambda: f"Registry status changed from {_val(old, 'status')} to {_val(new, 'status')}.",
        "employee_count_changed": lambda: f"Registered employees changed from {old} to {new}.",
        "website_found": lambda: f"Verified official website found: {new}.",
        "website_lost": lambda: f"Previously verified website {old} could not be verified in this run.",
        "website_changed": lambda: f"Official website changed from {old} to {new}.",
        "new_social_profile": lambda: f"New company-linked {_val(new, 'platform')} profile: {_val(new, 'url')}.",
        "removed_social_profile": lambda: f"{_val(old, 'platform').capitalize()} profile no longer linked: {_val(old, 'url')}.",
        "new_registry_event": lambda: f"Registry event on {_val(new, 'date')}: {_val(new, 'event')}.",
        "inspection_result_changed": lambda: f"New food-safety inspection result for {_val(new, 'establishment')}: {_val(new, 'result')} ({_val(new, 'latest_inspection_date')}).",
        "new_inspection_site": lambda: f"Food-safety inspection on record for {_val(new, 'establishment')}: {_val(new, 'result')}.",
        "new_approval": lambda: f"Listed in {_val(new, 'register')}.",
        "approval_changed": lambda: f"Approval record changed in {_val(new, 'register') or _val(old, 'register')}.",
        "approval_removed": lambda: f"No longer listed in {_val(old, 'register')}.",
        "description_changed": lambda: "The website description changed.",
    }
    fallback = f"{kind.replace('_', ' ').capitalize()} ({change.get('field')})."
    try:
        text = texts[kind]() if kind in texts else fallback
    except Exception:
        text = fallback
    return {"text": " ".join(text.split()), "change_id": change["id"], "type": kind, "material": bool(change.get("material")),
            "evidence_ids": list(dict.fromkeys((change.get("new_evidence_ids") or []) + (change.get("old_evidence_ids") or [])))}


def template_summary(envelope: dict[str, Any]) -> dict[str, Any]:
    claims = envelope["claims"]
    fields = _by_field(claims)
    sentences: list[dict[str, Any]] = []

    def say(text: str, cited: list[dict[str, Any]]) -> None:
        ids = [item["id"] for item in cited if item]
        if text and ids:
            sentences.append({"text": text, "claim_ids": ids})

    def first(field: str, key: str | None = None) -> dict[str, Any] | None:
        for item in fields.get(field, []):
            if key is None or item["key"] == key:
                return item
        return None

    name = first("legal_name", "current")
    form = first("legal_form", "current")
    status = first("registry_status", "current")
    address = first("business_address", "business") or first("business_address", "postal")
    founded = first("founded_date")
    if name:
        parts = [f"{name['value']}"]
        cited = [name]
        if form:
            code = (form["value"] or {}).get("code")
            parts.append(f"is a {LEGAL_FORMS_EN.get(code) or str((form['value'] or {}).get('description') or code).lower() + f' ({code})'}")
            cited.append(form)
        else:
            parts.append("is a registered Norwegian entity")
        if address and (address["value"] or {}).get("municipality"):
            parts.append(f"registered in {str(address['value']['municipality']).title()}")
            cited.append(address)
        if founded:
            parts.append(f"founded {founded['value']}")
            cited.append(founded)
        text = " ".join(parts[:2]) + (", " + ", ".join(parts[2:]) if len(parts) > 2 else "") + "."
        say(text, cited)
    if status and (status["value"] or {}).get("status") != "active":
        say(f"The registry marks the entity as {status['value']['status']}.", [status])
    purpose = first("business_purpose")
    industry = first("industry", "nace1")
    if purpose or industry:
        what = []
        cited = []
        if industry:
            division = division_label(industry["value"].get("code"))
            english = f"; division: {division}" if division else ""
            what.append(f"its main registered industry is {str(industry['value'].get('description')).lower()} (NACE {industry['value'].get('code')}{english})")
            cited.append(industry)
        if purpose:
            what.append(f"its registered activity reads: \"{purpose['value'][:220]}\"")
            cited.append(purpose)
        say("According to Enhetsregisteret, " + "; ".join(what) + ".", cited)
    description = first("website_description")
    website = first("official_website")
    brand = first("public_brand_name")
    if website:
        text = f"Its verified official website is {website['value']}"
        cited = [website]
        if brand:
            text += f", where it presents itself as {brand['value']}"
            cited.append(brand)
        say(text + ".", cited)
    if description:
        say(f"The website describes the business as: \"{description['value'][:240]}\" (company-reported).", [description])

    metrics = [item for item in fields.get("annual_account_metric", []) if item.get("scope", "company") == "company"]
    if metrics:
        latest_period = max(item["key"].split(":")[1] for item in metrics)
        current = {item["key"].split(":")[2]: item for item in metrics if item["key"].split(":")[1] == latest_period}
        parts, cited = [], []
        for metric, label in (("revenue", "revenue"), ("operating_result", "operating result"), ("annual_result", "annual result"), ("equity", "equity")):
            if metric in current:
                parts.append(f"{label} {_fmt_nok(current[metric]['value'])}")
                cited.append(current[metric])
        if parts:
            say(f"In its latest normalised company accounts (period ending {latest_period}) it reported " + ", ".join(parts) + ".", cited)
        prior = sorted({item["key"].split(":")[1] for item in metrics if item["key"].split(":")[1] < latest_period})
        if prior and "revenue" in current:
            previous_period = prior[-1]
            before = next((item for item in metrics if item["key"] == f"company:{previous_period}:revenue"), None)
            if before and isinstance(before["value"], (int, float)) and before["value"]:
                delta = (current["revenue"]["value"] - before["value"]) / abs(before["value"]) * 100
                if abs(delta) < 0.5:
                    say(f"Revenue was essentially unchanged from the period ending {previous_period} ({_fmt_nok(before['value'])}).", [current["revenue"], before])
                else:
                    direction = "up" if delta > 0 else "down"
                    say(f"Revenue was {direction} {abs(delta):.0f}% from {_fmt_nok(before['value'])} in the period ending {previous_period}.", [current["revenue"], before])
    employees = first("registered_employees")
    if employees:
        say(f"The registry lists {employees['value']} employees.", [employees])
    roles = fields.get("role", [])
    leaders = [item for item in roles if (item["value"] or {}).get("role_code") in {"DAGL", "LEDE"}]
    if leaders:
        say("Registered leadership: " + "; ".join(f"{item['value'].get('role')}: {item['value'].get('name')}" for item in leaders[:3]) + ".", leaders[:3])
    workplaces = fields.get("registered_workplace", [])
    if workplaces:
        cities = sorted({str(((item["value"] or {}).get("address") or {}).get("city") or "").title() for item in workplaces} - {""})
        say(f"It has {len(workplaces)} registered workplace(s)" + (f" in {', '.join(cities[:5])}" if cities else "") + ".", workplaces[:5])
    parents = [item for item in fields.get("group_relation", []) if (item["value"] or {}).get("relation") in {"parent", "top parent"}]
    if parents:
        say("It belongs to a group with parent " + ", ".join(f"{item['value'].get('name')} ({item['value'].get('organisation_number')})" for item in parents[:2]) + ".", parents[:2])
    jobs = fields.get("job_posting", [])
    if jobs:
        titles = [str((item["value"] or {}).get("title") or "")[:70] for item in jobs[:3]]
        say(f"It appears to be hiring: {len(jobs)} active job posting(s) found, e.g. " + "; ".join(t for t in titles if t) + ".", jobs[:3])
    news = sorted(fields.get("news_item", []), key=lambda item: item.get("effective_at") or "", reverse=True)
    if news:
        latest = news[0]
        say(f"Most recent dated company news: \"{latest['value']['title'][:120]}\" ({latest['value']['date']}).", [latest])
    social = fields.get("social_profile", [])
    if social:
        say("Company-linked profiles: " + ", ".join(sorted({item["value"]["platform"] for item in social})) + ".", social)

    changes = envelope.get("changes") or []
    change_items = [describe_change(item) for item in changes]
    material = [item for item in change_items if item["material"]]
    change_text = None
    if material:
        shown = material[:6]
        change_text = "Since the previous run: " + " ".join(item["text"] for item in shown)
        if len(material) > len(shown):
            change_text += f" ({len(material) - len(shown)} more material change(s) listed in the profile.)"
    elif (envelope.get("run") or {}).get("previous_run_id"):
        change_text = "No material changes were detected since the previous run."

    unknown = []
    labels = {
        "official_website": "an official website", "job_posting": "active job postings", "news_item": "dated public activity",
        "social_profile": "company-linked social profiles", "annual_account_metric": "normalised annual accounts", "role": "registered role holders",
        "registered_workplace": "registered workplaces", "registered_employees": "a registered employee count",
    }
    for claim in claims:
        if claim["key"] == "*" and claim["field"] in labels:
            unknown.append(f"{labels[claim['field']]} ({claim['availability'].replace('_', ' ')})")
    return {
        "method": "deterministic_template_v1",
        "sentences": sentences,
        "text": " ".join(item["text"] for item in sentences),
        "changes_text": change_text,
        "changes": change_items,
        "unknowns": unknown,
        "unknowns_text": ("Not found or not confirmed: " + "; ".join(unknown) + ".") if unknown else None,
    }


# ---- optional local LLM -------------------------------------------------------------------------
def ollama_available(model: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=timeout) as response:
            tags = json.loads(response.read())
        return any(item.get("name", "").split(":")[0] == model.split(":")[0] and (":" not in model or item.get("name") == model) for item in tags.get("models", []))
    except Exception:
        return False


NUMBER = re.compile(r"-?\d[\d\s.,]*\d|\d")


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", item).rstrip(".") for item in NUMBER.findall(text)}


def _claim_text(claim: dict[str, Any]) -> str:
    return json.dumps(claim.get("value"), ensure_ascii=False) + " " + str(claim.get("key")) + " " + json.dumps(claim.get("reporting_period") or {})


def llm_overview(envelope: dict[str, Any], template: dict[str, Any], *, model: str, timeout: float = 45.0) -> dict[str, Any] | None:
    """One or two plain-English sentences on what the company does, paraphrasing cited registry/website text.

    The deterministic template remains the factual summary; the overview is prepended only when it passes
    validation: it must cite provided claim ids, stay short, and contain no number absent from its sources.
    """
    sources = [claim for claim in envelope["claims"] if claim["availability"] == "available" and claim["field"] in
               {"business_purpose", "industry", "website_description", "public_brand_name"}][:6]
    name = next((claim["value"] for claim in envelope["claims"] if claim["field"] == "legal_name" and claim["key"] == "current"), None)
    if not sources or not name:
        return None
    facts = [{"id": claim["id"], "field": claim["field"], "text": claim["value"] if isinstance(claim["value"], str) else claim["value"]} for claim in sources]
    prompt = (
        f"Company: {name}\n"
        "Using ONLY the texts below (some are Norwegian), write one or two short English sentences that explain what this company does.\n"
        "Do not add facts, numbers, places, customers, sizes or opinions that are not in the texts. Do not use marketing language.\n"
        'Return JSON: {"overview": "...", "claim_ids": ["cl-..."]} citing the ids you used.\n\n'
        f"TEXTS:\n{json.dumps(facts, ensure_ascii=False)[:4000]}"
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json", "keep_alive": "30m",
                       "options": {"temperature": 0, "seed": 7, "num_predict": 160}}).encode()
    try:
        request = urllib.request.Request(OLLAMA_URL + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            output = json.loads(json.loads(response.read())["response"])
    except Exception:
        return None
    text = " ".join(str(output.get("overview") or "").split())
    by_id = {claim["id"]: claim for claim in sources}
    ids = [cid for cid in output.get("claim_ids") or [] if cid in by_id] or [claim["id"] for claim in sources if claim["field"] == "business_purpose"]
    if not text or not ids or len(text) > 420 or len(text) < 25:
        return None
    allowed = _numbers(" ".join(_claim_text(by_id[cid]) for cid in ids))
    if any(number not in allowed for number in _numbers(text)):
        return None
    overview = {"text": text, "claim_ids": ids, "method": f"local_llm_paraphrase:{model}", "note": "Machine paraphrase of the cited registry/website text."}
    return {**template, "method": f"{template['method']}+llm_overview:{model}", "overview": overview,
            "sentences": [{"text": text, "claim_ids": ids, "generated": True}] + template["sentences"], "text": text + " " + template["text"]}
