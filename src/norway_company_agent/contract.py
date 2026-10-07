"""Signalpost output contract: availability states, typed envelope and stable identifiers."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Availability = Literal["available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"]
AVAILABILITY_STATES: tuple[str, ...] = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")
TerminalStatus = Literal["completed", "failed"]

# Precedence used to summarise several checks of one field family into one honest state.
STATE_PRECEDENCE = {"available": 0, "ambiguous": 1, "blocked": 2, "failed": 3, "not_available": 4, "not_applicable": 5}

SECTIONS: dict[str, str] = {
    "legal_identity": "Legal identity and public brand",
    "financials": "Latest annual accounts and available history",
    "leadership": "Leadership",
    "workplaces": "Registered workplaces and locations",
    "web_presence": "Verified official website and company-owned profiles",
    "hiring": "Hiring",
    "activity": "Dated public activity",
    "assessments": "Official inspections, approvals and ratings",
}


def internal_to_availability(status: str | None, *, identity: str | None = None) -> str:
    """Map the starter kit's internal evidence statuses to the six contract states."""
    status = (status or "").casefold()
    if status == "available":
        if identity in {"review", "related_or_uncertain", "ambiguous"}:
            return "ambiguous"
        return "available"
    if status in {"not_found", "not_available", "absent"}:
        return "not_available"
    if status in {"blocked", "blocked_robots", "blocked_policy"}:
        return "blocked"
    if status == "not_applicable":
        return "not_applicable"
    if status == "ambiguous":
        return "ambiguous"
    return "failed"


def summarise_states(states: list[str]) -> str:
    if not states:
        return "not_available"
    return min(states, key=lambda state: STATE_PRECEDENCE.get(state, 9))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("\x1f".join(canonical(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:20]}"


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Evidence(_Model):
    id: str
    source_url: str
    source_class: str
    retrieved_at: str
    content_sha256: str | None = None
    claim_span: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    extractor: str
    snapshot: str | None = None
    superseded: bool = False


class Claim(_Model):
    id: str
    field: str
    section: str
    key: str
    value: Any = None
    availability: Availability
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    reporting_period: dict[str, Any] | None = None
    effective_at: str | None = None
    first_seen: str | None = None
    last_verified_at: str | None = None
    stale: bool = False
    note: str | None = None


class Change(_Model):
    id: str
    type: str
    field: str
    key: str
    old_value: Any = None
    new_value: Any = None
    old_evidence_ids: list[str] = Field(default_factory=list)
    new_evidence_ids: list[str] = Field(default_factory=list)
    detected_at: str
    material: bool = True


class ErrorItem(_Model):
    module: str
    state: Availability
    message: str
    url: str | None = None


class Run(_Model):
    run_id: str
    started_at: str
    completed_at: str
    terminal_status: TerminalStatus
    agent_version: str
    previous_run_id: str | None = None


class Operations(_Model):
    requests: int = 0
    runtime_ms: int = 0
    third_party_cost_usd: float = 0.0
    bytes: int = 0


class Envelope(_Model):
    organisation_number: str
    run: Run
    company: dict[str, Any] = Field(default_factory=dict)
    sections: dict[str, dict[str, Any]] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)
    errors: list[ErrorItem] = Field(default_factory=list)
    operations: Operations = Field(default_factory=Operations)


def validate_envelope(envelope: dict[str, Any]) -> list[str]:
    """Schema plus referential checks: every claim's evidence must exist in the envelope."""
    problems: list[str] = []
    try:
        model = Envelope.model_validate(envelope)
    except Exception as exc:
        return [f"schema: {exc}"[:800]]
    evidence_ids = {item.id for item in model.evidence}
    for claim in model.claims:
        missing = [item for item in claim.evidence_ids if item not in evidence_ids]
        if missing:
            problems.append(f"claim {claim.id} references missing evidence {missing[:3]}")
        if claim.availability == "available" and not claim.evidence_ids:
            problems.append(f"available claim {claim.id} has no evidence")
        if claim.availability == "available" and claim.value is None:
            problems.append(f"available claim {claim.id} has no value")
    ids = [claim.id for claim in model.claims]
    if len(ids) != len(set(ids)):
        problems.append("duplicate claim ids")
    return problems
