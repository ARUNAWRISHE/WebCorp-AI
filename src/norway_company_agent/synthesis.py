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
            what.append(f"its main registered industry is {str(industry['value'].get('description')).lower()} (NACE {industry['value'].get('code')})")
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
    material = [item for item in changes if item.get("material")]
    change_text = None
    if material:
        kinds: dict[str, int] = {}
        for item in material:
            kinds[item["type"]] = kinds.get(item["type"], 0) + 1
        change_text = "Since the previous run: " + ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in sorted(kinds.items())) + "."
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


def llm_summary(envelope: dict[str, Any], template: dict[str, Any], *, model: str, timeout: float = 60.0) -> dict[str, Any] | None:
    cited_ids = {cid for sentence in template["sentences"] for cid in sentence["claim_ids"]}
    claims = {item["id"]: item for item in envelope["claims"] if item["id"] in cited_ids}
    if not claims:
        return None
    facts = [{"id": cid, "field": item["field"], "value": item["value"], "period": item.get("reporting_period")} for cid, item in claims.items()]
    prompt = (
        "You write a short, neutral English company profile for a business analyst.\n"
        "Use ONLY the facts below. Do not add any fact, number, name, date or opinion that is not in them.\n"
        "Write 3-6 sentences. Every sentence must cite the ids of the facts it uses.\n"
        "Amounts are NOK; you may round to millions with one decimal.\n"
        'Return JSON: {"sentences": [{"text": "...", "claim_ids": ["cl-..."]}]}\n\n'
        f"FACTS:\n{json.dumps(facts, ensure_ascii=False)[:9000]}"
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0, "seed": 7, "num_predict": 500}}).encode()
    try:
        request = urllib.request.Request(OLLAMA_URL + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            output = json.loads(json.loads(response.read())["response"])
    except Exception:
        return None
    accepted = []
    for sentence in output.get("sentences") or []:
        text = str(sentence.get("text") or "").strip()
        ids = [cid for cid in sentence.get("claim_ids") or [] if cid in claims]
        if not text or not ids:
            continue
        source_text = " ".join(_claim_text(claims[cid]) for cid in ids)
        source_numbers = _numbers(source_text)
        allowed = set(source_numbers)
        for number in source_numbers:  # allow millions/billions rounding of cited amounts
            try:
                value = abs(float(number))
                allowed.add(f"{value / 1_000_000:.1f}")
                allowed.add(f"{value / 1_000_000_000:.1f}")
                allowed.add(f"{value / 1_000:.0f}")
            except ValueError:
                continue
        stated = {item.lstrip("-") for item in _numbers(text)}
        if any(item not in {a.lstrip("-") for a in allowed} for item in stated):
            continue
        accepted.append({"text": text, "claim_ids": ids})
    if len(accepted) < 2:
        return None
    return {**template, "method": f"local_llm_validated:{model}", "sentences": accepted, "text": " ".join(item["text"] for item in accepted),
            "template_text": template["text"]}
