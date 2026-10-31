"""Same-turn proposal handoff; real ASGI/DB, scripted model, no live calls."""
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup
from test_workbench_reuse_journey import create_case

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.generation_strategy import interpret_generation_choice
from casepilot_api.main import app
from casepilot_api.models import (
    CaseCollection,
    CollectionCaseMembership,
    ConversationOperation,
    WorkbenchRun,
)
from casepilot_api.models import TestCase as CaseRecord


def reuse_semantics(monkeypatch):
    choice = interpret_generation_choice("策略：select_and_generate。测试对象：Account system",
                                         SimpleNamespace(agent_provider="mock"))
    choice.test_object = "Account system"
    monkeypatch.setattr(conversations, "interpret_generation_choice", lambda *a, **kw: choice)
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")


@pytest.mark.asyncio
@pytest.mark.parametrize("domain_fails", [False, True, "unexpected_gate"])
@pytest.mark.parametrize("verify_after", [False, True])
async def test_same_run_create_draft_hands_off_to_only_real_reuse_gate(
    monkeypatch, domain_fails, verify_after
):
    reuse_semantics(monkeypatch)
    name = "Exact reuse destination"
    actions = ["COLLECTION_CREATE", "CASE_REUSE", *(["CASE_QUERY"] if verify_after else [])]
    provider = activate(monkeypatch, [("create_collection", {"name": name}),
                                      ("prepare_reuse", {"strategy": "select_and_generate"})],
                        fixture_plan={"steps": list(actions), "plan_actions": actions})
    original_send = conversations._send_message
    if domain_fails:
        def fail_after_domain(*args, **kwargs):
            result = original_send(*args, **kwargs)
            if kwargs.get("_workbench_dispatch"):
                if domain_fails == "unexpected_gate":
                    result.action = {"type": "not_a_destination_gate"}
                    return result
                raise HTTPException(409, "synthetic_domain_failure")
            return result
        monkeypatch.setattr(conversations, "_send_message", fail_after_domain)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, origin, _ = await setup(client)
        source = await create_case(client, origin["id"], "Original unchanged source")
        workspace = (await client.post("/api/v1/conversations", json={
            "space_id": account["spaces"][0]["id"],
        })).json()
        cid = workspace["id"]
        content = (f"原样复用已有主流程并补充验证码异常，组成新集合{name}。"
                   "测试对象：Account system。")
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": content, "source_collection_ids": [origin["id"]],
            "client_request_id": str(uuid4()),
        })
        assert response.status_code in {200, 202}, response.text
        body = response.json()
        outputs = [json.loads(item["output"]) for message in provider.observations
                   for item in message if item.get("type") == "function_call_output"]
        old_id = next(item["proposal"]["id"] for item in outputs if item.get("proposal"))
        current = (await client.get(f"/api/v1/conversations/{cid}")).json()
        old = current["context"]["workbench_collection_proposal"]
        with get_session_factory()() as db:
            assert not list(db.scalars(select(CaseCollection).where(
                CaseCollection.space_id == UUID(account["spaces"][0]["id"]),
                CaseCollection.name == name)))
            assert db.get(CaseRecord, UUID(source["id"])).current_revision_id == UUID(
                source["current_revision_id"])
        if domain_fails:
            assert old["id"] == old_id and old["status"] == "pending"
            with get_session_factory()() as db:
                assert not list(db.scalars(select(ConversationOperation).where(
                    ConversationOperation.conversation_id == UUID(cid))))
            return
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
            assert [step["action"] for step in run.plan["steps"]] == [
                "CASE_REUSE", *(["CASE_QUERY"] if verify_after else [])]
            assert run.cursor == 0
            assert run.status == "waiting_approval"
        assert body["action"]["type"] == "collection_confirmation"
        assert old["id"] == old_id and old["status"] == "superseded"
        assert not body["assistant_message"]["metadata"].get("workbench_collection_proposal")
        operation = body["operation_plan"]["operations"][0]
        assert old["superseded_by_operation_id"] == operation["id"]
        assert operation["payload"]["superseded_collection_proposal"]["id"] == old_id
        assert body["user_message"]["content"] == content
        rejected = await client.post(
            f"/api/v1/workspaces/{cid}/collection-proposals/{old_id}/confirm",
            json={"name": name, "collection_id": None},
        )
        assert rejected.status_code == 409 and rejected.json()["detail"] == (
            "collection_proposal_not_pending")
        endpoint = f"/api/v1/conversation-operations/{operation['id']}/confirm-collection"
        rejected = await client.post(endpoint, json={"collection_id": origin["id"]})
        assert rejected.status_code == 422
        approved = await client.post(endpoint, json={"create_collection_name": name})
        assert approved.status_code == 202, approved.text
        replay = await client.post(endpoint, json={"create_collection_name": name})
        assert replay.status_code == 202
        assert replay.json()["action"] == approved.json()["action"]
        with get_session_factory()() as db:
            destinations = list(db.scalars(select(CaseCollection).where(
                CaseCollection.space_id == UUID(account["spaces"][0]["id"]),
                CaseCollection.name == name)))
            assert len(destinations) == 1
            memberships = list(db.scalars(select(CollectionCaseMembership.collection_id).where(
                CollectionCaseMembership.test_case_id == UUID(source["id"]))))
            assert memberships == [UUID(origin["id"])]
            assert db.get(CaseRecord, UUID(source["id"])).current_revision_id == UUID(
                source["current_revision_id"])


@pytest.mark.parametrize("ownership,action,status,bound", [
    ("previous_run", "create", "pending", False),
    ("this_run", "rename", "pending", False),
    ("this_run", "create", "confirmed", False),
    ("this_run", "create", "pending", True),
    ("replaced", "create", "pending", False),
])
def test_handoff_never_cancels_unrelated_or_confirmed_proposals(
    monkeypatch, ownership, action, status, bound
):
    from copy import deepcopy

    from casepilot_api.workbench_tools import WorkbenchTools

    proposal = {"id": "draft-one", "action": action, "status": status}
    conversation = SimpleNamespace(collection_id=uuid4() if bound else None,
                                   context={"workbench_collection_proposal": deepcopy(proposal)})
    run_id, root_message_id = uuid4(), uuid4()
    run = SimpleNamespace(id=run_id, root_message_id=root_message_id, epoch=1, cursor=0,
        plan={"id": f"{run_id}:1", "root_message_id": str(root_message_id), "epoch": 1,
              "steps": [{"action": "CASE_REUSE", "description": "Reuse",
                         "depends_on": [], "status": "pending"}]})
    bridge = WorkbenchTools(None, None, conversation, None, durable_run=run)
    bridge.collection_proposal = None if ownership == "previous_run" else deepcopy(proposal)
    if ownership == "replaced":
        conversation.context["workbench_collection_proposal"]["id"] = "another-draft"
    before = deepcopy(conversation.context)
    monkeypatch.setattr(bridge, "current_payload", lambda: None)
    monkeypatch.setattr(conversations, "_send_message", lambda *a, **kw: pytest.fail("dispatched"))
    result = bridge.prepare("CASE_GENERATE", strategy="select_and_generate")
    assert result["error_code"] in {"one_proposal_per_turn", "collection_proposal_requires_review"}
    assert conversation.context == before
