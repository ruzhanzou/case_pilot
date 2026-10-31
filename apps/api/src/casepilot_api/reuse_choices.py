"""Apply reviewer choices to a confirmed plan without changing the source assets."""

import json
from collections import Counter
from copy import deepcopy

from fastapi import HTTPException


def reviewer_choices(planning):
    choices = (planning.get("reuse") or {}).get("user_choices") or {}
    ids = {p["id"] for p in planning.get("test_points", [])}
    if (
        not isinstance(choices, dict)
        or set(choices) - ids
        or any(
            not isinstance(value, str) or value not in {"new", "exclude", "copy"}
            for value in choices.values()
        )
    ):
        raise HTTPException(status_code=422, detail="reuse_choices_invalid")
    decisions = {
        item["point_id"]: item for item in (planning.get("reuse") or {}).get("decisions", [])
    }
    if any(
        value == "copy"
        and (
            decisions.get(key, {}).get("action") != "reuse"
            or (decisions.get(key, {}).get("source") or {}).get("kind") != "formal"
        )
        for key, value in choices.items()
    ):
        raise HTTPException(status_code=422, detail="reuse_choices_invalid")
    return choices


def apply_reviewer_choices(planning):
    result = deepcopy(planning)
    reuse = result.get("reuse")
    if not reuse:
        return result
    choices = reviewer_choices(result)
    changed_keys = {
        d.get("source", {}).get("key") or d.get("source_key")
        for d in reuse.get("decisions", [])
        if (d.get("source", {}).get("key") or d.get("source_key"))
        and choices.get(d["point_id"]) in {"new", "exclude"}
    }
    if changed_keys:
        result["excluded_reuse_source_keys"] = sorted(
            set(result.get("excluded_reuse_source_keys", [])) | changed_keys
        )
        # Keep old mapping only for removed-point provenance; never enforce its stale budget.
        if result.get("output_obligations"):
            result["output_obligations"] = {
                **result["output_obligations"],
                "plan_fingerprint": "invalidated",
            }
    points = {p["id"]: p for p in result["test_points"]}
    decisions = []
    for decision in reuse.get("decisions", []):
        if decision["point_id"] not in points:
            continue
        if choices.get(decision["point_id"]) == "new":
            decision.update(
                action="new",
                source_key=None,
                reason="用户选择重新生成，不使用历史用例正文",
                point_snapshot=deepcopy(points[decision["point_id"]]),
            )
            decision.pop("source", None)
        decisions.append(decision)
    reuse["decisions"] = decisions
    reuse["summary"] = dict(Counter(d["action"] for d in decisions))
    return result


def confirm_asset_reuse(planning, confirmation, *, confirmed_keys=()):
    result = deepcopy(planning)
    reuse = result.get("reuse") or {}
    decisions = reuse.get("decisions", [])
    inherited = [
        d
        for d in decisions
        if d.get("action") in {"reuse", "modify"}
        and (d.get("source") or {}).get("kind") == "formal"
    ]
    reserved = [item for item in result.get("reserved_reuse_outputs", [])
                if item.get("source", {}).get("kind") == "formal"]
    if confirmation == "fresh" and (inherited or reserved):
        from casepilot_agent.output_obligations import apply_reserved_review

        revoked = {item["source"]["key"] for item in reserved}
        revoked.update(d.get("source", {}).get("key") or d.get("source_key") for d in inherited)
        revoked.discard(None)
        for item in reserved:
            for point_id in item["point_ids"]:
                reuse.setdefault("user_choices", {})[point_id] = "new"
        for decision in inherited:
            reuse.setdefault("user_choices", {})[decision["point_id"]] = "new"
        result["reuse"] = reuse
        apply_reserved_review(result, reuse.get("user_choices", {}))
        result = apply_reviewer_choices(result)
        result["excluded_reuse_source_keys"] = sorted(
            set(result.get("excluded_reuse_source_keys", [])) | revoked
        )
        result.pop("output_obligations", None)
        # Remove stale reuse-provenance citations from regenerated coverage.
        # This is not erasure of historical context or a blanket no-reference policy.
        # Apply only that same reference withdrawal to the server's comparison
        # snapshots; all coverage IDs and business fields remain unchanged.
        snapshots = [*result["reuse"].get("feature_snapshots", []),
                     *(decision["point_snapshot"]
                       for decision in result["reuse"].get("decisions", [])
                       if isinstance(decision.get("point_snapshot"), dict))]
        for point in [*result.get("test_points", []), *result.get("feature_points", []),
                      *snapshots]:
            retained = []
            for reference in point.get("source_refs", []):
                try:
                    provenance = json.loads(reference.get("excerpt") or "")
                except (ValueError, TypeError):
                    provenance = None
                if isinstance(provenance, dict) and provenance.get("source_key") in revoked:
                    continue
                retained.append(reference)
            if "source_refs" in point:
                point["source_refs"] = retained
        result["reuse"]["asset_confirmation"] = "fresh"
        return result
    if not inherited:
        return result
    if confirmation is None and reuse.get("asset_confirmation") == "reuse":
        confirmed_keys = set(confirmed_keys)
        if all(d.get("source_key") in confirmed_keys for d in inherited):
            confirmation = "reuse"
    if confirmation is None:
        raise HTTPException(status_code=409, detail="reuse_confirmation_required")
    if confirmation == "reuse" and any(d.get("test_object_match") != "same" for d in inherited):
        raise HTTPException(status_code=409, detail="reuse_test_object_mismatch")
    if confirmation == "fresh":
        for decision in inherited:
            decision.update(action="new", source_key=None, reason="用户选择不复用用例管理中的用例")
            decision.pop("source", None)
            reuse.setdefault("user_choices", {})[decision["point_id"]] = "new"
        reuse["summary"] = dict(Counter(d["action"] for d in decisions))
    reuse["asset_confirmation"] = confirmation
    return result
