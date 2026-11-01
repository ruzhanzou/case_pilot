"""A model plan cannot silently repeat/reassign descriptions to other actions."""
import pytest
from pydantic import ValidationError

from casepilot_api.workbench_tools import PlanArguments


@pytest.mark.parametrize("steps,actions", [
    (["Read"], ["CASE_QUERY", "CASE_REUSE"]),
    (["Read", "Reuse"], ["CASE_QUERY"]),
])
def test_mismatched_plan_is_rejected_before_persistence(steps, actions):
    with pytest.raises(ValidationError, match="workbench_plan_step_count_mismatch"):
        PlanArguments(steps=steps, plan_actions=actions)


def test_compound_plan_and_read_only_plan_keep_one_to_one_mapping():
    for actions in [["CASE_QUERY"], ["CASE_QUERY", "CASE_REUSE", "CASE_QUERY"]]:
        descriptions = [f"Independent goal {i}" for i in range(len(actions))]
        plan = PlanArguments(steps=descriptions, plan_actions=actions)
        assert list(zip(plan.steps, plan.plan_actions, strict=True)) == list(
            zip(descriptions, actions, strict=True))


def test_nonexecuting_legacy_description_plan_remains_supported():
    assert PlanArguments(steps=["Explain available methods"]).plan_actions == []


def test_actual_sdk_tool_schemas_expose_runtime_cardinality_for_inline_and_standalone():
    from casepilot_api.workbench_tools import WorkbenchTools

    specs = WorkbenchTools.__new__(WorkbenchTools).specs()
    for name in ["plan_work", "prepare_rewrite", "prepare_reuse", "prepare_generation"]:
        schema = next(spec.schema()["parameters"] for spec in specs if spec.name == name)
        plan = schema if name == "plan_work" else schema["$defs"]["PlanArguments"]
        branches = plan["anyOf"]
        assert branches[0] == {"properties": {"plan_actions": {"maxItems": 0}}}
        assert len(branches) == 7
        for count, branch in enumerate(branches[1:], 1):
            assert branch["required"] == ["plan_actions"]
            assert branch["properties"]["steps"] == {"minItems": count, "maxItems": count}
            assert branch["properties"]["plan_actions"] == branch["properties"]["steps"]
        assert plan["properties"]["steps"]["maxItems"] == 6
        assert plan["properties"]["plan_actions"]["maxItems"] == 6
