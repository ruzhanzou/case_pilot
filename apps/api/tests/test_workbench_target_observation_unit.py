import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from test_workbench_selection import change
from test_workbench_selection import workspace as selection_workspace

from casepilot_api.schemas import ConversationMessageCreate
from casepilot_api.workbench_tools import WorkbenchTools


@pytest.fixture
def workspace(monkeypatch):
    return selection_workspace.__wrapped__(monkeypatch)


def bridge(workspace, payload):
    db, account, conversation, _ = workspace
    tools = WorkbenchTools(db, account, conversation, payload)
    tools.authorize = lambda: None
    tools.confirmed_collection_receipt = lambda: None
    return tools


@pytest.mark.parametrize("canonical", [False, True])
def test_observation_exact_request_count_does_not_persist_selection(workspace, canonical):
    db, account, conversation, versions = workspace
    ref = next(iter(versions))
    if canonical:
        change(workspace, refs=[ref])
    payload = ConversationMessageCreate(content="只改这条", target_case_ids=[ref[6:]],
        targets=[{"kind": "case", "case_ids": [ref[6:]]}], target_scope="selected",
        selection_version=1 if canonical else None)
    tools = bridge(workspace, payload)
    result = json.loads(tools.initial_observation()["content"].split("\n", 1)[1])
    assert result["selected_count"] == 1
    assert result["target_origin"] == ("canonical" if canonical else "explicit_request")
    assert result["canonical_selected_count"] == (1 if canonical else None)
    assert bool(conversation.context.get("workbench_selection")) is canonical
    assert tools.context(None)["selected_case_ids"] == [ref[6:]]
    assert ref not in str(result)


def test_foreign_explicit_target_is_not_advertised(workspace):
    tools = bridge(workspace, ConversationMessageCreate(
        content="只改这条", target_case_ids=[uuid4()]))
    with pytest.raises(HTTPException) as error:
        tools.initial_observation()
    assert error.value.detail == "source_not_found"


def test_stale_canonical_version_never_becomes_explicit_fallback(workspace):
    ref = next(iter(workspace[3]))
    change(workspace, refs=[ref])
    tools = bridge(workspace, ConversationMessageCreate(content="只改这条",
        target_case_ids=[ref[6:]], selection_version=0))
    with pytest.raises(HTTPException) as error:
        tools.initial_observation()
    assert error.value.detail == "workbench_selection_version_conflict"


def test_no_target_and_symbolic_scope_are_not_exact_selection(workspace):
    tools = bridge(workspace, ConversationMessageCreate(content="你好"))
    data = json.loads(tools.initial_observation()["content"].split("\n", 1)[1])
    assert data["selected_count"] == 0 and data["target_origin"] == "none"
    tools.payload = ConversationMessageCreate(content="改登录模块", targets=[{
        "kind": "module", "module": "登录"}])
    data = json.loads(tools.initial_observation()["content"].split("\n", 1)[1])
    assert data["selected_count"] is None and data["target_origin"] == "unresolved_request"
