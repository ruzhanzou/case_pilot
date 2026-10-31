"""Offline scripting convenience is explicit and never changes production planning."""
import json

from test_workbench_bridge_integration import Provider


def test_fixture_injects_known_single_goal_without_mutating_call():
    arguments = {}
    provider = Provider([("prepare_generation", arguments)])
    call = provider.complete([], [], "").calls[0]
    assert json.loads(call.arguments)["plan"]["plan_actions"] == ["CASE_GENERATE"]
    assert arguments == {}


def test_fixture_missing_plan_safety_test_can_explicitly_opt_out():
    provider = Provider([("prepare_generation", {})], inject_plan=False)
    assert json.loads(provider.complete([], [], "").calls[0].arguments) == {}


def test_fixture_preserves_explicit_full_goal_and_existing_plan_tool():
    plan = {"steps": ["Create", "Reuse", "Verify"],
            "plan_actions": ["COLLECTION_CREATE", "CASE_REUSE", "CASE_QUERY"]}
    provider = Provider([("create_collection", {"name": "Destination"})], fixture_plan=plan)
    assert json.loads(provider.complete([], [], "").calls[0].arguments)["plan"] == plan
    provider = Provider([("plan_work", plan), ("prepare_reuse", {"strategy": "select"})])
    provider.complete([], [], "")
    assert "plan" not in json.loads(provider.complete([], [], "").calls[0].arguments)


def test_fixture_continuation_keeps_existing_full_server_plan():
    provider = Provider([("prepare_rewrite", {})])
    messages = [{"role": "developer", "content":
                 'Durable server plan: {"steps": ["rewrite", "verify"], "cursor": 0}'}]
    arguments = json.loads(provider.complete(messages, [], "").calls[0].arguments)
    assert "plan" not in arguments
