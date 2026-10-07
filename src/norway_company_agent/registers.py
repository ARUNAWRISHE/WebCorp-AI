"""Official sector registers matched exactly by organisation number (company or registered subunit).

- Mattilsynet food-safety inspections (smilefjes), CC BY 4.0, daily CSV.
- Arbeidstilsynet cleaning-company approval register (renholdsregisteret), NLOD, daily XML.
- DiBK central approval register (sentral godkjenning), open API; DiBK asks users not to store register
  data permanently, so raw DiBK responses are not written to the snapshot store (hash and span only).
"""
from __future__ import annotations

import csv
import io
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .net import BudgetExceeded, Meter, Response, get, utc_now
from .profile import Profile

SMILEFJES_URL = "https://data.mattilsynet.no/smilefjes-tilsyn.csv"
RENHOLD_URL = "https://registerdata.arbeidstilsynet.no/renhold_register.xml"
DIBK_URL = "https://sgregister.dibk.no/api/enterprises/{org}"
DIBK_PAGE = "https://sgregister.dibk.no/enterprises/{org}"
SMILEY = {"0": "smiling (no remarks)", "1": "smiling (minor remarks)", "2": "straight face (orders issued)", "3": "sad face (strict sanctions)"}

FOOD_SERVICE_DIVISIONS = {"55", "56"}
CONSTRUCTION_PREFIXES = ("41", "42", "43", "71.1")
CLEANING_PREFIXES = ("81.2",)


def _codes(profile: Profile) -> list[str]:
    codes = list(profile.facts.get("industry_codes") or [])
    for unit in profile.facts.get("subunits") or []:
        code = ((unit.get("industry") or {}).get("code"))
        if code:
            codes.append(code)
    return codes


def _orgs(profile: Profile) -> set[str]:
    return {profile.organisation_number} | {str(unit.get("organisation_number")) for unit in profile.facts.get("subunits") or [] if unit.get("organisation_number")}


def _download_complete(url: str, *, max_bytes: int, meter: Meter, deadline: float | None, chunk: int = 1 << 16) -> Response | None:
    """Stream a bulk file, verify it against Content-Length and resume short reads with HTTP Range."""
    import hashlib
    import urllib.request

    from .net import USER_AGENT

    body = bytearray()
    expected: int | None = None
    started = time.monotonic()
    headers_out: dict[str, str] = {}
    for _attempt in range(6):
        if deadline is not None and time.monotonic() > deadline:
            return None
        request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if body:
            request_headers["Range"] = f"bytes={len(body)}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=request_headers), timeout=60) as response:
                headers_out = {key.casefold(): value for key, value in response.headers.items()}
                if body and response.status != 206:
                    body.clear()  # server ignored the range; start over
                if expected is None and response.status == 200 and headers_out.get("content-length", "").isdigit():
                    expected = int(headers_out["content-length"])
                while True:
                    block = response.read(chunk)
                    if not block:
                        break
                    body.extend(block)
                    if len(body) > max_bytes:
                        return None
        except Exception:
            time.sleep(1.0)
            continue
        if expected is None or len(body) >= expected:
            break
    if expected is not None and len(body) != expected:
        return None
    meter.add(len(body), int((time.monotonic() - started) * 1000))
    return Response(url, url, 200, headers_out, bytes(body), int((time.monotonic() - started) * 1000), utc_now())


def _date_ddmmyyyy(value: str) -> str | None:
    value = (value or "").strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[4:]}-{value[2:4]}-{value[:2]}"
    return None


