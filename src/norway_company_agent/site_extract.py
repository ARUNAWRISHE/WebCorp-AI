"""Claims extracted from a verified company website (company-reported layer)."""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup

from .identity import _tokens
from .profile import Profile
from .sitecrawl import Page, SiteCapture, registered_domain
from .verify import fold
from .webdiscovery import social_handle_matches
from .website import normalize_social_url

ATS_HOSTS = (
    "teamtailor.com", "jobylon.com", "webcruiter.no", "webcruiter.com", "recman.no", "easycruit.com", "hrmanager.no", "jobbnorge.no",
    "varbi.com", "reachmee.com", "smartrecruiters.com", "myworkdayjobs.com", "lever.co", "greenhouse.io", "finn.no", "arbeidsplassen.nav.no",
    "jobsite.no", "talentech.com", "recruitee.com", "personio.de", "personio.com", "hr-manager.net", "simployer.com", "cvpartner.com",
)
GENERIC_TITLES = {"nyheter", "news", "aktuelt", "presse", "press", "blogg", "blog", "artikler", "articles", "hjem", "home", "forside", "les mer", "read more"}
ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "PressRelease", "Report", "AnalysisNewsArticle"}
ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "Store", "Restaurant", "ProfessionalService", "HomeAndConstructionBusiness",
             "AutomotiveBusiness", "FinancialService", "LegalService", "MedicalBusiness", "LodgingBusiness", "FoodEstablishment"}


