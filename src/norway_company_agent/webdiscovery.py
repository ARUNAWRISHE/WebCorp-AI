"""Official-website resolution: candidate ladder + crawl + exact-entity verification.

Candidates are tried in order of prior strength. Search engines are not used (no key is available);
every candidate still has to pass `verify.assess` before anything from the site is published.
"""
from __future__ import annotations

import concurrent.futures
import re
import socket
from typing import Any

from .identity import _tokens
from .profile import Profile
from .sitecrawl import SiteCapture, crawl_site, registered_domain
from .verify import assess, fold
from .website import normalize_homepage

GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.no", "live.com", "msn.com",
    "yahoo.com", "yahoo.no", "ymail.com", "icloud.com", "me.com", "mac.com", "online.no", "getmail.no", "start.no", "frisurf.no",
    "broadpark.no", "altibox.no", "lyse.net", "c2i.net", "chello.no", "tele2.no", "telenor.no", "epost.no", "haugnett.no",
    "enivest.net", "loqal.no", "mail.com", "protonmail.com", "proton.me", "aol.com", "gmx.com", "gmx.net", "nextgentel.com",
    "vikenfiber.no", "tdcadsl.no", "sensewave.com", "ebnett.no", "bluezone.no", "dlnett.no", "hotmail.co.uk", "yahoo.co.uk",
    "mail.no", "post.no", "neasnett.no", "tussa.com", "nordnett.no", "vestnett.no", "kvinnherad.net", "online.com",
}
GENERIC_NAME_WORDS = {
    "holding", "holdings", "eiendom", "eiendommer", "invest", "investering", "gruppen", "group", "norge", "norway", "nordic",
    "consult", "consulting", "service", "services", "drift", "utvikling", "handel", "management", "capital", "partners",
    "selskap", "selskapet", "company", "co", "og", "and", "i", "nye", "ny",
}


def _resolves(host: str, timeout: float = 4.0) -> bool:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM)
        try:
            return bool(future.result(timeout=timeout))
        except Exception:
            return False


def guessed_domains(name: str, historic: list[str] | None = None) -> list[str]:
    hosts: list[str] = []
    raw_names = [name] + list(historic or [])[:1]
    for raw in raw_names:
        folded_variants = {
            " ".join(_tokens(raw)),
            " ".join(_tokens(str(raw).replace("ø", "oe").replace("Ø", "OE").replace("å", "aa").replace("Å", "AA"))),
        }
        for folded in folded_variants:
            tokens = [token for token in folded.split() if re.fullmatch(r"[a-z0-9]+", token)]
            if not tokens:
                continue
            distinctive = [token for token in tokens if token not in GENERIC_NAME_WORDS]
            if not distinctive or (len(distinctive) == 1 and len(distinctive[0]) < 4):
                continue
            base_sets = [tokens[:3]]
            if distinctive != tokens:
                base_sets.append(distinctive[:3])
            for base in base_sets:
                joined = "".join(base)
                if len(joined) < 4 or len(joined) > 40:
                    continue
                hosts.append(f"{joined}.no")
                if len(base) > 1:
                    hosts.append(f"{'-'.join(base)}.no")
                hosts.append(f"{joined}.com")
    return list(dict.fromkeys(hosts))[:8]


def candidate_ladder(profile: Profile, wikidata: dict[str, Any] | None) -> list[dict[str, Any]]:
    facts = profile.facts
    candidates: list[dict[str, Any]] = []

    def add(url: str | None, source: str, evidence_id: str | None = None) -> None:
        normalized = normalize_homepage(url)
        if not normalized:
            return
        domain = registered_domain(normalized)
        if not domain or any(item["domain"] == domain for item in candidates):
            return
        candidates.append({"url": normalized, "source": source, "domain": domain, "evidence_id": evidence_id})

    add(facts.get("registry_website"), "registry", facts.get("registry_website_evidence"))
    if wikidata and wikidata.get("website"):
        add(wikidata["website"], "wikidata", wikidata.get("evidence_id"))
    for unit in facts.get("subunits") or []:
        if unit.get("website"):
            add(unit["website"], "subunit_registry")
    email = str(facts.get("email") or "")
    if "@" in email:
        domain = email.split("@", 1)[1].strip().casefold()
        if domain and domain not in GENERIC_EMAIL_DOMAINS and "." in domain:
            add(f"https://{domain}/", "email_domain")
    if facts.get("name") and facts.get("legal_form") != "ENK":
        for host in guessed_domains(facts["name"], facts.get("historic_names")):
            if any(item["domain"] == host for item in candidates):
                continue
            candidates.append({"url": f"https://{host}/", "source": "guessed_domain", "domain": host, "evidence_id": None})
    return candidates


def resolve_website(profile: Profile, wikidata: dict[str, Any] | None, *, max_crawls: int = 4) -> tuple[SiteCapture | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Return (verified capture, assessment, attempts). The capture is None unless status == exact."""
    attempts: list[dict[str, Any]] = []
    crawls = 0
    best_ambiguous: tuple[SiteCapture, dict[str, Any], dict[str, Any]] | None = None
    guessed_checked = 0
    for candidate in candidate_ladder(profile, wikidata):
        if crawls >= max_crawls:
            break
        left = profile.budget_left()
        if left is not None and left < 20:
            attempts.append({**candidate, "outcome": "failed", "note": "run budget exhausted"})
            break
        if candidate["source"] == "guessed_domain":
            if guessed_checked >= 6:
                continue
            guessed_checked += 1
            if not _resolves(candidate["domain"]):
                attempts.append({**candidate, "outcome": "not_available", "note": "domain does not resolve"})
                continue
        crawls += 1
        capture = crawl_site(profile, candidate["url"])
        if capture.outcome != "available":
            attempts.append({**candidate, "outcome": capture.outcome, "note": capture.note})
            continue
        assessment = assess(capture, profile.facts, profile.organisation_number, candidate["source"])
        attempts.append({**candidate, "outcome": assessment["status"], "score": assessment["score"], "note": "; ".join(assessment["reasons"])[:300],
                         "final_url": capture.homepage.final_url if capture.homepage else None})
        if assessment["status"] == "exact":
            return capture, {**assessment, "candidate": candidate}, attempts
        if assessment["status"] == "ambiguous" and best_ambiguous is None:
            best_ambiguous = (capture, assessment, candidate)
    if best_ambiguous:
        return None, {**best_ambiguous[1], "candidate": best_ambiguous[2]}, attempts
    return None, None, attempts


def social_handle_matches(url: str, name_tokens: list[str], brand_tokens: list[str], domain_label: str) -> bool:
    path = fold(re.sub(r"^https?://[^/]+/", "", url))
    compact = re.sub(r"[^a-z0-9]", "", path.replace("company/", "").replace("channel/", "").replace("user/", "").replace("c/", ""))
    if not compact:
        return False
    for tokens in (name_tokens, brand_tokens):
        joined = "".join(tokens)
        if joined and (joined in compact or compact in joined and len(compact) >= 4):
            return True
        distinctive = [token for token in tokens if token not in GENERIC_NAME_WORDS and len(token) >= 4]
        if distinctive and all(token in compact for token in distinctive):
            return True
    label = re.sub(r"[^a-z0-9]", "", domain_label)
    return bool(label) and len(label) >= 4 and (label in compact or compact in label)
