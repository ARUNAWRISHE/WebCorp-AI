"""Official Brønnøysund collectors (NLOD 2.0): identity, roles, workplaces, accounts, group, filing years."""
from __future__ import annotations

import threading
import time
from typing import Any

from .net import Meter, Response, get
from .official import ACCOUNTING_OBLIGATION_SOURCE, ALWAYS_ACCOUNTING_OBLIGED_FORMS
from .profile import Profile

ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
ROLES = ENTITY + "/roller"
SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=200"
GROUP = "https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
ACCOUNT_YEARS = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar"
ACCOUNT_COPY = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"
ENTITY_PAGE = "https://virksomhet.brreg.no/nb/oppslag/enheter/{org}"

PERSONAL_CONTACT_FORMS = {"ENK"}  # sole proprietorship contact data is personal data; not republished


def _json(response: Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _get_json(profile: Profile, url: str, attempts: int = 3) -> tuple[Response, Any]:
    response = get(url, meter=profile.meter, accept="application/json", timeout=20, attempts=attempts, deadline=profile.deadline)
    body = _json(response) if response.ok else None
    if response.ok and body is None and response.body.strip() == b"":
        # The accounts API occasionally returns an empty 200 body; retry once.
        response = get(url, meter=profile.meter, accept="application/json", timeout=20, attempts=2, deadline=profile.deadline)
        body = _json(response) if response.ok else None
    return response, body


def _state_for(response: Response) -> str:
    if response.status in {404, 410}:
        return "not_available"
    if response.status == 429 or response.status == -1:
        return "blocked"
    return "failed"


def _address(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    lines = [line for line in value.get("adresse") or [] if line]
    result = {
        "street": ", ".join(lines) or None,
        "postal_code": value.get("postnummer"),
        "city": value.get("poststed"),
        "municipality": value.get("kommune"),
        "municipality_number": value.get("kommunenummer"),
        "country": value.get("land"),
    }
    return {key: item for key, item in result.items() if item} or None


def _format_address(address: dict[str, Any] | None) -> str | None:
    if not address:
        return None
    return ", ".join(filter(None, [address.get("street"), " ".join(filter(None, [address.get("postal_code"), address.get("city")]))])) or None


# ---- identity -----------------------------------------------------------------------------------
def collect_entity(profile: Profile, bulk_row: dict[str, Any] | None = None) -> dict[str, Any] | None:
    org = profile.organisation_number
    response, body = _get_json(profile, ENTITY.format(org=org))
    if not (response.ok and isinstance(body, dict)):
        state = _state_for(response)
        note = f"Live registry lookup returned {response.error or response.status}"
        if response.status == 410:
            note = "The entity is deleted from Enhetsregisteret (HTTP 410)."
        profile.error("registry", state, note, response.url)
        if bulk_row:
            return _collect_bulk_identity(profile, bulk_row, note)
        for name in ("legal_name", "legal_form", "registry_status", "business_address", "industry", "business_purpose", "founded_date", "registered_employees"):
            profile.check(name, state, note)
        profile.modules["registry"] = state
        return None
    profile.modules["registry"] = "available"
    ev = profile.evidence_from_response(response, "official_registry", "brreg_entity_v1", span=f"organisasjonsnummer={org}")
    entity_page = ENTITY_PAGE.format(org=org)

    name = body.get("navn")
    form = (body.get("organisasjonsform") or {})
    business = _address(body.get("forretningsadresse"))
    postal = _address(body.get("postadresse"))
    profile.company.update({
        "name": name,
        "legal_form": form.get("kode"),
        "legal_form_description": form.get("beskrivelse"),
        "municipality": (business or postal or {}).get("municipality"),
        "registry_page": entity_page,
    })
    profile.facts.update({
        "name": name,
        "legal_form": form.get("kode"),
        "business_address": business,
        "postal_address": postal,
        "email": body.get("epostadresse"),
        "phones": [item for item in (body.get("telefon"), body.get("mobil")) if item],
        "registry_website": body.get("hjemmeside"),
        "in_group": bool(body.get("erIKonsern")),
        "historic_names": [item.get("navn") for item in body.get("historiskeNavn") or [] if item.get("navn")],
        "latest_filed_year": body.get("sisteInnsendteAarsregnskap"),
        "industry_codes": [body[key]["kode"] for key in ("naeringskode1", "naeringskode2", "naeringskode3") if isinstance(body.get(key), dict)],
    })

    profile.claim("legal_name", "current", name, [ev], confidence=0.99)
    if form:
        profile.claim("legal_form", "current", {"code": form.get("kode"), "description": form.get("beskrivelse")}, [ev], confidence=0.99)
    status_flags = {
        "bankrupt": bool(body.get("konkurs")),
        "under_liquidation": bool(body.get("underAvvikling")),
        "forced_dissolution": bool(body.get("underTvangsavviklingEllerTvangsopplosning")),
    }
    status_text = "bankrupt" if status_flags["bankrupt"] else "under liquidation" if status_flags["under_liquidation"] else "under forced dissolution" if status_flags["forced_dissolution"] else "active"
    profile.claim("registry_status", "current", {"status": status_text, **status_flags,
                                                   "registered_in_business_register": bool(body.get("registrertIForetaksregisteret")),
                                                   "vat_registered": bool(body.get("registrertIMvaregisteret"))}, [ev], confidence=0.99)
    if business:
        profile.claim("business_address", "business", {**business, "formatted": _format_address(business)}, [ev], confidence=0.99)
    if postal and postal != business:
        profile.claim("business_address", "postal", {**postal, "formatted": _format_address(postal)}, [ev], confidence=0.99)
    for index, key in enumerate(("naeringskode1", "naeringskode2", "naeringskode3"), 1):
        item = body.get(key)
        if isinstance(item, dict) and item.get("kode"):
            profile.claim("industry", f"nace{index}", {"code": item.get("kode"), "description": item.get("beskrivelse"), "rank": index}, [ev], confidence=0.99)
    purpose = " ".join(body.get("aktivitet") or body.get("vedtektsfestetFormaal") or []).strip()
    if purpose:
        profile.claim("business_purpose", "registered", " ".join(purpose.split()), [ev], confidence=0.99)
    else:
        profile.check("business_purpose", "not_available", "No registered activity statement in Enhetsregisteret.", [ev])
    if body.get("stiftelsesdato"):
        profile.claim("founded_date", "founded", body["stiftelsesdato"], [ev], confidence=0.99,
                      registration_date=body.get("registreringsdatoEnhetsregisteret"))
    elif body.get("registreringsdatoEnhetsregisteret"):
        profile.claim("founded_date", "registered", body["registreringsdatoEnhetsregisteret"], [ev], confidence=0.95,
                      note="Registration date in Enhetsregisteret; no foundation date was registered.")
    if body.get("harRegistrertAntallAnsatte") and body.get("antallAnsatte") is not None:
        profile.claim("registered_employees", "registry", body["antallAnsatte"], [ev], confidence=0.97,
                      effective_at=body.get("registreringsdatoAntallAnsatteEnhetsregisteret") or body.get("registreringsdatoAntallAnsatteNAVAaregisteret"),
                      note="Employee count registered in Enhetsregisteret (sourced from the NAV employer register).")
    else:
        profile.check("registered_employees", "not_available", "No registered employee count (the registry reports none or zero is not registered).", [ev])
    capital = body.get("kapital")
    if isinstance(capital, dict) and capital.get("belop") is not None:
        profile.claim("legal_form", "share_capital", {"amount": capital.get("belop"), "currency": capital.get("valuta"), "type": capital.get("type"), "shares": capital.get("antallAksjer")},
                      [ev], confidence=0.99, effective_at=capital.get("innfortDato"))
    for item in body.get("historiskeNavn") or []:
        if item.get("navn"):
            profile.claim("legal_name", f"former:{item.get('navn')}", {"former_name": item.get("navn"), "from": item.get("fraDato"), "to": item.get("tilDato")}, [ev], confidence=0.99)
    if form.get("kode") not in PERSONAL_CONTACT_FORMS:
        if body.get("hjemmeside"):
            profile.facts["registry_website_evidence"] = ev
    if body.get("registreringsdatoEnhetsregisteret"):
        profile.claim("registry_event", f"registered:{body['registreringsdatoEnhetsregisteret']}",
                      {"event": "Registered in Enhetsregisteret", "date": body["registreringsdatoEnhetsregisteret"]}, [ev],
                      confidence=0.99, effective_at=body["registreringsdatoEnhetsregisteret"])
    if body.get("vedtektsdato"):
        profile.claim("registry_event", f"articles:{body['vedtektsdato']}", {"event": "Articles of association dated", "date": body["vedtektsdato"]},
                      [ev], confidence=0.99, effective_at=body["vedtektsdato"])
    if isinstance(capital, dict) and capital.get("innfortDato"):
        profile.claim("registry_event", f"capital:{capital['innfortDato']}", {"event": "Share capital registered", "date": capital["innfortDato"],
                      "amount": capital.get("belop"), "currency": capital.get("valuta")}, [ev], confidence=0.99, effective_at=capital["innfortDato"])
    return body


def _collect_bulk_identity(profile: Profile, row: dict[str, Any], live_note: str) -> dict[str, Any]:
    org = profile.organisation_number
    ev = profile.evidence_ref(source_url="https://data.brreg.no/enhetsregisteret/api/enheter/lastned", source_class="official_registry_bulk",
                              extractor="brreg_bulk_row_v1", span=f"organisasjonsnummer={org}", sha=row.get("_snapshot_sha256"))
    profile.modules["registry"] = "available"
    profile.company.update({"name": row.get("name"), "legal_form": row.get("legal_form"), "municipality": row.get("municipality")})
    profile.facts.update({"name": row.get("name"), "legal_form": row.get("legal_form"), "registry_website": row.get("website") or None,
                          "business_address": {"municipality": row.get("municipality")}, "phones": [], "historic_names": [],
                          "latest_filed_year": row.get("latest_submitted_accounts")})
    note = f"From the frozen registry snapshot because the live lookup failed ({live_note})."
    profile.claim("legal_name", "current", row.get("name"), [ev], confidence=0.97, note=note)
    if row.get("legal_form"):
        profile.claim("legal_form", "current", {"code": row.get("legal_form")}, [ev], confidence=0.97, note=note)
    profile.claim("registry_status", "current", {"status": "bankrupt" if row.get("bankrupt") else "under liquidation" if row.get("liquidating") else "active",
                                                  "bankrupt": bool(row.get("bankrupt")), "under_liquidation": bool(row.get("liquidating"))}, [ev], confidence=0.95, note=note)
    if row.get("industry_code"):
        profile.claim("industry", "nace1", {"code": row.get("industry_code"), "description": row.get("industry_label"), "rank": 1}, [ev], confidence=0.97, note=note)
    if row.get("employees") is not None:
        profile.claim("registered_employees", "registry", row.get("employees"), [ev], confidence=0.9, note=note)
    for name in ("business_address", "business_purpose", "founded_date"):
        profile.check(name, "failed", "Live registry lookup failed; field absent from the bulk snapshot.")
    return {"navn": row.get("name"), "organisasjonsform": {"kode": row.get("legal_form")}, "hjemmeside": row.get("website")}


# ---- roles --------------------------------------------------------------------------------------
def collect_roles(profile: Profile) -> None:
    org = profile.organisation_number
    response, body = _get_json(profile, ROLES.format(org=org))
    if not (response.ok and isinstance(body, dict)):
        state = _state_for(response)
        profile.check("role", state, f"Role lookup returned {response.error or response.status}")
        if state != "not_available":
            profile.error("roles", state, f"Role lookup returned {response.error or response.status}", response.url)
        profile.modules["roles"] = state
        return
    profile.modules["roles"] = "available"
    ev = profile.evidence_from_response(response, "official_registry", "brreg_roles_v1", span="rollegrupper")
    people: list[dict[str, Any]] = []
    for group in body.get("rollegrupper") or []:
        group_type = group.get("type") or {}
        changed = group.get("sistEndret")
        if changed:
            profile.claim("registry_event", f"roles:{group_type.get('kode')}:{changed}",
                          {"event": f"Role group updated: {group_type.get('beskrivelse')}", "date": changed}, [ev], confidence=0.99, effective_at=changed)
        for item in group.get("roller") or []:
            if item.get("avregistrert"):
                continue
            role_type = item.get("type") or {}
            person = item.get("person") or {}
            entity = item.get("enhet") or {}
            if person:
                if person.get("erDoed"):
                    continue
                names = person.get("navn") or {}
                display = " ".join(filter(None, [names.get("fornavn"), names.get("mellomnavn"), names.get("etternavn")]))
                holder = {"name": display, "holder_type": "person"}
                if display:
                    people.append({"name": display, "role_code": role_type.get("kode"), "first": names.get("fornavn"), "last": names.get("etternavn")})
            else:
                display = entity.get("navn")
                if isinstance(display, list):
                    display = " ".join(display)
                holder = {"name": display, "holder_type": "organisation", "organisation_number": entity.get("organisasjonsnummer")}
            if not holder.get("name"):
                continue
            value = {"role": role_type.get("beskrivelse"), "role_code": role_type.get("kode"), "group": group_type.get("beskrivelse"), **holder}
            profile.claim("role", f"{role_type.get('kode')}:{holder['name']}", value, [ev], confidence=0.99, effective_at=changed)
    profile.facts["role_people"] = people
    if not any(item["field"] == "role" for item in profile.claims.values()):
        profile.check("role", "not_available", "No active role holders are registered.", [ev])


# ---- workplaces ---------------------------------------------------------------------------------
def collect_subunits(profile: Profile) -> None:
    org = profile.organisation_number
    response, body = _get_json(profile, SUBUNITS.format(org=org))
    if not (response.ok and isinstance(body, dict)):
        state = _state_for(response)
        profile.check("registered_workplace", state, f"Subunit lookup returned {response.error or response.status}")
        profile.error("workplaces", state, f"Subunit lookup returned {response.error or response.status}", response.url)
        profile.modules["workplaces"] = state
        return
    profile.modules["workplaces"] = "available"
    ev = profile.evidence_from_response(response, "official_registry", "brreg_subunits_v1", span=f"overordnetEnhet={org}")
    units = ((body.get("_embedded") or {}).get("underenheter")) or []
    subunits = []
    for item in units:
        if item.get("slettedato"):
            continue
        address = _address(item.get("beliggenhetsadresse") or item.get("postadresse"))
        industry = item.get("naeringskode1") or {}
        value = {
            "name": item.get("navn"),
            "organisation_number": item.get("organisasjonsnummer"),
            "address": {**address, "formatted": _format_address(address)} if address else None,
            "industry": {"code": industry.get("kode"), "description": industry.get("beskrivelse")} if industry else None,
            "registered_employees": item.get("antallAnsatte") if item.get("harRegistrertAntallAnsatte") else None,
            "established": item.get("oppstartsdato"),
            "website": item.get("hjemmeside"),
        }
        subunits.append(value)
        profile.claim("registered_workplace", str(item.get("organisasjonsnummer")), value, [ev], confidence=0.99, effective_at=item.get("oppstartsdato"))
    total = (body.get("page") or {}).get("totalElements")
    profile.facts["subunits"] = subunits
    profile.facts["subunit_total"] = total
    if not subunits:
        profile.check("registered_workplace", "not_available", "No active registered subunits (establishments) in Enhetsregisteret.", [ev])


# ---- group --------------------------------------------------------------------------------------
def _find_node(node: dict[str, Any], org: str) -> dict[str, Any] | None:
    if str(node.get("organisasjonsnummer")) == org:
        return node
    for child in node.get("children") or []:
        found = _find_node(child, org)
        if found:
            return found
    return None


def collect_group(profile: Profile) -> None:
    org = profile.organisation_number
    if not profile.facts.get("in_group"):
        profile.check("group_relation", "not_applicable", "The registry does not mark this entity as part of a group (erIKonsern=false).")
        return
    response, body = _get_json(profile, GROUP.format(org=org))
    if not (response.ok and isinstance(body, dict)):
        state = _state_for(response)
        profile.check("group_relation", state, f"Group structure lookup returned {response.error or response.status}")
        return
    ev = profile.evidence_from_response(response, "official_registry", "brreg_group_structure_v1", span="konsernstruktur")
    node = _find_node(body, org)
    group_orgs: set[str] = set()

    def walk(item: dict[str, Any]) -> None:
        if item.get("organisasjonsnummer"):
            group_orgs.add(str(item["organisasjonsnummer"]))
        for child in item.get("children") or []:
            walk(child)

    walk(body)
    profile.facts["group_orgs"] = sorted(group_orgs - {org})
    if str(body.get("organisasjonsnummer")) != org:
        profile.claim("group_relation", f"top_parent:{body.get('organisasjonsnummer')}", {"relation": "top parent", "name": body.get("navn"), "organisation_number": body.get("organisasjonsnummer")}, [ev], confidence=0.98)
    if node and node.get("parentOrganisasjonsnummer") and node.get("parentOrganisasjonsnummer") != body.get("organisasjonsnummer"):
        profile.claim("group_relation", f"parent:{node.get('parentOrganisasjonsnummer')}", {"relation": "parent", "name": node.get("parentNavn"), "organisation_number": node.get("parentOrganisasjonsnummer"), "ownership_basis": node.get("grunnlag")}, [ev], confidence=0.98)
    children = (node or {}).get("children") or ([] if node else [])
    for child in children[:50]:
        profile.claim("group_relation", f"subsidiary:{child.get('organisasjonsnummer')}", {"relation": "subsidiary", "name": child.get("navn"), "organisation_number": child.get("organisasjonsnummer"), "ownership_basis": child.get("grunnlag"), "since": child.get("dato")}, [ev], confidence=0.98)


# ---- accounts -----------------------------------------------------------------------------------
METRICS = (
    ("revenue", ("resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter")),
    ("operating_expenses", ("resultatregnskapResultat", "driftsresultat", "driftskostnad", "sumDriftskostnad")),
    ("payroll_expenses", ("resultatregnskapResultat", "driftsresultat", "driftskostnad", "loennskostnad")),
    ("operating_result", ("resultatregnskapResultat", "driftsresultat", "driftsresultat")),
    ("net_financial_items", ("resultatregnskapResultat", "finansresultat", "nettoFinans")),
    ("profit_before_tax", ("resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad")),
    ("annual_result", ("resultatregnskapResultat", "aarsresultat")),
    ("total_assets", ("eiendeler", "sumEiendeler")),
    ("cash_and_bank", ("eiendeler", "sumBankinnskuddOgKontanter")),
    ("equity", ("egenkapitalGjeld", "egenkapital", "sumEgenkapital")),
    ("total_debt", ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld")),
)


def _path(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def collect_accounts(profile: Profile) -> None:
    org = profile.organisation_number
    response, body = _get_json(profile, ACCOUNTS.format(org=org))
    if response.status == 404 or (response.ok and body == []):
        form = profile.facts.get("legal_form")
        if form and form not in ALWAYS_ACCOUNTING_OBLIGED_FORMS and not profile.facts.get("latest_filed_year"):
            state, note = "not_applicable", f"No normalised accounts; legal form {form} is not always accounting-obliged ({ACCOUNTING_OBLIGATION_SOURCE})."
        else:
            state, note = "not_available", "Regnskapsregisteret returned no normalised annual-account record; this is not a zero value."
        ev = profile.evidence_from_response(response, "official_accounts", "brreg_accounts_v2", span="no records") if response.status in {200, 404} else None
        for name in ("annual_account_metric", "annual_account_filing"):
            profile.check(name, state, note, [ev] if ev else [])
        profile.modules["financials"] = state
        return
    if not (response.ok and isinstance(body, list)):
        state = _state_for(response)
        message = f"Accounts lookup returned {response.error or response.status}"
        for name in ("annual_account_metric", "annual_account_filing"):
            profile.check(name, state, message)
        profile.error("financials", state, message, response.url)
        profile.modules["financials"] = state
        return
    profile.modules["financials"] = "available"
    records = sorted(body, key=lambda item: (_path(item, ("regnskapsperiode", "tilDato")) or "", item.get("regnskapstype") or ""), reverse=True)
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        period = record.get("regnskapsperiode") or {}
        account_type = (record.get("regnskapstype") or "SELSKAP").upper()
        scope = "group" if account_type == "KONSERN" else "company"
        reporting_period = {"from": period.get("fraDato"), "to": period.get("tilDato")}
        year = str(period.get("tilDato") or "")[:4]
        span_prefix = f"regnskapstype={account_type}; periode={period.get('fraDato')}..{period.get('tilDato')}"
        ev = profile.evidence_from_response(response, "official_accounts", "brreg_accounts_v2", span=span_prefix)
        currency = record.get("valuta") or "NOK"
        filing = {
            "year": year,
            "scope": scope,
            "currency": currency,
            "small_company_rules": _path(record, ("regnkapsprinsipper", "smaaForetak")),
            "audit_opted_out": _path(record, ("revisjon", "fravalgRevisjon")),
            "unaudited": _path(record, ("revisjon", "ikkeRevidertAarsregnskap")),
            "liquidation_accounts": record.get("avviklingsregnskap"),
            "journal_number": record.get("journalnr"),
        }
        profile.claim("annual_account_filing", f"{scope}:{period.get('tilDato')}", filing, [ev], confidence=0.99, reporting_period=reporting_period, effective_at=period.get("tilDato"))
        values: dict[str, Any] = {}
        for metric, path in METRICS:
            amount = _path(record, path)
            if amount is None:
                continue
            values[metric] = amount
            metric_ev = profile.evidence_from_response(response, "official_accounts", "brreg_accounts_v2", span=f"{span_prefix}; {'.'.join(path)}={amount}")
            profile.claim("annual_account_metric", f"{scope}:{period.get('tilDato')}:{metric}", amount, [metric_ev], confidence=0.99,
                          reporting_period=reporting_period, effective_at=period.get("tilDato"), metric=metric, scope=scope, unit=currency)
        if scope not in latest:
            latest[scope] = {"period": reporting_period, "currency": currency, **values}
    profile.facts["latest_accounts"] = latest


# ---- filing years (rate-limited lane) -----------------------------------------------------------
class FilingYearsLane:
    """Background lane for the copy-year endpoint (about 30 request starts per minute).

    The endpoint is slow (several seconds per response), so a few workers share one start schedule:
    request starts are spaced at least 2.05 s apart and a 429 pauses every worker.
    """

    def __init__(self, deadline: float | None, workers: int = 4, spacing: float = 2.05):
        self.deadline = deadline
        self.workers = workers
        self.spacing = spacing
        self.results: dict[str, tuple[Response | None, Any]] = {}
        self.queue: list[str] = []
        self.lock = threading.Lock()
        self.next_start = 0.0
        self.meter = Meter()
        self.done = threading.Event()
        self.stop_flag = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self, organisations: list[str]) -> None:
        self.queue = list(reversed(organisations))
        self.threads = [threading.Thread(target=self._run, daemon=True, name=f"filing-years-{index}") for index in range(self.workers)]
        for thread in self.threads:
            thread.start()

    def _reserve(self) -> bool:
        while True:
            if self.stop_flag.is_set() or (self.deadline and time.monotonic() > self.deadline - 30):
                return False
            with self.lock:
                now = time.monotonic()
                if now >= self.next_start:
                    self.next_start = now + self.spacing
                    return True
                wait = self.next_start - now
            time.sleep(min(wait, 1.0))

    def _run(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    break
                org = self.queue.pop()
            if not self._reserve():
                with self.lock:
                    self.queue.append(org)
                break
            try:
                response = get(ACCOUNT_YEARS.format(org=org), meter=self.meter, accept="application/json", timeout=30, attempts=1, deadline=self.deadline)
                body = _json(response) if response.ok else None
            except Exception:
                response, body = None, None
            if response is not None and response.status == 429:
                with self.lock:
                    self.next_start = time.monotonic() + 30
                    self.queue.append(org)
                continue
            with self.lock:
                self.results[org] = (response, body)
        if all(not thread.is_alive() or thread is threading.current_thread() for thread in self.threads):
            self.done.set()

    def apply(self, profile: Profile) -> None:
        org = profile.organisation_number
        with self.lock:
            result = self.results.get(org)
        if result is None:
            profile.check("filed_account_years", "blocked", "Not checked: the annual-account copy endpoint allows about 30 requests per minute and this company was not reached within the run budget.")
            return
        response, body = result
        if response is None or not response.ok or not isinstance(body, list):
            state = "not_available" if response is not None and response.status == 404 else ("blocked" if response is not None and response.status == 429 else "failed")
            profile.check("filed_account_years", state, f"Copy-year lookup returned {(response.error or response.status) if response else 'no response'}")
            return
        years = sorted({str(item) for item in body if str(item).isdigit()}, reverse=True)
        if not years:
            profile.check("filed_account_years", "not_available", "No filed annual-account copies are listed.")
            return
        ev = profile.evidence_from_response(response, "official_accounts", "brreg_account_copy_years_v1", span=f"years={','.join(years)}")
        profile.claim("filed_account_years", "copies", {"years": years, "latest": years[0], "earliest": years[-1],
                                                          "copies": [{"year": year, "url": ACCOUNT_COPY.format(org=org, year=year)} for year in years[:5]]},
                      [ev], confidence=0.99, effective_at=years[0])
