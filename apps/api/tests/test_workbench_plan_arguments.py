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
