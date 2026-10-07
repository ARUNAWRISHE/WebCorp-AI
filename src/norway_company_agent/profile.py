"""Per-company claim/evidence builder used by every collector."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .contract import stable_id, summarise_states
from .net import Meter, Response, utc_now
from .store import SnapshotStore

# Field family -> section. Every family here gets an explicit state in every envelope.
FIELD_SECTIONS: dict[str, str] = {
    "legal_name": "legal_identity",
    "legal_form": "legal_identity",
    "registry_status": "legal_identity",
    "business_address": "legal_identity",
    "industry": "legal_identity",
    "business_purpose": "legal_identity",
    "founded_date": "legal_identity",
    "registered_employees": "legal_identity",
    "public_brand_name": "legal_identity",
    "annual_account_metric": "financials",
    "annual_account_filing": "financials",
    "filed_account_years": "financials",
    "role": "leadership",
    "group_relation": "leadership",
    "registered_workplace": "workplaces",
    "website_address": "workplaces",
    "registry_website": "web_presence",
    "official_website": "web_presence",
    "website_description": "web_presence",
    "social_profile": "web_presence",
    "knowledge_base_entry": "web_presence",
    "job_posting": "hiring",
    "careers_page": "hiring",
    "news_item": "activity",
    "registry_event": "activity",
}
# Families that are optional enrichment: reported only when found, so they never add noise.
OPTIONAL_FIELDS = {"registry_website", "website_address", "public_brand_name", "website_description", "knowledge_base_entry", "careers_page", "group_relation"}


@dataclass
class Profile:
    organisation_number: str
    store: SnapshotStore
    deadline: float | None = None
    meter: Meter = field(default_factory=Meter)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    checks: dict[str, list[tuple[str, str, list[str]]]] = field(default_factory=dict)
    company: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)
    timings_ms: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ---- evidence ---------------------------------------------------------------------------
    def evidence_from_response(self, response: Response, source_class: str, extractor: str, span: str | None = None) -> str:
        snapshot = self.store.put(response.sha256, response.body) if response.body else None
        return self.evidence_ref(
            source_url=response.url,
            final_url=response.final_url,
            source_class=source_class,
            extractor=extractor,
            retrieved_at=response.retrieved_at,
            sha=response.sha256 if response.body else None,
            span=span,
            snapshot=snapshot,
            status=response.status,
            redirect_chain=response.redirect_chain or None,
        )

    def evidence_ref(
        self,
        *,
        source_url: str,
        source_class: str,
        extractor: str,
        retrieved_at: str | None = None,
        sha: str | None = None,
        span: str | None = None,
        snapshot: str | None = None,
        status: int | None = None,
        final_url: str | None = None,
        redirect_chain: list[str] | None = None,
    ) -> str:
        evidence_id = stable_id("ev", source_url, sha, span)
        with self.lock:
            if evidence_id not in self.evidence:
                item = {
                    "id": evidence_id,
                    "source_url": source_url,
                    "final_url": final_url or source_url,
                    "source_class": source_class,
                    "retrieved_at": retrieved_at or utc_now(),
                    "content_sha256": sha,
                    "claim_span": (span or None) and str(span)[:600],
                    "http_status": status,
                    "extractor": extractor,
                    "snapshot": snapshot,
                }
                if redirect_chain:
                    item["redirect_chain"] = redirect_chain[:10]
                self.evidence[evidence_id] = item
        return evidence_id

    # ---- claims -----------------------------------------------------------------------------
    def claim(
        self,
        field_name: str,
        key: str,
        value: Any,
        evidence_ids: list[str],
        *,
        confidence: float = 0.95,
        reporting_period: dict[str, Any] | None = None,
        effective_at: str | None = None,
        note: str | None = None,
        **extra: Any,
    ) -> str | None:
        if value in (None, "", [], {}):
            return None
        claim_id = stable_id("cl", self.organisation_number, field_name, key, value)
        with self.lock:
            # One claim per (field, key): a second source for the same item adds evidence, not a duplicate.
            existing = self.claims.get(claim_id) or next((item for item in self.claims.values() if item["field"] == field_name and item["key"] == str(key)), None)
            if existing:
                existing["evidence_ids"] = sorted(set(existing["evidence_ids"]) | set(evidence_ids))
                existing["confidence"] = max(existing.get("confidence") or 0, confidence)
                return claim_id
            item = {
                "id": claim_id,
                "field": field_name,
                "section": FIELD_SECTIONS.get(field_name, "legal_identity"),
                "key": str(key),
                "value": value,
                "availability": "available",
                "confidence": round(confidence, 3),
                "evidence_ids": sorted(set(evidence_ids)),
                "reporting_period": reporting_period,
                "effective_at": effective_at,
                "note": note,
                **extra,
            }
            self.claims[claim_id] = item
            self.checks.setdefault(field_name, []).append(("available", note or "", list(evidence_ids)))
        return claim_id

    def check(self, field_name: str, state: str, note: str, evidence_ids: list[str] | None = None) -> None:
        """Record a performed check for a field family (used when nothing publishable was found)."""
        with self.lock:
            self.checks.setdefault(field_name, []).append((state, note, list(evidence_ids or [])))

    def error(self, module: str, state: str, message: str, url: str | None = None) -> None:
        with self.lock:
            self.errors.append({"module": module, "state": state, "message": str(message)[:400], "url": url})

    def budget_left(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.monotonic()

    # ---- finalisation -----------------------------------------------------------------------
    def placeholder_claims(self, field_names: list[str] | None = None) -> list[dict[str, Any]]:
        """One explicit non-available claim per field family that has no available value."""
        output = []
        families = field_names or [name for name in FIELD_SECTIONS if name not in OPTIONAL_FIELDS]
        available = {item["field"] for item in self.claims.values() if item["availability"] == "available"}
        for name in families:
            if name in available:
                continue
            checks = self.checks.get(name, [])
            states = [state for state, _, _ in checks if state != "available"]
            if not checks:
                state, note, evidence_ids = "failed", "This field was not checked in this run (module not reached).", []
            else:
                state = summarise_states(states)
                notes = [note for check_state, note, _ in checks if check_state == state and note]
                note = "; ".join(dict.fromkeys(notes))[:500] or None
                evidence_ids = sorted({eid for _, _, ids in checks for eid in ids if eid in self.evidence})
            output.append({
                "id": stable_id("cl", self.organisation_number, name, "*", state),
                "field": name,
                "section": FIELD_SECTIONS[name],
                "key": "*",
                "value": None,
                "availability": state,
                "confidence": None,
                "evidence_ids": evidence_ids,
                "reporting_period": None,
                "effective_at": None,
                "note": note,
            })
        return output
