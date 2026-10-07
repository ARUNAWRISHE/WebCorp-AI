"""Bounded, robots-aware company-site capture: homepage plus a few identity, careers and news pages."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import tldextract
import trafilatura
from bs4 import BeautifulSoup

from .net import BudgetExceeded, Response, get, robots_allowed
from .profile import Profile
from .website import _social_links, normalize_homepage

_extract = tldextract.TLDExtract(suffix_list_urls=())  # bundled public-suffix snapshot; no network

PAGE_GROUPS: dict[str, tuple[str, ...]] = {
    "identity": ("om-oss", "om_oss", "omoss", "about", "kontakt", "contact", "personvern", "privacy", "vilkar", "vilkår",
                 "salgsbetingelser", "kjopsbetingelser", "kjøpsbetingelser", "terms", "impressum", "firma", "selskapet"),
    "careers": ("karriere", "ledige-stillinger", "stillinger", "jobb", "career", "jobs", "rekruttering", "work-with-us", "jobbe-hos-oss"),
    "news": ("nyheter", "aktuelt", "news", "presse", "press", "blogg", "blog", "artikler", "nytt"),
    "team": ("ledelse", "ansatte", "vare-ansatte", "våre-ansatte", "team", "people", "management", "styret", "medarbeidere"),
}
GROUP_LIMITS = {"identity": 2, "careers": 1, "news": 1, "team": 1}
FEED_TYPES = ("application/rss+xml", "application/atom+xml")


@dataclass
class Page:
    kind: str
    url: str
    final_url: str
    response: Response
    title: str = ""
    description: str = ""
    site_name: str = ""
    text: str = ""
    full_text: str = ""
    identity_text: str = ""
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    social_links: list[dict[str, str]] = field(default_factory=list)
    feed_urls: list[str] = field(default_factory=list)
    html: str = ""


@dataclass
class SiteCapture:
    requested_url: str
    outcome: str  # available | not_available | blocked | failed
    note: str = ""
    pages: list[Page] = field(default_factory=list)
    attempted: list[dict[str, Any]] = field(default_factory=list)

    @property
    def homepage(self) -> Page | None:
        return self.pages[0] if self.pages else None

    @property
    def registered_domain(self) -> str:
        return registered_domain(self.homepage.final_url) if self.homepage else ""


def registered_domain(url: str) -> str:
    host = urllib.parse.urlparse(url if "://" in url else "https://" + url).hostname or ""
    parts = _extract(host)
    return parts.top_domain_under_public_suffix.casefold() if parts.suffix else host.casefold()


def _flatten_jsonld(value: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(value, list):
        for item in value:
            _flatten_jsonld(item, output)
    elif isinstance(value, dict):
        if "@graph" in value:
            _flatten_jsonld(value["@graph"], output)
        if value.get("@type"):
            output.append(value)
        for key, child in value.items():
            if key != "@graph" and isinstance(child, (dict, list)):
                _flatten_jsonld(child, output)


def parse_page(kind: str, response: Response) -> Page:
    html = response.text()
    page = Page(kind=kind, url=response.url, final_url=response.final_url, response=response, html=html[:1_500_000])
    soup = BeautifulSoup(html, "lxml")
    if soup.title:
        page.title = soup.title.get_text(" ", strip=True)[:300]
    for selector in ('meta[name="description"]', 'meta[property="og:description"]'):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            page.description = " ".join(str(tag["content"]).split())[:1000]
            break
    site_name = soup.select_one('meta[property="og:site_name"]')
    if site_name and site_name.get("content"):
        page.site_name = " ".join(str(site_name["content"]).split())[:200]
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        try:
            _flatten_jsonld(json.loads(raw), page.jsonld)
        except Exception:
            continue
    for link in soup.select("link[rel]"):
        rel = " ".join(link.get("rel") or []).casefold()
        if "alternate" in rel and str(link.get("type") or "").casefold() in FEED_TYPES and link.get("href"):
            page.feed_urls.append(urllib.parse.urljoin(page.final_url, str(link["href"])))
    page.social_links = _social_links(page.final_url, soup)
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        page.links.append((urllib.parse.urljoin(page.final_url, href), anchor.get_text(" ", strip=True)[:200]))
    identity_nodes = soup.select('footer, address, [class*="footer"], [id*="footer"], [class*="kontakt"], [class*="contact"], [itemprop="address"], [itemprop="legalName"]')
    page.identity_text = " ".join(" ".join(node.get_text(" ", strip=True).split()) for node in identity_nodes[:12])[:6000]
    for node in soup(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    page.full_text = " ".join(soup.get_text(" ", strip=True).split())[:200_000]
    try:
        page.text = (trafilatura.extract(html, url=page.final_url, include_links=False, include_tables=False, favor_precision=True) or "")[:8000]
    except Exception:
        page.text = ""
    return page


def _classify_links(page: Page, base_domain: str) -> dict[str, list[str]]:
    found: dict[str, dict[str, int]] = {group: {} for group in PAGE_GROUPS}
    for url, text in page.links:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or registered_domain(url) != base_domain:
            continue
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
        if clean.rstrip("/") == page.final_url.split("?")[0].rstrip("/") or re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?)$", parsed.path, re.I):
            continue
        haystack = (urllib.parse.unquote(parsed.path) + " " + text).casefold()
        for group, terms in PAGE_GROUPS.items():
            for rank, term in enumerate(terms):
                if term in haystack:
                    depth = parsed.path.strip("/").count("/")
                    score = rank * 10 + depth
                    found[group][clean] = min(score, found[group].get(clean, score))
                    break
    return {group: [url for url, _ in sorted(items.items(), key=lambda item: (item[1], item[0]))] for group, items in found.items()}


def _is_dns_failure(error: str | None) -> bool:
    text = (error or "").casefold()
    return any(marker in text for marker in ("getaddrinfo", "name or service not known", "nodename nor servname", "11001", "11004", "no address associated", "did not resolve"))


def fetch_html(profile: Profile, url: str, *, timeout: float = 10.0, max_bytes: int = 2_000_000) -> tuple[Response | None, str]:
    """Fetch one HTML page under robots policy. Returns (response, outcome)."""
    verdict, note = robots_allowed(url, meter=profile.meter, deadline=profile.deadline)
    if verdict == "unreachable":
        return None, "not_available" if _is_dns_failure(note) else "failed:" + note
    if verdict == "disallowed":
        return None, "blocked:" + note
    response = get(url, meter=profile.meter, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5", timeout=timeout,
                   max_bytes=max_bytes, attempts=1, guard=True, deadline=profile.deadline)
    if response.status == -1:
        return response, "blocked:" + (response.error or "blocked")
    if response.status in {404, 410}:
        return response, "not_available"
    if response.status in {401, 403, 429, 451}:
        return response, f"blocked:HTTP {response.status}"
    if not response.ok:
        if _is_dns_failure(response.error):
            return response, "not_available"
        return response, "failed:" + (response.error or str(response.status))
    content_type = response.headers.get("content-type", "").casefold()
    if content_type and "html" not in content_type and "xml" not in content_type:
        return response, f"failed:unsupported content type {content_type[:60]}"
    return response, "available"


def crawl_site(profile: Profile, url: str, *, max_pages: int = 6, site_budget: float = 35.0) -> SiteCapture:
    normalized = normalize_homepage(url)
    capture = SiteCapture(requested_url=url or "", outcome="not_available")
    if not normalized:
        capture.note = "invalid website URL"
        return capture
    started = time.monotonic()
    supplied_scheme = bool(re.match(r"^https?://", str(url or "").strip(), re.I))
    try:
        response, outcome = fetch_html(profile, normalized)
        if outcome != "available" and not supplied_scheme and normalized.startswith("https://"):
            fallback = "http://" + normalized.removeprefix("https://")
            response2, outcome2 = fetch_html(profile, fallback)
            if outcome2 == "available":
                response, outcome = response2, outcome2
        capture.attempted.append({"url": normalized, "outcome": outcome})
        if outcome != "available" or response is None:
            capture.outcome = outcome.split(":", 1)[0]
            capture.note = outcome.split(":", 1)[1] if ":" in outcome else ("domain does not resolve or no page" if capture.outcome == "not_available" else "")
            return capture
        homepage = parse_page("homepage", response)
        capture.pages.append(homepage)
        capture.outcome = "available"
        base = registered_domain(homepage.final_url)
        groups = _classify_links(homepage, base)
        queue: list[tuple[str, str]] = []
        for group, limit in GROUP_LIMITS.items():
            for link in groups[group][:limit]:
                if link not in {item[1] for item in queue}:
                    queue.append((group, link))
        for kind, link in queue:
            if len(capture.pages) >= max_pages or time.monotonic() - started > site_budget:
                break
            page_response, page_outcome = fetch_html(profile, link, max_bytes=1_500_000)
            capture.attempted.append({"url": link, "outcome": page_outcome})
            if page_outcome == "available" and page_response is not None and registered_domain(page_response.final_url) == base:
                capture.pages.append(parse_page(kind, page_response))
        feeds = [feed for page in capture.pages for feed in page.feed_urls if registered_domain(feed) == base]
        if feeds and time.monotonic() - started <= site_budget:
            feed_url = feeds[0]
            verdict, _ = robots_allowed(feed_url, meter=profile.meter, deadline=profile.deadline)
            if verdict == "allowed":
                feed_response = get(feed_url, meter=profile.meter, accept="application/rss+xml,application/atom+xml,application/xml,text/xml", timeout=10,
                                    max_bytes=1_000_000, attempts=1, guard=True, deadline=profile.deadline)
                if feed_response.ok:
                    capture.pages.append(Page(kind="feed", url=feed_url, final_url=feed_response.final_url, response=feed_response, html=feed_response.text()[:1_000_000]))
    except BudgetExceeded:
        if not capture.pages:
            capture.outcome, capture.note = "failed", "run budget exhausted"
    return capture
