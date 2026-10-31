"""Pair selections are explicit; cached outputs remain tied to the complete catalog."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_parallel_planning import features
from test_planning_quality_flow import point

from casepilot_agent.contracts import RequirementAnalysis
from casepilot_agent.planning import build_planning
from casepilot_agent.store import JobStore


def capture(*, reverse_features=False, reverse_sources=False, mutation=None):
    saved = {}
    evidence = [
        {
            "source_id": str(i),
            "document_id": "d",
            "chunk_id": str(i),
            "label": f"rule{i}",
            "locator": str(i),
            "excerpt": f"Explicit rule {i}",
        }
        for i in (1, 2)
    ]
    if reverse_sources:
        evidence.reverse()

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            data = features(2).model_dump()
            for i, feature in enumerate(data["feature_points"], 1):
                slot = next(
                    item["slot"] for item in payload["source_catalog"] if item["locator"] == str(i)
                )
                feature["source_refs"] = [{"label": "choice", "locator": slot}]
            if reverse_features:
                data["feature_points"].reverse()
            return schema.model_validate(data)
        saved.update(schema=schema, payload=deepcopy(payload))
        props = schema.model_json_schema()["$defs"]["BatchTestPoint"]["properties"]
        assert "primary_feature_id" not in props
        assert props["primary_binding"]["enum"] == [b["id"] for b in payload["primary_bindings"]]
        values = []
        for i, binding in enumerate(payload["primary_bindings"]):
            value = point(i, f"p{i}")
            value.pop("source_refs")
            value.pop("feature_point_ids")
            value["primary_binding"] = binding["id"]
            values.append(value)
        if mutation:
            mutation(values, payload)
        result = schema.model_validate({"test_points": values})
        saved["cached"] = result.model_dump(mode="json")
        assert schema.model_validate(saved["cached"]).model_dump(mode="json") == saved["cached"]
        return result

    plan = build_planning(
        RequirementAnalysis(summary="Rules"), {"evidence": evidence}, complete, target_count=2
    )
    return plan, saved


def test_pair_only_schema_contributes_exact_owner_source_and_roundtrips_internal_cache():
    plan, saved = capture()
    assert all(p["primary_feature_id"] in p["feature_point_ids"] for p in plan["test_points"])
    assert all("primary_binding" not in p for p in plan["test_points"])
    assert all("primary_binding" in p for p in saved["cached"]["test_points"])
    assert all(len(p["source_refs"]) == 1 for p in plan["test_points"])


@pytest.mark.parametrize("kind", ["unknown_pair", "foreign_secondary", "hidden_conflict"])
def test_invalid_pair_or_hidden_marker_or_secondary_never_gets_repaired_silently(kind):
    def mutate(values, payload):
        if kind == "unknown_pair":
            values[0]["primary_binding"] = "primary:foreign"
        elif kind == "foreign_secondary":
            values[0]["source_refs"] = [{"locator": "source:foreign", "label": "untrusted"}]
        else:
            values[0]["primary_feature_id"] = payload["primary_bindings"][1]["feature_id"]

    with pytest.raises(ValueError, match="literal_error|planning_primary_binding_conflict"):
        capture(mutation=mutate)


def test_different_owner_at_same_pair_index_rejects_old_derived_marker():
    _, old = capture()
    _, reordered = capture(reverse_features=True)
    with pytest.raises(ValueError, match="planning_primary_binding_conflict"):
        reordered["schema"].model_validate(old["cached"])


def test_real_store_input_fingerprint_changes_when_same_owner_source_catalog_reorders():
    _, original = capture()
    _, reordered = capture(reverse_sources=True)
    observed = []

    def execute(statement):
        observed.append(statement.compile().params["input_hash_1"])
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))

    store = object.__new__(JobStore)
    connection = SimpleNamespace(execute=execute)
    job_id = uuid4()
    for payload in (original["payload"], deepcopy(original["payload"]), reordered["payload"]):
        assert (
            store.load_completed_stage(connection, job_id, "test_point.generated", payload) is None
        )
    assert observed[0] == observed[1] and observed[0] != observed[2]
