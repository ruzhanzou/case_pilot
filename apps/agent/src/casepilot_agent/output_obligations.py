"""Typed output obligations over a reviewed plan, not authority inferred from references."""

import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256


def plan_fingerprint(plan):
    reuse = plan.get("reuse", {})
    semantic = {
        key: plan.get(key)
        for key in (
            "test_points",
            "feature_points",
            "approved_source_catalog",
            "excluded_reuse_source_keys",
            "reserved_reuse_outputs",
        )
    }
    semantic["reuse"] = {
        "decisions": reuse.get("decisions", []),
        "user_choices": reuse.get("user_choices", {}),
        "strategy": reuse.get("strategy"),
    }
    return sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def approved_catalog(plan):
    catalog = plan.get("approved_source_catalog")
    if catalog is None:  # Compatible legacy plans already carry exact approved decisions.
        catalog = [
            d["source"] for d in plan.get("reuse", {}).get("decisions", []) if d.get("source")
        ]
    excluded = set(plan.get("excluded_reuse_source_keys", []))
    points = {point["id"] for point in plan.get("test_points", [])}
    choices = plan.get("reuse", {}).get("user_choices", {})
    for decision in plan.get("reuse", {}).get("decisions", []):
        if choices.get(decision.get("point_id")) in {"new", "exclude"} and decision.get("source"):
            excluded.add(decision["source"]["key"])
    for reservation in plan.get("reserved_reuse_outputs", []):
        ids = reservation["point_ids"]
        if not set(ids) <= points or any(choices.get(point) in {"new", "exclude"} for point in ids):
            excluded.add(reservation["source"]["key"])
    for key, ids in plan.get("output_obligations", {}).get("source_point_ids", {}).items():
        if not any(
            point in points and choices.get(point) not in {"new", "exclude"} for point in ids
        ):
            excluded.add(key)
    return [item for item in catalog if item["key"] not in excluded]


def missing_required(plan, keys):
    if not keys:
        return []
    point_ids = {point["id"] for point in plan.get("test_points", [])}
    represented = {
        d["source"]["key"]
        for d in plan.get("reuse", {}).get("decisions", [])
        if d.get("action") == "reuse" and d.get("source") and d["point_id"] in point_ids
    }
    represented.update(
        item["source"]["key"] for item in plan.get("reserved_reuse_outputs", [])
        if item.get("action") == "reuse" and item.get("point_ids")
        and set(item["point_ids"]) <= point_ids
    )
    return sorted(set(keys) - represented)


def ensure_required_coverage(plan, quantity, *, reviewed, repair):
    """Only a fresh, unreviewed plan gets one bounded correction opportunity."""
    keys = quantity.required_reuse_source_keys
    allowed = {item["key"] for item in approved_catalog(plan)}
    if len(keys) != len(set(keys)) or not set(keys) <= allowed:
        raise ValueError("required_reuse_source_invalid")
    missing = missing_required(plan, keys)
    if missing and not reviewed:
        plan = repair(deepcopy(plan), missing)
        missing = missing_required(plan, keys)
    if missing:
        raise ValueError("required_reuse_coverage_missing_replan_required")
    return plan


def bind_obligations(plan, quantity):
    keys = quantity.required_reuse_source_keys
    allowed = {item["key"] for item in approved_catalog(plan)}
    if len(keys) != len(set(keys)) or not set(keys) <= allowed:
        raise ValueError("required_reuse_source_invalid")
    if missing_required(plan, keys):
        raise ValueError("required_reuse_coverage_missing_replan_required")
    output, new = quantity.output_case_count, quantity.new_case_count
    if output is not None and output < len(keys):
        raise ValueError("output_obligation_count_conflict")
    if output is not None and new is not None and output < new + len(keys):
        raise ValueError("output_obligation_count_conflict")
    plan["output_obligations"] = {
        "schema_version": 1,
        "required_reuse_source_keys": list(keys),
        "output_case_count": output,
        "new_case_count": new,
        "plan_fingerprint": plan_fingerprint(plan),
        "source_point_ids": {
            key: sorted(
                {point for item in plan.get("reserved_reuse_outputs", [])
                 if item["source"]["key"] == key for point in item["point_ids"]}
                or {d["point_id"] for d in plan.get("reuse", {}).get("decisions", [])
                    if d.get("action") == "reuse" and d.get("source", {}).get("key") == key}
            )
            for key in keys
        },
    }
    return plan["output_obligations"]


def validate_output_obligations(plan, cases):
    obligation = plan.get("output_obligations")
    if not obligation:
        return
    if obligation["plan_fingerprint"] != plan_fingerprint(plan):
        raise ValueError("output_obligation_plan_changed")
    reused, new_count = Counter(), 0
    for case in cases:
        references = (
            case.source_refs if hasattr(case, "source_refs") else case.get("source_refs", [])
        )
        source_actions = set()
        for reference in references:
            excerpt = (
                reference.excerpt if hasattr(reference, "excerpt") else reference.get("excerpt", "")
            )
            try:
                value = json.loads(excerpt)
            except (ValueError, TypeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("source_key")
                and value.get("action") in {"reuse", "modify"}
            ):
                source_actions.add((value["source_key"], value["action"]))
        if not source_actions:
            new_count += 1
        for key, action in source_actions:
            if action == "reuse":
                reused[key] += 1
    if any(reused[key] != 1 for key in obligation["required_reuse_source_keys"]):
        raise ValueError("required_reuse_output_missing_or_duplicate")
    if (
        obligation["output_case_count"] is not None
        and len(cases) != obligation["output_case_count"]
    ):
        raise ValueError("output_obligation_count_mismatch")
    if obligation["new_case_count"] is not None and new_count != obligation["new_case_count"]:
        raise ValueError("output_obligation_new_count_mismatch")


