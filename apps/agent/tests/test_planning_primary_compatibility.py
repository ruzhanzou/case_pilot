"""Persisted primary ownership is additive; historical snapshots remain unchanged."""

import hashlib
import json
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from test_parallel_planning import features
from test_planning_quality_flow import point

from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.contracts import TestPointPlan as Plan
from casepilot_agent.planning import merge_planning, planned_module


def setup():
    owners = features(3).feature_points
    raw = point("same")
    raw["feature_point_ids"] = [owners[1].id, owners[0].id, owners[2].id]
    return owners, Point.model_validate(raw)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def test_legacy_missing_primary_retains_old_serialized_fingerprint_id_and_module():
    owners, point_model = setup()
    raw = point_model.model_dump(mode="json")
    before = deepcopy(raw)
    assert "primary_feature_id" not in raw
    # Feature array order, not owners order, is the pre-marker module contract.
    assert planned_module(point_model, owners).endswith(owners[0].name)
    serialized = Plan(test_points=[point_model]).model_dump(mode="json")["test_points"][0]
    assert serialized == raw and fingerprint(serialized) == fingerprint(before)
    assert json.loads(point_model.model_dump_json()) == raw
    assert Point.model_validate({**raw, "primary_feature_id": None}).model_dump(mode="json") == raw
    merged = merge_planning(owners, [point_model], {}, 1)
    old_key = "/".join(
        sorted(f"FP-{uuid5(NAMESPACE_URL, f'{f.module}/{f.name}').hex[:16]}" for f in owners)
        + [point_model.scenario, point_model.title]
    )
    assert merged["test_points"][0]["id"] == f"TP-{uuid5(NAMESPACE_URL, old_key).hex[:16]}"
    assert "primary_feature_id" not in merged["test_points"][0]
    assert raw == before


def test_new_same_owners_different_primary_never_merge_and_reverse_is_stable():
    owners, original = setup()
    first = original.model_copy(update={"id": "one", "primary_feature_id": owners[0].id})
    second = original.model_copy(update={"id": "two", "primary_feature_id": owners[1].id})
    a = merge_planning(owners, [first, second], {}, 1)["test_points"]
    b = merge_planning(owners, [second, first], {}, 1)["test_points"]
    assert len(a) == len(b) == 2
    assert {p["primary_feature_id"]: p["id"] for p in a} == {
        p["primary_feature_id"]: p["id"] for p in b
    }
    assert all(p["primary_feature_id"] in p["feature_point_ids"] for p in a)


def test_secondary_reordering_does_not_change_new_identity_or_module():
    owners, original = setup()
    first = original.model_copy(update={"id": "one", "primary_feature_id": owners[1].id})
    second = first.model_copy(
        update={"id": "two", "feature_point_ids": list(reversed(first.feature_point_ids))}
    )
    assert planned_module(first, owners) == planned_module(second, owners)
    assert planned_module(first, owners).endswith(owners[1].name)
    assert len(merge_planning(owners, [first, second], {}, 1)["test_points"]) == 1


def test_single_owner_marker_retains_existing_stable_identity():
    owners, original = setup()
    legacy = original.model_copy(update={"feature_point_ids": [owners[0].id]})
    marked = legacy.model_copy(update={"primary_feature_id": owners[0].id})
    assert (
        merge_planning(owners, [legacy], {}, 1)["test_points"][0]["id"]
        == (merge_planning(owners, [marked], {}, 1)["test_points"][0]["id"])
    )
