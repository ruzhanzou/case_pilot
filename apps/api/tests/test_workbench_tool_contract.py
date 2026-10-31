"""Bridge metadata declares domain fulfillment, never infers it from prose."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from casepilot_api.workbench_tools import PlanArguments, WorkbenchTools


def test_typed_plan_actions_are_returned_without_claiming_execution(monkeypatch):
    conversation = SimpleNamespace(context={})
    bridge = WorkbenchTools(None, None, conversation, None)
    monkeypatch.setattr(bridge, "authorize", lambda: None)
    result = bridge.plan(
        PlanArguments(steps=["Rewrite selected cases"], plan_actions=["CASE_MODIFY"])
    )
    assert result["plan_actions"] == ["CASE_MODIFY"]
    assert result["executed"] is False
    assert bridge.plan(PlanArguments(steps=["Inspect scope"]))["plan_actions"] == []
    with pytest.raises(ValidationError):
        PlanArguments(steps=["Apply"], plan_actions=["APPLY"])


def test_reads_fulfill_only_query_and_actual_preparation_fulfills_mutation_actions():
    bridge = WorkbenchTools(None, None, None, None)
    specs = {spec.name: spec for spec in bridge.specs()}
    assert specs["prepare_generation"].fulfilled_actions == ("CASE_GENERATE",)
    assert specs["prepare_rewrite"].fulfilled_actions == ("CASE_MODIFY",)
    assert specs["prepare_reuse"].fulfilled_actions == ("CASE_REUSE", "CASE_GENERATE")
    for name in ("query_assets", "query_uploaded_cases", "query_candidates"):
        assert specs[name].fulfilled_actions == ("CASE_QUERY",)
        assert specs[name].effect == "read"
    assert specs["query_collections"].fulfilled_actions == ("COLLECTION_QUERY",)
    assert specs["query_collections"].effect == "read"
    for name in (
        "select_assets",
        "plan_work",
        "preview_uploaded_cases",
    ):
        assert specs[name].fulfilled_actions == ()


def test_agent_selection_schema_excludes_legacy_targets():
    bridge = WorkbenchTools(None, None, None, None)
    schema = next(spec.args_schema for spec in bridge.specs() if spec.name == "select_assets")
    assert "targets" not in schema.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        schema(base_version=0, targets=[{"kind": "case", "candidate_refs": ["legacy"]}])
    assert schema(base_version=0, sources=[{"ref": "candidate:observed", "version": "1"}])


@pytest.mark.parametrize("action", ["create", "rename", "delete"])
def test_collection_plan_actions_match_only_entity_proposal_tools(action):
    intent = "COLLECTION_" + action.upper()
    args = PlanArguments(
        steps=["Prepare collection review"], plan_actions=[intent, "CASE_GENERATE"],
    )
    assert args.plan_actions == [intent, "CASE_GENERATE"]
    specs = {spec.name: spec for spec in WorkbenchTools(None, None, None, None).specs()}
    assert specs[action + "_collection"].fulfilled_actions == (intent,)
    assert specs["query_collections"].fulfilled_actions == ("COLLECTION_QUERY",)
    assert intent not in specs["query_collections"].fulfilled_actions
    assert specs["select_assets"].fulfilled_actions == ()
