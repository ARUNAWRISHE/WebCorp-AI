"""Wikidata (CC0) lookup by Norwegian organisation number (property P2333).

Identity is exact: an item is used only when its P2333 statement equals the organisation number.
"""
from __future__ import annotations

import threading
import urllib.parse
from typing import Any

from .net import BudgetExceeded, Meter, Response, get
from .profile import Profile

API = "https://www.wikidata.org/w/api.php"
SOCIAL_PROPERTIES = {
    "P2002": ("x", "https://x.com/{}"),
    "P2013": ("facebook", "https://facebook.com/{}"),
    "P2003": ("instagram", "https://instagram.com/{}"),
    "P4264": ("linkedin", "https://linkedin.com/company/{}"),
    "P2397": ("youtube", "https://youtube.com/channel/{}"),
}


def _values(claims: dict[str, Any], prop: str) -> list[Any]:
    output = []
    for statement in claims.get(prop) or []:
        if statement.get("rank") == "deprecated":
            continue
        value = ((statement.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is not None:
            output.append(value)
    return output


class WikidataLookup:
    def __init__(self, organisations: list[str], *, deadline: float | None = None, batch: int = 40):
        self.organisations = organisations
        self.deadline = deadline
        self.batch = batch
        self.meter = Meter()
        self.hits: dict[str, dict[str, Any]] = {}
        self.responses: dict[str, Response] = {}
        self.status = "pending"
        self.note = ""
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="wikidata-lookup")

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        try:
            qids: list[str] = []
            failures = 0
            for start in range(0, len(self.organisations), self.batch):
                chunk = self.organisations[start:start + self.batch]
                query = "haswbstatement:" + "|".join(f"P2333={org}" for org in chunk)
                url = API + "?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": 50, "srprop": "", "format": "json"})
                response = get(url, meter=self.meter, accept="application/json", timeout=30, attempts=3, deadline=self.deadline)
                if not response.ok:
                    failures += 1
                    continue
                qids.extend(item["title"] for item in (response.json().get("query") or {}).get("search") or [])
            for start in range(0, len(qids), 50):
                chunk = qids[start:start + 50]
                url = API + "?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims|labels|descriptions|sitelinks/urls",
                                                         "languages": "nb|nn|en", "format": "json"})
                response = get(url, meter=self.meter, accept="application/json", timeout=40, attempts=3, deadline=self.deadline)
                if not response.ok:
                    failures += 1
                    continue
                for qid, entity in (response.json().get("entities") or {}).items():
                    claims = entity.get("claims") or {}
                    for org in _values(claims, "P2333"):
                        org = str(org).replace(" ", "")
                        if org in self.organisations and org not in self.hits:
                            self.hits[org] = {"qid": qid, "entity": entity}
                            self.responses[org] = response
            self.status = "available" if failures == 0 else "failed"
            self.note = f"{len(self.hits)} organisation numbers matched Wikidata items" + (f"; {failures} request(s) failed" if failures else "")
        except BudgetExceeded:
            self.status, self.note = "failed", "run budget exhausted during Wikidata lookup"
        except Exception as exc:
            self.status, self.note = "failed", f"{type(exc).__name__}: {exc}"[:300]
        finally:
            self.ready.set()

    def apply(self, profile: Profile) -> dict[str, Any] | None:
        org = profile.organisation_number
        hit = self.hits.get(org)
        if not hit:
            state = "not_available" if self.status == "available" else "failed"
            profile.check("knowledge_base_entry", state, f"No Wikidata item with P2333={org}." if state == "not_available" else f"Wikidata lookup failed: {self.note}")
            return None
        entity, qid = hit["entity"], hit["qid"]
        response = self.responses[org]
        ev = profile.evidence_from_response(response, "open_knowledge_base_cc0", "wikidata_p2333_v1", span=f"{qid} P2333={org}")
        labels = entity.get("labels") or {}
        descriptions = entity.get("descriptions") or {}
        label = next((labels[lang]["value"] for lang in ("nb", "nn", "en") if lang in labels), None)
        description = next((descriptions[lang]["value"] for lang in ("en", "nb", "nn") if lang in descriptions), None)
        sitelinks = entity.get("sitelinks") or {}
        wikipedia = next((sitelinks[key].get("url") for key in ("nowiki", "enwiki", "nnwiki") if key in sitelinks and sitelinks[key].get("url")), None)
        profile.claim("knowledge_base_entry", qid, {"source": "Wikidata", "id": qid, "url": f"https://www.wikidata.org/wiki/{qid}", "label": label,
                                                     "description": description, "wikipedia": wikipedia}, [ev], confidence=0.95)
        claims = entity.get("claims") or {}
        for prop, (platform, template) in SOCIAL_PROPERTIES.items():
            for handle in _values(claims, prop)[:2]:
                if isinstance(handle, str) and handle.strip():
                    url = template.format(urllib.parse.quote(handle.strip(), safe="-_.@"))
                    profile.claim("social_profile", f"{platform}:{url.casefold()}", {"platform": platform, "url": url},
                                  [profile.evidence_ref(source_url=response.url, final_url=response.final_url, source_class="open_knowledge_base_cc0", extractor="wikidata_p2333_v1",
                                                        retrieved_at=response.retrieved_at, sha=response.sha256, span=f"{qid} {prop}={handle}",
                                                        snapshot=profile.store.put(response.sha256, response.body), status=response.status)],
                                  confidence=0.85, note="Listed on the Wikidata item identified by this organisation number.")
        websites = [value for value in _values(claims, "P856") if isinstance(value, str)]
        return {"qid": qid, "website": websites[0] if websites else None, "evidence_id": ev}