def reserve_required_outputs(plan, quantity, sources, point_ids_by_source):
    """Bind explicit required outputs to exact confirmed sources and real review points."""
    allowed = {item["key"]: item for item in approved_catalog(plan)}
    by_key = {item["key"]: item for item in sources}
    keys = quantity.required_reuse_source_keys
    if len(keys) != len(set(keys)) or not set(keys) <= allowed.keys() & by_key.keys():
        raise ValueError("required_reuse_source_invalid")
    points = {point["id"] for point in plan.get("test_points", [])}
    choices = plan.get("reuse", {}).get("user_choices", {})
    reservations = []
    for key in keys:
        source = by_key[key]
        if any(source.get(field) != allowed[key].get(field) for field in
               ("revision", "document_version", "document_checksum")):
            raise ValueError("required_reuse_source_invalid")
        ids = point_ids_by_source.get(key, [])
        if not ids or len(ids) != len(set(ids)) or not set(ids) <= points:
            raise ValueError("required_reuse_coverage_missing_replan_required")
        if any(choices.get(point) in {"new", "exclude"} for point in ids):
            raise ValueError("required_reuse_source_invalid")
        reservations.append({"action": "reuse", "source": deepcopy(source),
                             "point_ids": list(ids),
                             "point_snapshots": {p["id"]: deepcopy(p)
                                                 for p in plan["test_points"] if p["id"] in ids},
                             "reason": "用户明确要求原样复用的已确认来源"})
    plan["reserved_reuse_outputs"] = reservations
    return reservations


def append_reserved_source_point(plan, sources):
    """A real source-backed draft point, presented for review, never an execution-only slot."""
    from casepilot_agent.contracts import FeaturePoint, TestPoint
    from casepilot_agent.reuse import reuse_ref

    if len(sources) != 1:
        raise ValueError("reserved_reuse_mapping_requires_clarification")
    identity = [{"key": s["key"], "revision": s.get("revision"),
                 "document_version": s.get("document_version"),
                 "document_checksum": s.get("document_checksum")} for s in sources]
    digest = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    feature_id, point_id = f"FP-{digest}", f"TP-{digest}"
    snapshots = [s["snapshot"] for s in sources]
    description = "\n".join(json.dumps({"title": s["title"],
        "preconditions": s.get("preconditions", []), "steps": s["steps"]},
        ensure_ascii=False) for s in snapshots)
    refs = [reuse_ref({"source": s, "action": "reuse", "reason": "明确保留原样输出"})
            for s in sources]
    # A planning citation is evidence, not proof that a generated output reused it.
    refs = [ref.model_copy(update={"excerpt": json.dumps(
        {**json.loads(ref.excerpt), "action": "reference"}, ensure_ascii=False
    )}) for ref in refs]
    feature = FeaturePoint(id=feature_id, name="已确认来源的原样复用覆盖",
        description=description, module=snapshots[0].get("module", ""),
        requirement_refs=list(dict.fromkeys(ref for f in plan.get("feature_points", [])
                                           for ref in f.get("requirement_refs", []))),
        source_refs=refs)
    point = TestPoint(id=point_id, title="保留已明确要求原样复用的来源用例",
        scenario=description, objective="按所列来源的原始前提、步骤与预期分别保留候选输出",
        category="functional", priority=snapshots[0].get("priority", "P1"),
        priority_reason="当前用户明确要求保留的已确认来源", feature_point_ids=[feature_id],
        source_refs=refs)
    if any(p["id"] == point_id for p in plan.get("test_points", [])):
        raise ValueError("reserved_source_point_identity_conflict")
    plan.setdefault("feature_points", []).append(feature.model_dump(mode="json"))
    plan.setdefault("test_points", []).append(point.model_dump(mode="json"))
    return point_id


def apply_reserved_review(plan, choices):
    """Apply an actual human choice; dropping an unrevoked required point is a conflict."""
    current_ids = {point["id"] for point in plan.get("test_points", [])}
    retained, removed = [], set()
    for item in plan.get("reserved_reuse_outputs", []):
        ids = item["point_ids"]
        if any(choices.get(point) in {"new", "exclude"} for point in ids):
            removed.add(item["source"]["key"])
        elif not set(ids) <= current_ids:
            raise ValueError("reserved_reuse_selection_conflict")
        else:
            retained.append(item)
    if removed:
        plan["reserved_reuse_outputs"] = retained
        plan["excluded_reuse_source_keys"] = sorted(
            set(plan.get("excluded_reuse_source_keys", [])) | removed
        )
        for point in [*plan.get("test_points", []), *plan.get("feature_points", [])]:
            for reference in point.get("source_refs", []):
                try:
                    provenance = json.loads(reference.get("excerpt", ""))
                except (ValueError, TypeError):
                    continue
                if isinstance(provenance, dict) and provenance.get("source_key") in removed:
                    reference["excerpt"] = json.dumps(
                        {**provenance, "action": "reference"}, ensure_ascii=False
                    )
        # The authenticated human superseded the previous output scope/budget.
        plan.pop("output_obligations", None)


def has_point_review_receipt(plan):
    """Only an explicit server-issued point approval proves these exact point IDs were reviewed."""
    receipt = plan.get("point_review_receipt")
    if not isinstance(receipt, dict) or receipt.get("kind") not in {"points", "asset_points"}:
        return False
    ids = receipt.get("point_ids")
    return bool(
        receipt.get("brief_id") and type(receipt.get("version")) is int
        and receipt["version"] > 0 and isinstance(ids, list) and ids
        and len(ids) == len(set(ids))
        and set(ids) == {point["id"] for point in plan.get("test_points", [])}
    )
