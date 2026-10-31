"""Server-owned reuse reservations and exact point-review receipts."""
from copy import deepcopy


def _preserve_quantity_identities(plan, prior):
    """Retained numeric metadata cannot self-declare itself a legacy artifact.

    Removing an entire contract/sample or point is an ordinary draft edit, not
    a certification claim. Historical metadata without identities stays intact.
    """
    obligations, linked, obligation_ids, point_ids = {}, {}, {}, {}
    sampling = {}

    def contracts(value):
        for batch in (value.get("coverage_review") or {}).get("batches", []):
            for obligation in batch.get("obligations", []):
                contract = obligation.get("boundary_contract")
                if isinstance(contract, dict):
                    yield obligation, contract

    def obligation_key(obligation):
        return obligation.get("id"), tuple(sorted(obligation.get("feature_point_ids", [])))

    def sampling_keys(obligation, identity):
        return [
            ("owner", obligation_key(obligation), identity),
            ("obligation", obligation.get("id"), identity),
            *(("point", (point_id, obligation.get("id")), identity)
              for point_id in obligation.get("point_ids", [])),
        ]

    def sampling_pair(contract):
        return contract.get("sampling_step"), contract.get("sampling_literal", "")

    def remember(mapping, key, identity):
        if isinstance(identity, str) and identity:
            mapping.setdefault(key, set()).add(identity)

    def require(mapping, key, identity):
        expected = mapping.get(key)
        if expected and identity not in expected:
            raise ValueError("planning_boundary_quantity_identity_changed")

    for obligation, contract in contracts(prior):
        identity = contract.get("quantity_axis_id")
        if isinstance(identity, str) and identity:
            for key in sampling_keys(obligation, identity):
                sampling.setdefault(key, set()).add(sampling_pair(contract))
        remember(obligations, obligation_key(obligation), identity)
        remember(obligation_ids, obligation.get("id"), identity)
        for point_id in obligation.get("point_ids", []):
            remember(linked, (point_id, obligation.get("id")), identity)
            remember(point_ids, point_id, identity)
    for point in prior.get("test_points", []):
        for sample in point.get("boundary_samples") or []:
            remember(linked, (point["id"], sample.get("obligation_id")),
                     sample.get("quantity_axis_id"))
            remember(point_ids, point["id"], sample.get("quantity_axis_id"))
    for obligation, contract in contracts(plan):
        identity = contract.get("quantity_axis_id")
        for key in sampling_keys(obligation, identity):
            expected_sampling = sampling.get(key)
            if expected_sampling and sampling_pair(contract) not in expected_sampling:
                raise ValueError("planning_boundary_quantity_identity_changed")
        require(obligations, obligation_key(obligation), identity)
        require(obligation_ids, obligation.get("id"), identity)
        for point_id in obligation.get("point_ids", []):
            require(linked, (point_id, obligation.get("id")), identity)
    for point in plan.get("test_points", []):
        for sample in point.get("boundary_samples") or []:
            require(linked, (point["id"], sample.get("obligation_id")),
                    sample.get("quantity_axis_id"))
            require(point_ids, point["id"], sample.get("quantity_axis_id"))


def edited_plan(incoming, previous, choices):
    from casepilot_agent.output_obligations import apply_reserved_review

    plan = deepcopy(incoming or {})
    prior = previous or {}
    _preserve_quantity_identities(plan, prior)
    plan.pop("point_review_receipt", None)
    if plan.get("pending_planning_clarification") != prior.get("pending_planning_clarification"):
        raise ValueError("planning_clarification_authority_changed")
    if prior.get("pending_planning_clarification") and (
            plan.get("coverage_review") != prior.get("coverage_review")):
        raise ValueError("planning_clarification_authority_changed")
    if plan.get("reserved_reuse_outputs", []) != prior.get("reserved_reuse_outputs", []):
        raise ValueError("reserved_reuse_authority_changed")
    if plan.get("pending_reserved_outputs") != prior.get("pending_reserved_outputs"):
        raise ValueError("reserved_reuse_authority_changed")
    if (prior.get("reserved_reuse_outputs") or prior.get("excluded_reuse_source_keys")
            or prior.get("pending_reserved_outputs")):
        for field in ("approved_source_catalog", "output_obligations",
                      "excluded_reuse_source_keys"):
            if plan.get(field) != prior.get(field):
                raise ValueError("reserved_reuse_authority_changed")
        old_points = {p["id"]: p for p in prior.get("test_points", [])}
        points = {p["id"]: p for p in plan.get("test_points", [])}
        for reservation in prior.get("reserved_reuse_outputs", []):
            if any(choices.get(pid) in {"new", "exclude"} for pid in reservation["point_ids"]):
                continue
            if any(points.get(pid) != old_points.get(pid) for pid in reservation["point_ids"]):
                raise ValueError("reserved_reuse_selection_conflict")
    apply_reserved_review(plan, choices)
    return plan


def stamp_point_review(plan, brief, *, kind):
    ids = [point["id"] for point in plan.get("test_points", [])]
    if not ids:
        plan.pop("point_review_receipt", None)
        return
    plan["point_review_receipt"] = {
        "brief_id": str(brief.id), "version": brief.version,
        "point_ids": ids, "kind": kind,
    }


def inherit_point_review(plan, brief):
    """Only DB-confirmed exact receipts carry authority into a later worker."""
    result = deepcopy(plan or {})
    receipt = result.pop("point_review_receipt", None)
    if (brief.status != "confirmed" or brief.confirmed_by is None or brief.confirmed_at is None
            or not isinstance(receipt, dict) or receipt.get("brief_id") != str(brief.id)
            or type(receipt.get("version")) is not int
            or receipt.get("version") != brief.version
            or receipt.get("kind") not in {"points", "asset_points"}):
        return result
    ids = receipt.get("point_ids")
    points = result.get("test_points", [])
    allowed = {point["id"] for point in points}
    if (not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids)
            or len(ids) != len(set(ids)) or not set(ids) <= allowed):
        return result
    result["test_points"] = [point for point in points if point["id"] in ids]
    features = {ref for point in result["test_points"] for ref in point["feature_point_ids"]}
    result["feature_points"] = [f for f in result.get("feature_points", []) if f["id"] in features]
    if result.get("reuse"):
        result["reuse"] = {**result["reuse"], "decisions": [
            row for row in result["reuse"].get("decisions", []) if row["point_id"] in ids
        ], "user_choices": {key: value for key, value in
                            result["reuse"].get("user_choices", {}).items() if key in ids}}
    result["selection_context"] = {
        "original_test_point_ids": sorted(allowed), "selected_test_point_ids": list(ids),
    }
    result["point_review_receipt"] = receipt
    return result
