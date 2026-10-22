"""Apply reviewer choices to a confirmed plan without changing the source assets."""

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
    inherited = [d for d in decisions if d.get("action") in {"reuse", "modify"}
                 and (d.get("source") or {}).get("kind") == "formal"]
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
