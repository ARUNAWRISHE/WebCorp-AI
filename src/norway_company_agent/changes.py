"""Claim-level refresh: typed changes, carry-forward of last supported values, and evidence preservation."""
from __future__ import annotations

from typing import Any

from .contract import stable_id

ADD_TYPES = {
    "role": "new_role", "registered_workplace": "new_location", "job_posting": "new_job", "news_item": "new_activity",
    "annual_account_filing": "new_filing", "social_profile": "new_social_profile", "official_website": "website_found",
    "group_relation": "new_group_relation", "knowledge_base_entry": "new_knowledge_base_entry", "registry_event": "new_registry_event",
    "careers_page": "careers_page_found", "industry": "industry_changed", "legal_name": "name_changed", "business_address": "address_changed",
    "food_safety_inspection": "new_inspection_site", "public_approval": "new_approval", "registry_website": "registry_website_added",
}
REMOVE_TYPES = {
    "role": "removed_role", "registered_workplace": "closed_location", "job_posting": "closed_job", "social_profile": "removed_social_profile",
    "official_website": "website_lost", "group_relation": "ended_group_relation", "careers_page": "careers_page_removed",
    "public_approval": "approval_removed",
}
VALUE_TYPES = {
    "legal_name": "name_changed", "legal_form": "legal_form_changed", "registry_status": "status_changed", "business_address": "address_changed",
    "industry": "industry_changed", "business_purpose": "purpose_changed", "registered_employees": "employee_count_changed",
    "annual_account_metric": "financial_value_restated", "official_website": "website_changed", "website_description": "description_changed",
    "public_brand_name": "brand_changed", "filed_account_years": "new_filing", "role": "role_changed", "registered_workplace": "location_changed",
    "job_posting": "job_updated", "founded_date": "founded_date_changed",
    "food_safety_inspection": "inspection_result_changed", "public_approval": "approval_changed", "registry_website": "registry_website_changed",
}
NON_MATERIAL = {"description_changed", "new_registry_event", "job_updated", "careers_page_found", "careers_page_removed", "brand_changed"}
# Families whose removal is only meaningful when the source was actually re-checked successfully.
NOISY_ADDS = {"annual_account_metric"}


def _available(claims: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["field"], item["key"]): item for item in claims if item.get("availability") == "available" and item.get("key") != "*"}


def refresh(previous: dict[str, Any] | None, current: dict[str, Any], *, detected_at: str, failed_fields: set[str]) -> dict[str, Any]:
    """Mutates and returns `current`: adds changes, first_seen, carried-forward claims and superseded evidence."""
    current.setdefault("changes", [])
    if not previous:
        for claim in current["claims"]:
            if claim["availability"] == "available":
                claim["first_seen"] = claim.get("first_seen") or detected_at
                claim["last_verified_at"] = detected_at
        return current
    prev_claims = previous.get("claims") or []
    prev_evidence = {item["id"]: item for item in previous.get("evidence") or []}
    old = _available(prev_claims)
    new = _available(current["claims"])
    old_by_id = {item["id"]: item for item in prev_claims}
    current_evidence = {item["id"]: item for item in current["evidence"]}

    def keep_old_evidence(ids: list[str]) -> list[str]:
        kept = []
        for evidence_id in ids:
            if evidence_id in current_evidence:
                kept.append(evidence_id)
            elif evidence_id in prev_evidence:
                item = dict(prev_evidence[evidence_id])
                item["superseded"] = True
                current_evidence[evidence_id] = item
                current["evidence"].append(item)
                kept.append(evidence_id)
        return kept

    # first_seen / last_verified_at
    for claim in current["claims"]:
        if claim["availability"] != "available":
            continue
        previous_claim = old_by_id.get(claim["id"])
        claim["first_seen"] = (previous_claim or {}).get("first_seen") or detected_at
        claim["last_verified_at"] = detected_at

    # Carry forward: a field family that failed this run keeps its last supported values (marked stale).
    carried_fields: set[str] = set()
    for (field, key), claim in old.items():
        if field in failed_fields and (field, key) not in new:
            carried = dict(claim)
            carried["stale"] = True
            carried["note"] = ((claim.get("note") or "") + " Carried forward from the previous run because this run could not re-check the source.").strip()
            carried["evidence_ids"] = keep_old_evidence(claim.get("evidence_ids") or [])
            current["claims"].append(carried)
            carried_fields.add(field)
    if carried_fields:
        current["claims"] = [item for item in current["claims"] if not (item.get("key") == "*" and item["field"] in carried_fields)]

    changes: list[dict[str, Any]] = []

    def change(kind: str, field: str, key: str, old_value: Any, new_value: Any, old_ids: list[str], new_ids: list[str]) -> None:
        changes.append({
            "id": stable_id("ch", current["organisation_number"], kind, field, key, old_value, new_value),
            "type": kind, "field": field, "key": key, "old_value": old_value, "new_value": new_value,
            "old_evidence_ids": keep_old_evidence(old_ids), "new_evidence_ids": new_ids, "detected_at": detected_at,
            "material": kind not in NON_MATERIAL,
        })

    # Keyed families where the key itself identifies the item (roles, jobs, locations...)
    for (field, key), claim in new.items():
        if (field, key) in old:
            before = old[(field, key)]
            if before.get("value") != claim.get("value") and field in VALUE_TYPES:
                change(VALUE_TYPES[field], field, key, before.get("value"), claim.get("value"), before.get("evidence_ids") or [], claim.get("evidence_ids") or [])
        elif field in ADD_TYPES and field not in NOISY_ADDS:
            # Singletons (key current/primary) whose value changed are reported as value changes when the old key exists.
            change(ADD_TYPES[field], field, key, None, claim.get("value"), [], claim.get("evidence_ids") or [])
    for (field, key), claim in old.items():
        if (field, key) in new or field in failed_fields:
            continue
        if field in REMOVE_TYPES:
            change(REMOVE_TYPES[field], field, key, claim.get("value"), None, claim.get("evidence_ids") or [], [])
    current["changes"] = sorted(changes, key=lambda item: (not item["material"], item["type"], item["key"]))
    current.setdefault("run", {})["previous_run_id"] = (previous.get("run") or {}).get("run_id")
    return current