def _types(item: dict[str, Any]) -> set[str]:
    value = item.get("@type")
    return set(value if isinstance(value, list) else [value])


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for parser in (lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")), parsedate_to_datetime):
        try:
            parsed = parser(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed.year < 1990 or parsed > datetime.now(timezone.utc).replace(microsecond=0).replace(year=datetime.now(timezone.utc).year + 1):
                return None
            return parsed.date().isoformat()
        except Exception:
            continue
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else None


MONTHS = {"jan": 1, "januar": 1, "january": 1, "feb": 2, "februar": 2, "february": 2, "mar": 3, "mars": 3, "march": 3, "apr": 4, "april": 4,
          "mai": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
          "september": 9, "okt": 10, "oktober": 10, "oct": 10, "october": 10, "nov": 11, "november": 11, "des": 12, "desember": 12, "dec": 12, "december": 12}


def _text_date(text: str | None) -> str | None:
    """Parse common Norwegian/English date strings: 12.09.2026, 12. september 2026, September 12, 2026."""
    text = (text or "").casefold()
    candidates = []
    for day, month, year in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        candidates.append((int(year), int(month), int(day)))
    for day, month, year in re.findall(r"\b(\d{1,2})\.?\s+([a-zæøå]{3,9})\.?\s+(\d{4})\b", text):
        if month in MONTHS:
            candidates.append((int(year), MONTHS[month], int(day)))
    for month, day, year in re.findall(r"\b([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", text):
        if month in MONTHS:
            candidates.append((int(year), MONTHS[month], int(day)))
    for year, month, day in candidates:
        try:
            value = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
        if 1990 <= year and value <= datetime.now(timezone.utc):
            return value.date().isoformat()
    return None


def _page_evidence(profile: Profile, page: Page, extractor: str, span: str | None) -> str:
    return profile.evidence_from_response(page.response, "company_owned", extractor, span=span)


def extract_site(profile: Profile, capture: SiteCapture, assessment: dict[str, Any]) -> None:
    homepage = capture.homepage
    if homepage is None:
        return
    proof = assessment.get("proof") or {}
    proof_span = (proof.get("organisation_number") or {}).get("span") or "; ".join(assessment.get("reasons", []))[:300]
    proof_page = next((page for page in capture.pages if page.final_url == (proof.get("organisation_number") or {}).get("page")), homepage)
    identity_ev = _page_evidence(profile, proof_page, "site_identity_gate_v2", proof_span)
    home_ev = identity_ev if proof_page is homepage else _page_evidence(profile, homepage, "site_homepage_v2", homepage.title or homepage.final_url)
    source = assessment["candidate"]["source"]
    website_ev = [identity_ev, home_ev]
    if assessment["candidate"].get("evidence_id"):
        website_ev.append(assessment["candidate"]["evidence_id"])
    if not proof.get("site_specific", True):
        # Declared site that presents another brand, franchise or group: the registry link is reported as the
        # registry_website fact, but the site is not called this entity's own website and nothing on it is attributed.
        note = (f"The declared website {homepage.final_url} presents a different brand, franchise or group site; "
                "it is not treated as this entity's own website, and its profiles, news and jobs are not attributed.")
        profile.check("official_website", "ambiguous", note, website_ev)
        for name in ("social_profile", "news_item", "job_posting"):
            profile.check(name, "not_available", note)
        return
    profile.claim("official_website", "primary", homepage.final_url.split("#")[0], website_ev, confidence=float(assessment["score"]),
                  discovery_source=source, identity_method="verify_v2", identity_reasons=assessment.get("reasons", [])[:4])
    profile.company["website"] = homepage.final_url

    # Public brand and description
    org_items = [item for page in capture.pages for item in page.jsonld if _types(item) & ORG_TYPES]
    brand = homepage.site_name or next((item.get("name") for item in org_items if isinstance(item.get("name"), str)), None)
    legal_tokens = _tokens(profile.facts.get("name"))
    if brand and _tokens(brand) and _tokens(brand) != legal_tokens and len(brand) <= 80:
        profile.claim("public_brand_name", "site", brand.strip(), [home_ev], confidence=0.85, note="Brand/trading name shown on the verified company website.")
    if homepage.description:
        profile.claim("website_description", "meta", homepage.description, [home_ev], confidence=0.9, note="Company-reported description (not independently verified).")
    elif homepage.text:
        first = " ".join(homepage.text.split())[:400]
        if len(first) > 60:
            profile.claim("website_description", "text", first, [home_ev], confidence=0.8, note="Opening text of the verified homepage (company-reported).")

    # Social profiles: links on the verified site or in its structured data, gated by handle identity.
    brand_tokens = _tokens(brand) if brand else []
    domain_label = registered_domain(homepage.final_url).split(".")[0]
    seen: set[tuple[str, str]] = set()
    for page in capture.pages:
        links = list(page.social_links)
        for item in page.jsonld:
            same_as = item.get("sameAs")
            for raw in same_as if isinstance(same_as, list) else [same_as]:
                if isinstance(raw, str):
                    normalized = normalize_social_url(raw)
                    if normalized:
                        links.append(normalized)
        for link in links:
            key = (link["platform"], link["url"].casefold())
            if key in seen:
                continue
            seen.add(key)
            if social_handle_matches(link["url"], legal_tokens, brand_tokens, domain_label):
                ev = _page_evidence(profile, page, "site_social_links_v2", f"link to {link['url']}")
                profile.claim("social_profile", f"{link['platform']}:{link['url'].casefold()}", {"platform": link["platform"], "url": link["url"]},
                              [ev, identity_ev], confidence=0.9, note="Profile linked from the verified company website; handle matches the company name or domain.")
    if not any(item["field"] == "social_profile" for item in profile.claims.values()):
        profile.check("social_profile", "not_available", "No company-matching social profile links on the verified website.", [home_ev])

    # Addresses published by the company
    for page in capture.pages:
        for item in page.jsonld:
            address = item.get("address")
            for entry in address if isinstance(address, list) else [address]:
                if isinstance(entry, dict) and (entry.get("streetAddress") or entry.get("postalCode")):
                    value = {key: str(entry.get(source_key)).strip() for key, source_key in
                             (("street", "streetAddress"), ("postal_code", "postalCode"), ("city", "addressLocality"), ("country", "addressCountry")) if entry.get(source_key) and not isinstance(entry.get(source_key), dict)}
                    if value:
                        ev = _page_evidence(profile, page, "site_jsonld_address_v1", str(entry)[:300])
                        profile.claim("website_address", "|".join(value.get(k, "") for k in ("street", "postal_code")), value, [ev], confidence=0.85,
                                      note="Address published in the verified website's structured data.")

    # Leadership corroboration: registered role holders named on the verified site.
    folded = fold(" ".join(page.full_text for page in capture.pages if page.kind != "feed"))
    words = re.findall(r"[a-z0-9]+", folded)
    joined = " " + " ".join(words) + " "
    for claim in list(profile.claims.values()):
        if claim["field"] != "role" or (claim["value"] or {}).get("holder_type") != "person":
            continue
        name_words = re.findall(r"[a-z0-9]+", fold(claim["value"].get("name", "")))
        if len(name_words) >= 2 and (f" {' '.join(name_words)} " in joined or f" {name_words[0]} {name_words[-1]} " in joined):
            page = next((p for p in capture.pages if f"{name_words[-1]}" in fold(p.full_text)), homepage)
            ev = _page_evidence(profile, page, "site_role_mention_v1", f"{claim['value'].get('name')} named on company website")
            with profile.lock:
                claim["evidence_ids"] = sorted(set(claim["evidence_ids"]) | {ev})
                claim["corroborated_on_website"] = True

    _extract_jobs(profile, capture)
    _extract_news(profile, capture)


def _extract_jobs(profile: Profile, capture: SiteCapture) -> None:
    careers = [page for page in capture.pages if page.kind == "careers"]
    found = 0
    for page in capture.pages:
        for item in page.jsonld:
            if "JobPosting" not in _types(item):
                continue
            title = item.get("title") or item.get("name")
            if not isinstance(title, str) or not title.strip():
                continue
            valid_through = _date(item.get("validThrough"))
            if valid_through and valid_through < datetime.now(timezone.utc).date().isoformat():
                continue
            url = item.get("url") if isinstance(item.get("url"), str) else page.final_url
            ev = _page_evidence(profile, page, "site_jobposting_jsonld_v1", f"JobPosting: {title.strip()[:120]}")
            profile.claim("job_posting", f"site:{url}#{title.strip()[:80]}", {"title": title.strip()[:200], "url": url, "date_posted": _date(item.get("datePosted")),
                          "valid_through": valid_through, "source": "company website (JobPosting structured data)"}, [ev], confidence=0.9, effective_at=_date(item.get("datePosted")))
            found += 1
    for page in careers:
        ev_page = None
        ats_links = []
        for url, text in page.links:
            host = (urllib.parse.urlparse(url).hostname or "").casefold()
            path = urllib.parse.urlparse(url).path.strip("/")
            if not any(host == ats or host.endswith("." + ats) for ats in ATS_HOSTS):
                continue
            if host.endswith("finn.no") and "job" not in path:
                continue
            if not path or len(path.split("/")) < 2 and not re.search(r"\d{4,}", path):
                continue
            if not text or len(text) < 4 or text.casefold() in {"søk her", "apply", "søk", "les mer", "read more", "se stilling"}:
                text = text or path.split("/")[-1].replace("-", " ")
            ats_links.append((url, text))
        for url, text in ats_links[:20]:
            ev_page = ev_page or _page_evidence(profile, page, "site_careers_ats_links_v1", f"careers page links to {len(ats_links)} job pages")
            profile.claim("job_posting", f"ats:{url}", {"title": " ".join(text.split())[:200], "url": url, "source": "job page linked from the verified company careers page"},
                          [ev_page], confidence=0.8)
            found += 1
        ev = _page_evidence(profile, page, "site_careers_page_v1", page.title or page.final_url)
        profile.claim("careers_page", page.final_url, {"url": page.final_url, "title": page.title}, [ev], confidence=0.85)
    if not found:
        note = "Verified website has a careers page but no machine-readable job postings." if careers else "No careers page or job postings found on the verified website."
        profile.check("job_posting", "not_available", note)


def _extract_news(profile: Profile, capture: SiteCapture) -> None:
    items: dict[str, dict[str, Any]] = {}

    def add(page: Page, title: str, date: str | None, url: str | None, kind: str) -> None:
        title = " ".join(str(title or "").split())[:240]
        if not title or not date or len(title) < 8:
            return
        head = re.split(r"\s[|\-–]\s", title.casefold())[0].strip()
        if head in GENERIC_TITLES or title.casefold() == (page.title or "").casefold() and page.kind != "news":
            return
        url_key = (url or "").split("#")[0].split("?")[0].rstrip("/").casefold()
        key = url_key if url and url_key != page.final_url.split("?")[0].rstrip("/").casefold() else url_key + "#" + title.casefold()
        if key in items and len(title) < len(items[key]["title"]):
            items[key]["title"] = title  # prefer the shorter, un-suffixed title for the same article
        if key not in items:
            items[key] = {"page": page, "title": title, "date": date, "url": url or page.final_url, "kind": kind}

    for page in capture.pages:
        if page.kind == "feed":
            soup = BeautifulSoup(page.html, "xml")
            for entry in soup.find_all(["item", "entry"])[:30]:
                title = entry.find("title")
                link = entry.find("link")
                date = entry.find(["pubDate", "published", "updated", "dc:date"])
                href = (link.get("href") if link is not None and link.get("href") else link.get_text(strip=True) if link is not None else None)
                add(page, title.get_text(" ", strip=True) if title else "", _date(date.get_text(strip=True) if date else None), href, "feed")
            continue
        for item in page.jsonld:
            if _types(item) & ARTICLE_TYPES:
                url = item.get("url") if isinstance(item.get("url"), str) else (item.get("mainEntityOfPage") if isinstance(item.get("mainEntityOfPage"), str) else None)
                add(page, item.get("headline") or item.get("name"), _date(item.get("datePublished") or item.get("dateCreated")), url, "jsonld")
        if page.kind in {"news", "homepage"}:
            soup = BeautifulSoup(page.html, "lxml")
            published = soup.select_one('meta[property="article:published_time"], meta[name="article:published_time"], meta[itemprop="datePublished"]')
            if published is not None and page.kind == "news":
                heading = soup.select_one('meta[property="og:title"]')
                title = heading.get("content") if heading is not None else (soup.h1.get_text(" ", strip=True) if soup.h1 else page.title)
                add(page, title, _date(published.get("content")), page.final_url, "article_meta")
            anchors = soup.find_all("time")[:80]
            for time_tag in anchors:
                date = _date(time_tag.get("datetime")) or _text_date(time_tag.get_text(" ", strip=True))
                if not date:
                    continue
                card = time_tag
                for _ in range(5):
                    if card.parent is None:
                        break
                    card = card.parent
                    if card.find("a", href=True) and len(card.get_text(" ", strip=True)) > 25:
                        break
                anchor = card.find("a", href=True) if card is not None else None
                heading = card.find(["h1", "h2", "h3", "h4", "h5", "h6"]) if card is not None else None
                title = heading.get_text(" ", strip=True) if heading else (anchor.get_text(" ", strip=True) if anchor else "")
                url = urllib.parse.urljoin(page.final_url, anchor["href"]) if anchor else None
                if url and registered_domain(url) != capture.registered_domain:
                    continue
                add(page, title, date, url, "time_tag")
            if page.kind == "news" and not items:
                for node in soup.select("article, li, .news-item, .post, .article, .card")[:80]:
                    text = node.get_text(" ", strip=True)
                    date = _text_date(text[:200])
                    anchor = node.find("a", href=True)
                    heading = node.find(["h1", "h2", "h3", "h4", "h5", "h6"]) or anchor
                    if not date or heading is None:
                        continue
                    url = urllib.parse.urljoin(page.final_url, anchor["href"]) if anchor else None
                    if url and registered_domain(url) != capture.registered_domain:
                        continue
                    add(page, heading.get_text(" ", strip=True), date, url, "news_page_text")
    ordered = sorted(items.values(), key=lambda item: item["date"], reverse=True)[:12]
    for item in ordered:
        ev = _page_evidence(profile, item["page"], f"site_news_{item['kind']}_v1", f"{item['date']} {item['title'][:160]}")
        profile.claim("news_item", item["url"] + "#" + item["title"][:60], {"title": item["title"], "date": item["date"], "url": item["url"], "source": "verified company website"},
                      [ev], confidence=0.85, effective_at=item["date"])
    if not ordered:
        profile.check("news_item", "not_available", "No dated news or press items found on the verified website.")
