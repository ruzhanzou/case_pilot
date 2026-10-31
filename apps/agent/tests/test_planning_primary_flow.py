"""Actual dynamic planning contracts; semantic quality still needs independent review."""

import pytest
from test_parallel_planning import features
from test_planning_quality_flow import point

from casepilot_agent.contracts import FeaturePoint, RequirementAnalysis
from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.planning import build_planning, planned_module


def context():
    return {
        "user_input": "Plan the two supplied business rules and their explicit state interactions",
        "evidence": [
            {
                "source_id": "s",
                "document_id": "d",
                "chunk_id": str(i),
                "label": f"Rule {i}",
                "locator": f"line{i}",
                "excerpt": f"Explicit business rule {i}.",
            }
            for i in (1, 2)
        ],
    }


def run(
    *,
    scenario="Known initial state, action and primary observable result",
    wrong_source=False,
    completion_wrong_owner=False,
    completion_empty_scenario=False,
):
    calls = []

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            data = features(2).model_dump()
            for index, feature in enumerate(data["feature_points"], 1):
                feature["source_refs"] = [{"locator": f"source:{index}", "label": "selection"}]
            return schema.model_validate(data)
        calls.append(payload)
        owners = [f["id"] for f in payload["feature_points"]["feature_points"]]
        value = point("known")
        value.update(
            scenario=scenario,
            primary_feature_id=owners[1],
            feature_point_ids=owners,
            source_refs=[{"locator": "source:1", "label": "selection"}]
            if wrong_source
            else [{"locator": f"source:{i}", "label": "selection"} for i in (1, 2)],
        )
        points, obligations = [value], []
        if completion_wrong_owner or completion_empty_scenario:
            obligations = [
                dict(
                    id="gap",
                    feature_point_ids=[owners[0]],
                    dimension="state",
                    basis="Explicit rule 1 missing branch",
                    point_ids=[],
                )
            ]
            if payload.get("coverage_completion"):
                extra = point("different", "p1")
                extra.update(
                    primary_feature_id=owners[1],
                    feature_point_ids=owners,
                    source_refs=[{"locator": "source:2", "label": "selection"}],
                )
                if completion_empty_scenario:
                    extra["primary_feature_id"] = owners[0]
                    extra["source_refs"] = [{"locator": "source:1", "label": "selection"}]
                    extra["scenario"] = ""
                points.append(extra)
                obligations[0]["point_ids"] = ["p1"]
        for item in points:
            primary = item.pop("primary_feature_id")
            item["primary_binding"] = next(
                binding["id"]
                for binding in payload["primary_bindings"]
                if binding["feature_id"] == primary
            )
        return schema.model_validate({"test_points": points, "coverage_obligations": obligations})

    return build_planning(
        RequirementAnalysis(summary="Two given rules"), context(), complete
    ), calls


@pytest.mark.parametrize("scenario", ["", "   "])
def test_initial_and_completion_schema_require_meaningful_scenario(scenario):
    with pytest.raises(ValueError, match="string_too_short|planning_point_scenario_required"):
        run(scenario=scenario)


def test_explicit_pair_contributes_own_source_separately_from_extra_precondition():
    plan, _ = run(wrong_source=True)
    assert {ref["chunk_id"] for ref in plan["test_points"][0]["source_refs"]} == {"1", "2"}


def test_primary_survives_projection_merge_and_drives_module_not_feature_array_order():
    plan, calls = run()
    point_data = plan["test_points"][0]
    assert point_data["primary_feature_id"] == point_data["feature_point_ids"][0]
    by_name = {f["name"]: f for f in plan["feature_points"]}
    assert point_data["feature_point_ids"][0] == by_name["功能1"]["id"]
    assert {ref["chunk_id"] for ref in point_data["source_refs"]} == {"1", "2"}
    assert planned_module(
        Point.model_validate(point_data),
        [FeaturePoint.model_validate(f) for f in plan["feature_points"]],
    ).endswith("功能1")
    assert len(calls) == 1


def test_completion_cannot_hide_wrong_primary_behind_secondary_owner_overlap():
    with pytest.raises(ValueError, match="planning_coverage_completion_owner_invalid"):
        run(completion_wrong_owner=True)


def test_appended_completion_point_cannot_omit_scenario():
    with pytest.raises(ValueError, match="string_too_short"):
        run(completion_empty_scenario=True)
