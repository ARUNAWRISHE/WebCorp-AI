"""Exact-entity verification for a captured website.

Publication requires proof that ties the site to this organisation number, not name similarity alone.
The required proof depends on how the candidate was found: a registry- or Wikidata-declared site needs
less corroboration than a domain guessed from the name.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .identity import _tokens
from .sitecrawl import SiteCapture, registered_domain

ORG_PATTERN = re.compile(r"(?<![\d])(\d{3})[\s.  -]?(\d{3})[\s.  -]?(\d{3})(?![\d])")
KEYWORD_ORG_PATTERN = re.compile(
    r"(?i)(?:org(?:anisasjons)?\.?\s*-?\s*(?:nr|nummer|no|number)?\.?|foretaksregisteret|vat(?:\s*no)?|mva)\s*[:.]?\s*(?:no)?\s*"
    r"(\d{3}[\s.  ]?\d{3}[\s.  ]?\d{3})"
)
PARKED_MARKERS = (
    "domain is for sale", "domain for sale", "domenet er til salgs", "dette domenet", "hugedomains", "parked at", "parkeringsside",
    "this domain may be for sale", "buy this domain", "kjøp dette domenet", "her flytter snart en ny gjest", "has been informing visitors",
    "find the best information and most relevant links", "web hosting by", "domeneshop", "coming soon", "kommer snart", "under construction",
    "website is under construction", "siden er under arbeid", "default web site page", "it works!", "welcome to nginx", "index of /",
)
DECLARED_SOURCES = {"registry", "wikidata", "subunit_registry"}
PLACEHOLDER_ORGS = {"123456789", "987654321", "999999999", "000000000", "111111111", "123123123"}


def fold(text: str) -> str:
    text = str(text or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def org_numbers(text: str) -> set[str]:
    return {"".join(match.groups()) for match in ORG_PATTERN.finditer(text or "")}


def keyword_org_numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", match.group(1)) for match in KEYWORD_ORG_PATTERN.finditer(text or "")}


def _context(text: str, needle_digits: str, width: int = 70) -> str | None:
    for match in ORG_PATTERN.finditer(text or ""):
        if "".join(match.groups()) == needle_digits:
            start, end = max(0, match.start() - width), min(len(text), match.end() + width)
            return text[start:end].strip()
    return None


def _contains_sequence(haystack_tokens: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    n = len(needle)
    return any(haystack_tokens[i:i + n] == needle for i in range(len(haystack_tokens) - n + 1))


def _phone_digits(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-8:] if len(digits) >= 8 else ""


def _street_tokens(address: dict[str, Any] | None) -> list[str]:
    street = (address or {}).get("street") or ""
    if not street or re.search(r"postboks|pb\.?\s*\d|boks\s*\d", street, re.I):
        return []
    return [token for token in re.findall(r"[a-z0-9]+", fold(street)) if token]


def assess(capture: SiteCapture, facts: dict[str, Any], organisation_number: str, source: str) -> dict[str, Any]:
    """Return {status: exact|ambiguous|rejected, score, reasons, proof: {...}}."""
    reasons: list[str] = []
    proof: dict[str, Any] = {}
    pages = [page for page in capture.pages if page.kind != "feed"]
    if not pages:
        return {"status": "rejected", "score": 0.0, "reasons": ["no page captured"], "proof": {}}
    homepage = pages[0]
    all_text = " ".join(page.full_text for page in pages)
    folded_all = fold(all_text)
    raw_lower = folded_all[:400_000]

    # 1. Placeholder / parked pages never identify a company.
    if any(marker in raw_lower[:20000] for marker in PARKED_MARKERS) and len(homepage.text) < 600:
        return {"status": "rejected", "score": 0.1, "reasons": ["parked, placeholder or for-sale page"], "proof": {}}

    title_host = re.sub(r"^www\.", "", (homepage.title or "").strip().casefold())
    if title_host and title_host == registered_domain(homepage.final_url) and len(homepage.text) < 400 and len(pages) == 1:
        return {"status": "rejected", "score": 0.1, "reasons": ["placeholder page (title is the bare domain name)"], "proof": {}}

    # 2. Organisation-number proof.
    org_page = next((page for page in pages if organisation_number in org_numbers(page.full_text)), None)
    subunit_orgs = {str(item.get("organisation_number")) for item in facts.get("subunits") or [] if item.get("organisation_number")}
    subunit_page = None if org_page else next((page for page in pages if org_numbers(page.full_text) & subunit_orgs), None)
    keyword_orgs = set()
    for page in pages:
        keyword_orgs |= keyword_org_numbers(page.full_text)
    related = {str(item.get("organisation_number")) for item in facts.get("subunits") or []}
    related |= {str(item) for item in facts.get("group_orgs") or []}
    other_orgs = sorted(keyword_orgs - {organisation_number} - related - PLACEHOLDER_ORGS)
    if org_page:
        proof["organisation_number"] = {"page": org_page.final_url, "span": _context(org_page.full_text, organisation_number)}

    # 3. Name evidence.
    names = [facts.get("name") or ""] + [name for name in facts.get("historic_names") or []]
    name_variants = [tokens for tokens in (_tokens(name) for name in names) if tokens]
    core = name_variants[0] if name_variants else []
    # The hostname is NOT name evidence: for a domain derived from the name it would be circular.
    strong_fields = [homepage.title, homepage.site_name]
    for item in homepage.jsonld:
        for key in ("name", "legalName", "alternateName"):
            if isinstance(item.get(key), str):
                strong_fields.append(item[key])
    identity_fields = strong_fields + [homepage.description, homepage.identity_text]
    for page in pages[1:]:
        identity_fields.append(page.identity_text)
    identity_token_lists = [_tokens(field) for field in identity_fields if field]
    all_tokens = _tokens(all_text[:300_000])
    name_in_identity = any(_contains_sequence(tokens, variant) or (len(variant) > 1 and set(variant) <= set(tokens))
                           for variant in name_variants for tokens in identity_token_lists)
    name_in_text = any(_contains_sequence(all_tokens, variant) for variant in name_variants)
    current_in_identity = bool(core) and any(_contains_sequence(tokens, core) or (len(core) > 1 and set(core) <= set(tokens)) for tokens in identity_token_lists)
    strong_token_lists = [_tokens(field) for field in strong_fields if field]
    host_label = re.sub(r"[^a-z0-9]", "", registered_domain(homepage.final_url).split(".")[0])
    host_match = bool(core) and ("".join(core) == host_label or (len("".join(core)) >= 6 and "".join(core) in host_label))
    current_in_strong = bool(core) and any(_contains_sequence(tokens, core) or (len(core) > 1 and set(core) <= set(tokens)) for tokens in strong_token_lists)
    if source in DECLARED_SOURCES and host_match:
        current_in_strong = True  # an officially declared site named after the company is entity-specific
    name_in_host = bool(core) and "".join(core) == host_label
    # Brønnøysund legal names are unique: the exact current name *with its legal form* ("Flislegger Simonsen AS")
    # stated as the site's title, brand, structured legal name or footer identifies the registered entity.
    full_name = re.findall(r"[a-z0-9]+", fold(facts.get("name") or ""))
    registered_name_fields = strong_fields + [page.identity_text for page in pages] + [homepage.full_text[:400], homepage.full_text[-1500:]]
    registered_name_on_site = len(full_name) >= 2 and any(_contains_sequence(re.findall(r"[a-z0-9]+", fold(field)), full_name) for field in registered_name_fields if field)
    registered_name_strong = len(full_name) >= 2 and any(_contains_sequence(re.findall(r"[a-z0-9]+", fold(field)), full_name) for field in strong_fields if field)
    if registered_name_on_site:
        proof["registered_name"] = facts.get("name")
    partial = len(set(core) & set(all_tokens)) / len(set(core)) if core else 0.0
    if name_in_identity:
        reasons.append("full legal name appears in homepage identity fields")
    elif name_in_text:
        reasons.append("full legal name appears in page text")

    # 4. Corroborators from the official registry record.
    corroborators: list[str] = []
    digits_all = re.sub(r"\D", "", all_text)
    for phone in facts.get("phones") or []:
        phone_digits = _phone_digits(phone)
        if phone_digits and phone_digits in digits_all:
            corroborators.append("registered phone number appears on site")
            proof["phone"] = phone_digits
            break
    email = str(facts.get("email") or "").casefold()
    if email and email in all_text.casefold():
        corroborators.append("registered email address appears on site")
    elif email and email.split("@")[-1] == registered_domain(homepage.final_url):
        corroborators.append("registered email domain equals site domain")
    for address in (facts.get("business_address"), facts.get("postal_address")):
        street = _street_tokens(address)
        postcode = (address or {}).get("postal_code")
        if street and _contains_sequence(re.findall(r"[a-z0-9]+", folded_all), street) and (not postcode or postcode in all_text):
            corroborators.append("registered street address appears on site")
            break
    if not any(item.startswith("registered street") for item in corroborators):
        for address in (facts.get("business_address"), facts.get("postal_address")):
            postcode, city = (address or {}).get("postal_code"), fold((address or {}).get("city") or "")
            if postcode and city and re.search(rf"\b{postcode}\s+{re.escape(city)}\b", folded_all):
                corroborators.append("registered postcode and city appear on site")
                break
    for person in facts.get("role_people") or []:
        first = fold(person.get("first") or "").split()
        last = fold(person.get("last") or "").split()
        if first and last and _contains_sequence(re.findall(r"[a-z0-9]+", folded_all), first[:1] + last[-1:]):
            corroborators.append(f"registered role holder appears on site ({person.get('role_code')})")
            proof["role_holder"] = person.get("name")
            break
    corroborators = list(dict.fromkeys(corroborators))
    strong = [item for item in corroborators if not item.startswith("registered role holder")]
    proof["corroborators"] = corroborators
    reasons.extend(corroborators)

    # 5. Decision table.
    site_specific = bool(org_page) or current_in_strong or registered_name_strong
    proof["site_specific"] = site_specific
    if org_page or subunit_page:
        if subunit_page and not org_page:
            proof["organisation_number"] = {"page": subunit_page.final_url, "span": "registered subunit organisation number appears on the site"}
            reasons.insert(0, "organisation number of a registered subunit appears on the site")
        if len(other_orgs) >= 3 and not (current_in_strong or registered_name_on_site):
            return {"status": "ambiguous", "score": 0.7, "reasons": ["organisation number appears, but the site lists several other organisation numbers (directory or group page)"], "proof": {**proof, "other_organisation_numbers": other_orgs[:10]}}
        proof["site_specific"] = True
        return {"status": "exact", "score": 1.0 if org_page else 0.97, "reasons": ["exact organisation number appears on the site" if org_page else "registered subunit organisation number appears on the site", *reasons], "proof": proof}
    if other_orgs and not name_in_identity:
        return {"status": "rejected", "score": 0.2, "reasons": [f"site states a different organisation number ({other_orgs[0]})"], "proof": {**proof, "other_organisation_numbers": other_orgs[:10]}}
    if source in DECLARED_SOURCES:
        if other_orgs and len(other_orgs) >= 1 and not corroborators:
            return {"status": "ambiguous", "score": 0.6, "reasons": ["declared site states another organisation number and has no registry corroboration", *reasons], "proof": proof}
        if name_in_identity:
            return {"status": "exact", "score": 0.95, "reasons": [f"{source}-declared site; " + reasons[0], *reasons[1:]], "proof": proof}
        if (name_in_text or partial >= 0.5) and corroborators:
            return {"status": "exact", "score": 0.92, "reasons": [f"{source}-declared site with name evidence and registry corroboration", *reasons], "proof": proof}
        if len(corroborators) >= 2 or any(item.startswith("registered email domain equals") for item in corroborators):
            return {"status": "exact", "score": 0.9, "reasons": [f"{source}-declared site confirmed by registry contact data", *reasons], "proof": proof}
        return {"status": "ambiguous", "score": 0.6, "reasons": [f"{source}-declared site without exact identity evidence", *reasons], "proof": proof}
    # Discovered candidates (email domain, guessed domain) need the CURRENT legal name in the site identity
    # AND a contact corroborator (phone, email or street address). Former names and role-holder names are
    # not enough: they often point to a successor or sister company run by the same people.
    # Multi-word names with their legal form are distinctive on their own; one-word names ("Nordlys AS") also
    # need a registry corroborator, and any other stated organisation number blocks this route.
    if registered_name_on_site and not other_orgs and (len(full_name) >= 3 or corroborators):
        return {"status": "exact", "score": 0.92, "reasons": [f"{source} candidate; the unique registered legal name '{facts.get('name')}' is stated as the site's own identity", *reasons], "proof": {**proof, "site_specific": bool(current_in_strong or registered_name_strong or name_in_host)}}
    if current_in_identity and strong:
        return {"status": "exact", "score": 0.93, "reasons": [f"{source} candidate; current legal name in site identity plus registry contact corroboration", *reasons], "proof": proof}
    if current_in_strong and "role_holder" in proof and len(core) >= 2:
        # Legal names are unique per register; the exact current name as the site's own title/brand plus a
        # registered role holder named on the site ties it to this entity.
        return {"status": "exact", "score": 0.9, "reasons": [f"{source} candidate; exact current legal name as site title/brand plus a registered role holder on the site", *reasons], "proof": proof}
    if current_in_identity or name_in_identity or (name_in_host and corroborators):
        return {"status": "ambiguous", "score": 0.6, "reasons": [f"{source} candidate matches the name but lacks independent contact corroboration", *reasons], "proof": proof}
    return {"status": "rejected", "score": 0.2, "reasons": [f"{source} candidate lacks exact-entity evidence", *reasons], "proof": proof}
