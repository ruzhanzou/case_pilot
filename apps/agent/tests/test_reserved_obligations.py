"""Reservations are exact source authority, distinct from permission to use references."""
from copy import deepcopy

import pytest
from test_compact_generation import request
from test_reserved_generation import reservation

from casepilot_agent.output_obligations import (
    append_reserved_source_point,
    apply_reserved_review,
    bind_obligations,
    has_point_review_receipt,
    reserve_required_outputs,
    validate_output_obligations,
)
from casepilot_agent.quantity import OutputQuantity


def prepared():
    plan = request(2).confirmed_plan
    source = reservation(None)["source"]
    plan["approved_source_catalog"] = [{"key": source["key"], "revision": "r1"}]
    quantity = OutputQuantity(required_reuse_source_keys=[source["key"]],
                              output_case_count=2, new_case_count=1)
    reserve_required_outputs(plan, quantity, [source], {source["key"]: ["P-0"]})
    bind_obligations(plan, quantity)
    return plan, source, quantity


def test_reservation_binding_tracks_full_snapshot_and_exact_source_version():
    plan, source, quantity = prepared()
    assert plan["output_obligations"]["source_point_ids"] == {source["key"]: ["P-0"]}
    source["snapshot"]["title"] = "changed outside plan"
    reserved_title = plan["reserved_reuse_outputs"][0]["source"]["snapshot"]["title"]
    assert reserved_title != source["snapshot"]["title"]
    source["revision"] = "r2"
    with pytest.raises(ValueError, match="required_reuse_source_invalid"):
        reserve_required_outputs(plan, quantity, [source], {source["key"]: ["P-0"]})
    plan["reserved_reuse_outputs"][0]["source"]["snapshot"]["title"] = "tamper"
    with pytest.raises(ValueError, match="plan_changed"):
        validate_output_obligations(plan, [])


@pytest.mark.parametrize("choice", ["new", "exclude"])
def test_explicit_review_overrides_reservation_without_reviving_source(choice):
    plan, source, quantity = prepared()
    apply_reserved_review(plan, {"P-0": choice})
    assert plan["reserved_reuse_outputs"] == []
    assert source["key"] in plan["excluded_reuse_source_keys"]
    assert "output_obligations" not in plan
    with pytest.raises(ValueError, match="required_reuse_source_invalid"):
        reserve_required_outputs(plan, quantity, [source], {source["key"]: ["P-0"]})


def test_partial_point_selection_cannot_silently_drop_required_output():
    plan, _, _ = prepared()
    plan["test_points"] = plan["test_points"][1:]
    before = deepcopy(plan)
    with pytest.raises(ValueError, match="reserved_reuse_selection_conflict"):
        apply_reserved_review(plan, {})
    assert plan == before


def test_background_source_does_not_become_reservation():
    plan, source, _ = prepared()
    reserve_required_outputs(plan, OutputQuantity(), [source], {})
    assert plan["reserved_reuse_outputs"] == []


def test_source_backed_draft_is_real_review_point_not_multiple_source_budget_trick():
    plan = request(1).confirmed_plan
    original = deepcopy(plan)
    source = reservation(None)["source"]
    with pytest.raises(ValueError, match="mapping_requires_clarification"):
        append_reserved_source_point(plan, [source, {**source, "key": "asset:b"}])
    assert plan == original
    point_id = append_reserved_source_point(plan, [source])
    assert plan["test_points"][:-1] == original["test_points"]
    assert plan["test_points"][-1]["id"] == point_id
    assert source["snapshot"]["title"] in plan["test_points"][-1]["scenario"]
    assert not has_point_review_receipt(plan)


def test_point_review_requires_exact_receipt_not_draft_or_source_confirmation():
    plan = request(1).confirmed_plan
    assert not has_point_review_receipt(plan)
    plan["point_review_receipt"] = {"brief_id": "b", "version": 1,
                                    "point_ids": ["P-0"], "kind": "source_only"}
    assert not has_point_review_receipt(plan)
    plan["point_review_receipt"]["kind"] = "points"
    assert has_point_review_receipt(plan)
    plan["point_review_receipt"]["point_ids"] = ["foreign"]
    assert not has_point_review_receipt(plan)


def test_source_backed_point_evidence_is_not_an_output_reuse_receipt():
    import json
    from types import SimpleNamespace

    plan = request(1).confirmed_plan
    source = reservation(None)["source"]
    append_reserved_source_point(plan, [source])
    refs = plan["test_points"][-1]["source_refs"]
    assert all(json.loads(ref["excerpt"])["action"] == "reference" for ref in refs)
    bind_obligations(plan, OutputQuantity(output_case_count=1, new_case_count=1))
    validate_output_obligations(plan, [SimpleNamespace(source_refs=refs)])
