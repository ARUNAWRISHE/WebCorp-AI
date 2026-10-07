"""Offline regression tests for the Signalpost agent (no network)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent import agent as agent_module  # noqa: E402
from norway_company_agent import brreg  # noqa: E402
from norway_company_agent.agent import RunConfig, build_envelope, compute_sections, failed_envelope, read_inputs, run  # noqa: E402
from norway_company_agent.changes import refresh  # noqa: E402
from norway_company_agent.contract import AVAILABILITY_STATES, internal_to_availability, validate_envelope  # noqa: E402
from norway_company_agent.net import Response  # noqa: E402
from norway_company_agent.profile import Profile  # noqa: E402
from norway_company_agent.sitecrawl import Page, SiteCapture  # noqa: E402
from norway_company_agent.store import SnapshotStore  # noqa: E402
from norway_company_agent.synthesis import _numbers, template_summary  # noqa: E402
from norway_company_agent.verify import assess, org_numbers  # noqa: E402
from norway_company_agent.webdiscovery import guessed_domains  # noqa: E402


# ---- contract -----------------------------------------------------------------------------------
def test_internal_states_map_to_six_contract_states():
    cases = {
        ("available", None): "available", ("available", "review"): "ambiguous", ("not_found", None): "not_available",
        ("blocked", None): "blocked", ("blocked_robots", None): "blocked", ("not_applicable", None): "not_applicable",
        ("source_error", None): "failed", ("budget_exhausted", None): "failed", ("weird", None): "failed",
    }
    for (status, identity), expected in cases.items():
        assert internal_to_availability(status, identity=identity) == expected
        assert expected in AVAILABILITY_STATES


def test_failed_envelope_is_valid_and_explicit():
    envelope = failed_envelope("123456789", run_id="r", started_at="2026-10-07T00:00:00Z", message="boom")
    assert validate_envelope(envelope) == []
    assert envelope["run"]["terminal_status"] == "failed"
    assert all(claim["availability"] == "failed" for claim in envelope["claims"])


def test_available_claim_without_evidence_is_rejected():
    envelope = failed_envelope("123456789", run_id="r", started_at="t", message="x")
    envelope["claims"].append({"id": "cl-x", "field": "legal_name", "section": "legal_identity", "key": "current", "value": "X AS",
                               "availability": "available", "evidence_ids": []})
    assert any("no evidence" in problem for problem in validate_envelope(envelope))


# ---- inputs -------------------------------------------------------------------------------------
def test_read_inputs_formats_invalid_and_duplicates(tmp_path):
    (tmp_path / "a.txt").write_text("923 609 016\n923609016\nabc\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text('{"organisation_number": "914778271"}\n"810034882"\n', encoding="utf-8")
    (tmp_path / "c.csv").write_text("orgnr,name\n923609016,Equinor\n", encoding="utf-8")
    (tmp_path / "d.json").write_text(json.dumps({"organisation_numbers": ["923609016", "914778271"]}), encoding="utf-8")
    assert [(item["organisation_number"], item["valid"]) for item in read_inputs(str(tmp_path / "a.txt"))] == [("923609016", True), ("abc", False)]
    assert [item["organisation_number"] for item in read_inputs(str(tmp_path / "b.jsonl"))] == ["914778271", "810034882"]
    assert [item["organisation_number"] for item in read_inputs(str(tmp_path / "c.csv"))] == ["923609016"]
    assert len(read_inputs(str(tmp_path / "d.json"))) == 2


# ---- identity -----------------------------------------------------------------------------------
def _capture(text: str, *, title: str = "", host: str = "example.no", footer: str = "") -> SiteCapture:
    response = Response(url=f"https://{host}/", final_url=f"https://{host}/", status=200, headers={}, body=text.encode(), elapsed_ms=1, retrieved_at="t")
    page = Page(kind="homepage", url=response.url, final_url=response.final_url, response=response, title=title, full_text=text + " " + footer,
                identity_text=footer, text=text)
    return SiteCapture(requested_url=response.url, outcome="available", pages=[page])


FACTS = {"name": "LYNGDAL GLASSREKKVERK AS", "historic_names": ["TORE FOSS AS"], "phones": ["38 34 00 00"], "email": "post@lgr.no",
         "business_address": {"street": "Kroken 4", "postal_code": "4580"}, "role_people": [{"name": "Tore Foss", "first": "Tore", "last": "Foss", "role_code": "DAGL"}]}


def test_org_number_on_site_is_exact_even_with_spaces():
    capture = _capture("Lyngdal Glassrekkverk AS · Org.nr. 916 617 445 MVA", host="lyngdalglassrekkverk.no")
    result = assess(capture, FACTS, "916617445", "guessed_domain")
    assert result["status"] == "exact" and result["score"] == 1.0


def test_guessed_domain_with_name_only_is_not_published():
    capture = _capture("Velkommen til Lyngdal Glassrekkverk", title="Lyngdal Glassrekkverk", host="lyngdalglassrekkverk.no")
    assert assess(capture, FACTS, "916617445", "guessed_domain")["status"] == "ambiguous"


def test_guessed_domain_with_name_and_phone_is_exact():
    capture = _capture("Ring oss på 38 34 00 00", title="Lyngdal Glassrekkverk", host="lyngdalglassrekkverk.no")
    assert assess(capture, FACTS, "916617445", "guessed_domain")["status"] == "exact"


def test_former_name_plus_role_holder_is_not_exact_for_discovered_domain():
    # Successor-company trap: the site belongs to a new company using the former name and the same person.
    capture = _capture("Tore Foss AS – snekker. Daglig leder Tore Foss", title="Tore Foss AS", host="torefoss.no")
    assert assess(capture, FACTS, "916617445", "guessed_domain")["status"] != "exact"


def test_site_showing_another_org_number_is_rejected():
    capture = _capture("Glass AS · Org.nr 999 888 777", title="Glass AS", host="glass.no")
    assert assess(capture, FACTS, "916617445", "guessed_domain")["status"] == "rejected"


def test_parked_page_is_rejected():
    capture = _capture("This domain is for sale. Buy this domain today.", host="lyngdalglassrekkverk.no")
    assert assess(capture, FACTS, "916617445", "registry")["status"] == "rejected"


def test_org_number_pattern_does_not_match_inside_longer_numbers():
    assert org_numbers("Konto 1234916617445999") == set()
    assert org_numbers("NO 916.617.445 MVA") == {"916617445"}


def test_guessed_domains_skip_generic_and_short_names():
    assert guessed_domains("HOLDING AS") == []
    assert "sorlandsporteneiendom.no" in guessed_domains("SØRLANDSPORTEN EIENDOM AS")
    assert "sorlandsporten.no" in guessed_domains("SØRLANDSPORTEN EIENDOM AS")


# ---- accounts ordering (regression: starter treated the oldest record as the latest) -------------
def test_accounts_are_sorted_newest_first(monkeypatch, tmp_path):
    body = [
        {"regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2023-01-01", "tilDato": "2023-12-31"}, "valuta": "NOK",
         "resultatregnskapResultat": {"aarsresultat": 1.0, "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 10.0}}}},
        {"regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "valuta": "NOK",
         "resultatregnskapResultat": {"aarsresultat": 3.0, "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 30.0}}}},
    ]
    raw = json.dumps(body).encode()
    monkeypatch.setattr(brreg, "get", lambda url, **kwargs: Response(url, url, 200, {}, raw, 1, "2026-10-07T00:00:00Z"))
    profile = Profile("123456789", SnapshotStore(tmp_path))
    brreg.collect_accounts(profile)
    assert profile.facts["latest_accounts"]["company"]["period"]["to"] == "2025-12-31"
    assert profile.facts["latest_accounts"]["company"]["revenue"] == 30.0
    revenue_claims = [item for item in profile.claims.values() if item["field"] == "annual_account_metric" and item["key"].endswith(":revenue")]
    assert {item["reporting_period"]["to"] for item in revenue_claims} == {"2023-12-31", "2025-12-31"}
    assert all(profile.evidence[item["evidence_ids"][0]]["snapshot"] for item in revenue_claims)


def test_missing_accounts_are_not_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(brreg, "get", lambda url, **kwargs: Response(url, url, 404, {}, b"", 1, "t", "HTTP 404"))
    profile = Profile("123456789", SnapshotStore(None))
    profile.facts["legal_form"] = "AS"
    brreg.collect_accounts(profile)
    placeholders = {item["field"]: item for item in profile.placeholder_claims()}
    assert placeholders["annual_account_metric"]["availability"] == "not_available"
    assert placeholders["annual_account_metric"]["value"] is None


# ---- refresh ------------------------------------------------------------------------------------
def _profile_envelope(roles: list[str], *, jobs_failed: bool = False) -> dict:
    profile = Profile("123456789", SnapshotStore(None))
    ev = profile.evidence_ref(source_url="https://data.brreg.no/x", source_class="official_registry", extractor="t", sha="a" * 64)
    profile.claim("legal_name", "current", "X AS", [ev])
    for name in roles:
        profile.claim("role", f"DAGL:{name}", {"role": "Daglig leder", "name": name}, [ev])
    if jobs_failed:
        profile.check("job_posting", "failed", "feed down")
    else:
        profile.claim("job_posting", "nav:1", {"title": "Snekker"}, [ev])
    envelope = build_envelope(profile, run_id="r", started_at="t", completed_at="t", terminal_status="completed", runtime_ms=1)
    return envelope


def test_refresh_detects_typed_changes_and_preserves_old_evidence():
    previous = _profile_envelope(["Kari Nordmann"])
    refresh(None, previous, detected_at="2026-10-01T00:00:00Z", failed_fields=set())
    current = _profile_envelope(["Ola Nordmann"])
    refresh(previous, current, detected_at="2026-10-07T00:00:00Z", failed_fields=set())
    kinds = sorted(change["type"] for change in current["changes"])
    assert kinds == ["new_role", "removed_role"]
    assert validate_envelope(current) == []


def test_identical_rerun_produces_no_changes():
    first = _profile_envelope(["Kari Nordmann"])
    refresh(None, first, detected_at="2026-10-01T00:00:00Z", failed_fields=set())
    second = _profile_envelope(["Kari Nordmann"])
    refresh(first, second, detected_at="2026-10-07T00:00:00Z", failed_fields=set())
    assert second["changes"] == []
    assert [claim["id"] for claim in first["claims"]] == [claim["id"] for claim in second["claims"]]
    first_seen = {claim["id"]: claim.get("first_seen") for claim in second["claims"] if claim["availability"] == "available"}
    assert set(first_seen.values()) == {"2026-10-01T00:00:00Z"}


def test_failed_refresh_carries_forward_last_supported_value():
    previous = _profile_envelope(["Kari Nordmann"])
    refresh(None, previous, detected_at="2026-10-01T00:00:00Z", failed_fields=set())
    current = _profile_envelope(["Kari Nordmann"], jobs_failed=True)
    failed = {claim["field"] for claim in current["claims"] if claim["key"] == "*" and claim["availability"] == "failed"}
    refresh(previous, current, detected_at="2026-10-07T00:00:00Z", failed_fields=failed)
    jobs = [claim for claim in current["claims"] if claim["field"] == "job_posting"]
    assert len(jobs) == 1 and jobs[0]["stale"] is True and jobs[0]["value"] == {"title": "Snekker"}
    assert not any(change["type"] == "closed_job" for change in current["changes"])
    assert validate_envelope(current) == []


# ---- synthesis ----------------------------------------------------------------------------------
def test_template_summary_cites_only_existing_claims():
    envelope = _profile_envelope(["Kari Nordmann"])
    envelope["sections"] = compute_sections(envelope)
    summary = template_summary(envelope)
    ids = {claim["id"] for claim in envelope["claims"]}
    assert summary["sentences"]
    assert all(cid in ids for sentence in summary["sentences"] for cid in sentence["claim_ids"])


def test_number_extraction_for_llm_validation():
    assert _numbers("Revenue NOK 10 021 242 in 2025") >= {"10021242", "2025"}


# ---- end-to-end contract under faults and budget --------------------------------------------------
def _fake_research(profile, **kwargs):
    org = profile.organisation_number
    if org.endswith("1"):
        raise RuntimeError("simulated crash")
    if org.endswith("2"):
        time.sleep(120)  # far longer than the run budget: must still produce an envelope
        return
    ev = profile.evidence_ref(source_url="https://data.brreg.no/x", source_class="official_registry", extractor="t", sha="b" * 64)
    profile.modules["registry"] = "available"
    profile.claim("legal_name", "current", f"Company {org}", [ev])
    profile.company["name"] = f"Company {org}"


def test_one_envelope_per_input_under_crash_timeout_and_invalid_input(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "research_company", _fake_research)
    inputs = tmp_path / "in.txt"
    inputs.write_text("\n".join(["100000001", "100000002", "100000003", "not-a-number", "100000003"]), encoding="utf-8")
    config = RunConfig(input_path=str(inputs), output=str(tmp_path / "out.jsonl"), report=str(tmp_path / "report.json"), viewer=str(tmp_path / "v.html"),
                       state_dir=str(tmp_path / "state"), time_budget=20, workers=3, llm="off", use_nav=False, use_wikidata=False, use_history=False)
    started = time.monotonic()
    report = run(config)
    assert time.monotonic() - started < 20
    assert report["checks"]["within_time_budget"]
    rows = [json.loads(line) for line in (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["organisation_number"] for row in rows] == ["100000001", "100000002", "100000003", "not-a-number"]
    assert report["checks"]["one_envelope_per_input"] and report["checks"]["schema_valid"] and report["checks"]["only_contract_states"]
    assert all(validate_envelope(row) == [] for row in rows)
    by_org = {row["organisation_number"]: row for row in rows}
    assert by_org["100000003"]["run"]["terminal_status"] == "completed"
    assert by_org["100000001"]["run"]["terminal_status"] == "failed"
    assert by_org["not-a-number"]["run"]["terminal_status"] == "failed"
    assert (tmp_path / "v.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    # Second run against the archived state is idempotent for unchanged companies.
    report2 = run(config)
    rows2 = {json.loads(line)["organisation_number"]: json.loads(line) for line in (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()}
    assert rows2["100000003"]["changes"] == []
    assert rows2["100000003"]["run"]["previous_run_id"]
    assert report2["checks"]["one_envelope_per_input"]


@pytest.mark.parametrize("state", AVAILABILITY_STATES)
def test_sections_accept_every_state(state):
    envelope = failed_envelope("123456789", run_id="r", started_at="t", message="x")
    for claim in envelope["claims"]:
        claim["availability"] = state if state != "available" else "failed"
    envelope["sections"] = compute_sections(envelope)
    assert validate_envelope(envelope) == []


def test_registry_declared_group_site_links_but_is_not_site_specific():
    # Parent/brand site that only lists the legal entity in its footer.
    capture = _capture("Bonnier Healthcare – our brands", title="Bonnier Healthcare", host="bonnierhealthcare.no",
                       footer="Lyngdal Glassrekkverk AS – en del av Bonnier")
    result = assess(capture, FACTS, "916617445", "registry")
    assert result["status"] == "exact"
    assert result["proof"]["site_specific"] is False


def test_subunit_org_number_on_site_is_exact():
    facts = {**FACTS, "subunits": [{"organisation_number": "973123456"}]}
    capture = _capture("Avdeling Lyngdal · org.nr 973 123 456", host="lgr-avd.no")
    result = assess(capture, facts, "916617445", "guessed_domain")
    assert result["status"] == "exact" and result["proof"]["site_specific"] is True


def test_postcode_and_city_corroborate_a_guessed_domain():
    facts = {**FACTS, "business_address": {"street": "Postboks 12", "postal_code": "4580", "city": "LYNGDAL"}, "phones": [], "email": None}
    capture = _capture("Lyngdal Glassrekkverk AS, 4580 Lyngdal", title="Lyngdal Glassrekkverk", host="lyngdalglassrekkverk.no")
    assert assess(capture, facts, "916617445", "guessed_domain")["status"] == "exact"


def test_norwegian_and_english_text_dates():
    from norway_company_agent.site_extract import _text_date
    assert _text_date("Publisert 12.09.2026") == "2026-09-12"
    assert _text_date("12. september 2026") == "2026-09-12"
    assert _text_date("September 12, 2026") == "2026-09-12"
    assert _text_date("31.02.2026") is None
    assert _text_date("ingen dato") is None


def test_franchise_site_is_not_published_as_official_website(tmp_path):
    from norway_company_agent.site_extract import extract_site
    profile = Profile("916617445", SnapshotStore(None))
    profile.facts.update(FACTS)
    capture = _capture("7-Eleven – alltid åpent", title="7-Eleven Norge", host="7-eleven.no", footer="Lyngdal Glassrekkverk AS")
    assessment = assess(capture, FACTS, "916617445", "registry")
    assert assessment["status"] == "exact" and assessment["proof"]["site_specific"] is False
    extract_site(profile, capture, {**assessment, "candidate": {"source": "registry", "url": "https://7-eleven.no/"}})
    assert not any(item["field"] in {"official_website", "social_profile", "news_item"} for item in profile.claims.values())
    states = {item["field"]: item["availability"] for item in profile.placeholder_claims()}
    assert states["official_website"] == "ambiguous"