class SectorRegisters:
    """Downloads the bulk registers once per run in the background (cached for 20 h in the state dir)."""

    def __init__(self, cache_dir: Path | None, deadline: float | None):
        self.cache_dir = cache_dir
        self.deadline = deadline
        self.meter = Meter()
        self.ready = threading.Event()
        self.smilefjes: dict[str, list[dict[str, Any]]] = {}
        self.smilefjes_response: Response | None = None
        self.renhold: dict[str, dict[str, Any]] = {}
        self.renhold_response: Response | None = None
        self.status: dict[str, str] = {}
        self.thread = threading.Thread(target=self._load, daemon=True, name="sector-registers")

    def start(self) -> None:
        self.thread.start()

    def _download(self, url: str, name: str, max_bytes: int) -> Response | None:
        cached = self.cache_dir / name if self.cache_dir else None
        if cached and cached.exists() and time.time() - cached.stat().st_mtime < 20 * 3600:
            body = cached.read_bytes()
            meta = cached.with_suffix(cached.suffix + ".retrieved")
            retrieved = meta.read_text(encoding="utf-8").strip() if meta.exists() else utc_now()
            return Response(url, url, 200, {}, body, 0, retrieved)
        response = _download_complete(url, max_bytes=max_bytes, meter=self.meter, deadline=self.deadline)
        if response is None:
            return None
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(response.body)
            cached.with_suffix(cached.suffix + ".retrieved").write_text(response.retrieved_at, encoding="utf-8")
        return response

    def _load(self) -> None:
        try:
            response = self._download(SMILEFJES_URL, "smilefjes-tilsyn.csv", 80_000_000)
            if response is not None:
                text = response.body.decode("utf-8-sig", errors="replace")
                for row in csv.DictReader(io.StringIO(text), delimiter=";"):
                    org = (row.get("orgnummer") or "").strip()
                    if len(org) == 9 and org.isdigit():
                        self.smilefjes.setdefault(org, []).append(row)
                self.smilefjes_response = response
                self.status["smilefjes"] = f"available ({sum(len(v) for v in self.smilefjes.values())} inspections)"
            else:
                self.status["smilefjes"] = "failed"
        except BudgetExceeded:
            self.status["smilefjes"] = "failed: budget"
        except Exception as exc:
            self.status["smilefjes"] = f"failed: {type(exc).__name__}"
        try:
            response = self._download(RENHOLD_URL, "renhold_register.xml", 80_000_000)
            if response is not None:
                root = ET.fromstring(response.body)
                for company in root.iter("Virksomhet"):
                    main = company.find("Hovedenhet")
                    if main is None:
                        continue
                    org = (main.findtext("Organisasjonsnummer") or "").strip()
                    if org:
                        self.renhold[org] = {"status": (main.findtext("Godkjenningsstatus") or "").strip(), "name": (main.findtext("Navn") or "").strip()}
                self.renhold_response = response
                self.status["renhold"] = f"available ({len(self.renhold)} companies)"
            else:
                self.status["renhold"] = "failed"
        except BudgetExceeded:
            self.status["renhold"] = "failed: budget"
        except Exception as exc:
            self.status["renhold"] = f"failed: {type(exc).__name__}"
        finally:
            self.ready.set()

    # ---- per company ----------------------------------------------------------------------------
    def apply(self, profile: Profile, *, use_dibk: bool = True) -> None:
        codes = _codes(profile)
        orgs = _orgs(profile)
        self._apply_smilefjes(profile, codes, orgs)
        self._apply_renhold(profile, codes)
        if use_dibk:
            self._apply_dibk(profile, codes)
        else:
            profile.check("public_approval", "not_applicable", "DiBK connector disabled for this run.")

    def _apply_smilefjes(self, profile: Profile, codes: list[str], orgs: set[str]) -> None:
        relevant = any(code[:2] in FOOD_SERVICE_DIVISIONS for code in codes)
        if not self.status.get("smilefjes", "").startswith("available") or self.smilefjes_response is None:
            profile.check("food_safety_inspection", "failed" if relevant else "not_applicable", f"Mattilsynet inspection data unavailable: {self.status.get('smilefjes') or 'not loaded within the run budget'}")
            return
        rows = [row for org in orgs for row in self.smilefjes.get(org, [])]
        if not rows:
            profile.check("food_safety_inspection", "not_available" if relevant else "not_applicable",
                          "No Mattilsynet smilefjes inspection is registered for this company or its subunits." if relevant
                          else "Not a food-service business; Mattilsynet smilefjes inspections do not apply.")
            return
        response = self.smilefjes_response
        by_site: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_site.setdefault(row.get("tilsynsobjektid") or row.get("navn") or "", []).append(row)
        for site, items in list(by_site.items())[:25]:
            items.sort(key=lambda row: _date_ddmmyyyy(row.get("dato") or "") or "", reverse=True)
            latest = items[0]
            grade = (latest.get("total_karakter") or latest.get("karakter") or "").strip()
            date = _date_ddmmyyyy(latest.get("dato") or "")
            span = f"orgnummer={latest.get('orgnummer')}; tilsynid={latest.get('tilsynid')}; dato={latest.get('dato')}; total_karakter={grade}"
            ev = profile.evidence_from_response(response, "official_inspection_register", "mattilsynet_smilefjes_v1", span=span)
            value = {
                "establishment": latest.get("navn"),
                "address": ", ".join(filter(None, [latest.get("adrlinje1"), " ".join(filter(None, [latest.get("postnr"), latest.get("poststed")]))])),
                "latest_inspection_date": date,
                "grade": grade,
                "result": SMILEY.get(grade, "not graded"),
                "inspections_on_record": len(items),
                "history": [{"date": _date_ddmmyyyy(row.get("dato") or ""), "grade": (row.get("total_karakter") or "").strip()} for row in items[:6]],
                "source": "Mattilsynet smilefjes (CC BY 4.0)",
            }
            profile.claim("food_safety_inspection", site, value, [ev], confidence=0.98, effective_at=date,
                          note="Official food-safety inspection result; matched by the owner's organisation number.")

    def _apply_renhold(self, profile: Profile, codes: list[str]) -> None:
        relevant = any(code.startswith(CLEANING_PREFIXES) for code in codes)
        entry = self.renhold.get(profile.organisation_number)
        if entry and self.renhold_response is not None:
            ev = profile.evidence_from_response(self.renhold_response, "official_approval_register", "arbeidstilsynet_renhold_v1",
                                                span=f"Organisasjonsnummer={profile.organisation_number}; Godkjenningsstatus={entry['status']}")
            profile.claim("public_approval", "renhold", {"register": "Cleaning-company approval register (Arbeidstilsynet)", "status": entry["status"],
                                                         "listed_name": entry["name"]}, [ev], confidence=0.98, effective_at=self.renhold_response.retrieved_at[:10])
        elif relevant:
            state = "not_available" if self.status.get("renhold", "").startswith("available") else "failed"
            profile.check("public_approval", state, "Cleaning business not listed in Arbeidstilsynet's cleaning-company register." if state == "not_available"
                          else f"Cleaning register unavailable: {self.status.get('renhold') or 'not loaded within the run budget'}")

    def _apply_dibk(self, profile: Profile, codes: list[str]) -> None:
        if not any(code.startswith(CONSTRUCTION_PREFIXES) for code in codes):
            if not any(claim["field"] == "public_approval" for claim in profile.claims.values()):
                profile.check("public_approval", "not_applicable", "Not a construction or engineering business; central approval does not apply.")
            return
        response = get(DIBK_URL.format(org=profile.organisation_number), meter=profile.meter, accept="application/json", timeout=20, attempts=2, deadline=profile.deadline)
        if response.status == 404:
            profile.check("public_approval", "not_available", "No valid central approval (sentral godkjenning) in DiBK's register.")
            return
        if not response.ok:
            profile.check("public_approval", "failed", f"DiBK register lookup returned {response.error or response.status}")
            return
        try:
            data = (response.json() or {}).get("dibk-sgdata") or {}
        except Exception:
            profile.check("public_approval", "failed", "DiBK register returned unreadable data")
            return
        status = data.get("status") or {}
        areas = [{"function": item.get("function"), "subject_area": item.get("subject_area"), "grade": item.get("grade")}
                 for item in data.get("valid_approval_areas") or []]
        # Not stored permanently at DiBK's request: evidence keeps URL, hash, time and span, not the bytes.
        ev = profile.evidence_ref(source_url=response.url, final_url=response.final_url, source_class="official_approval_register", extractor="dibk_sgregister_v1",
                                  retrieved_at=response.retrieved_at, sha=response.sha256, status=response.status,
                                  span=f"approved={status.get('approved')}; approval_period_to={status.get('approval_period_to')}; areas={len(areas)}")
        profile.claim("public_approval", "dibk", {"register": "Central approval for building enterprises (DiBK)", "approved": status.get("approved"),
                                                  "valid_until": status.get("approval_period_to"), "approval_areas": areas[:20],
                                                  "certificate": status.get("approval_certificate") or DIBK_PAGE.format(org=profile.organisation_number)},
                      [ev], confidence=0.98, effective_at=status.get("approval_period_to"))
