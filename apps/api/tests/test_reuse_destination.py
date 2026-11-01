"""Exact output handoff from an already-bound workbench, with real DB guards."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup
from test_workbench_collection_handoff import reuse_semantics
from test_workbench_reuse_journey import create_case

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseCollection, Conversation, ConversationOperation, GenerationJob


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["new", "current", "existing"])
async def test_bound_reuse_destination_needs_exact_human_confirmation(monkeypatch, kind):
    reuse_semantics(monkeypatch)
    monkeypatch.setattr(
        conversations,
        "select_case_scope",
        lambda *a, **kw: SimpleNamespace(
            ids=[],
            reference="explicit",
            requested_count=None,
            referenced_case_keys=[],
            ambiguous=False,
            clarification=None,
        ),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, origin, workspace = await setup(client)
        await create_case(client, origin["id"], "Preserve original source")
        other = (
            await client.post(
                f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
                json={
                    "space_id": account["spaces"][0]["id"],
                    "name": "Observed destination",
                },
            )
        ).json()
        cid = workspace["id"]
        destination = {"kind": kind}
        if kind == "new":
            destination["name"] = "Explicit new output"
            choice = {"create_collection_name": destination["name"]}
        else:
            target = origin["id"] if kind == "current" else other["id"]
            if kind == "existing":
                destination["collection_id"] = target
            choice = {"collection_id": target}
        activate(
            monkeypatch,
            [
                (
                    "prepare_reuse",
                    {
                        "strategy": "select_and_generate",
                        "destination": destination,
                    },
                )
            ],
            fixture_plan={"steps": ["Reuse and fill gaps"], "plan_actions": ["CASE_REUSE"]},
        )
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": (
                    "原样复用已有用例并补测试点，测试对象：Account system。供我确认输出集合。"
                ),
                "source_collection_ids": [origin["id"]],
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code in {200, 202}, response.text
        body = response.json()
        assert body["action"]["type"] == "collection_confirmation", body
        opid = body["operation_plan"]["operations"][0]["id"]
        with get_session_factory()() as db:
            assert db.get(Conversation, UUID(cid)).collection_id == UUID(origin["id"])
            assert not list(
                db.scalars(
                    select(GenerationJob).where(
                        GenerationJob.input_payload["conversation_id"].astext == cid
                    )
                )
            )
        endpoint = f"/api/v1/conversation-operations/{opid}/confirm-collection"
        wrong = await client.post(endpoint, json={"create_collection_name": "Unrequested output"})
        assert wrong.status_code == 409, wrong.text
        approved = await client.post(endpoint, json=choice)
        assert approved.status_code == 202, approved.text
        replay = await client.post(endpoint, json=choice)
        assert replay.status_code == 202, replay.text
        assert replay.json()["action"] == approved.json()["action"]
        with get_session_factory()() as db:
            operation = db.get(ConversationOperation, UUID(opid))
            binding = operation.payload["reference_binding"]
            assert origin["id"] in {row["collection_id"] for row in binding["source_collections"]}
            assert operation.payload["reuse_destination_approved"] == str(
                db.get(Conversation, UUID(cid)).collection_id
            )
            if kind == "new":
                assert (
                    len(
                        list(
                            db.scalars(
                                select(CaseCollection).where(
                                    CaseCollection.space_id == UUID(account["spaces"][0]["id"]),
                                    CaseCollection.name == destination["name"],
                                )
                            )
                        )
                    )
                    == 1
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source_unbind", "source_reindex", "ui_switch", "namesake"])
async def test_destination_confirmation_rejects_stale_authority_atomically(monkeypatch, change):
    from test_collection_references import source

    reuse_semantics(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, origin, workspace = await setup(client)
        sid, _ = source(account)
        path = f"/api/v1/collections/{origin['id']}/references"
        assert (
            await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        ).status_code == 200
        name = "Explicit pending destination"
        activate(
            monkeypatch,
            [("prepare_reuse", {"destination": {"kind": "new", "name": name}})],
            fixture_plan={"steps": ["Reuse"], "plan_actions": ["CASE_REUSE"]},
        )
        cid = workspace["id"]
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "原样复用并补测试点到明确新集合，测试对象：Account system。",
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 202, response.text
        opid = response.json()["operation_plan"]["operations"][0]["id"]
        if change == "source_unbind":
            assert (
                await client.put(path, json={"base_version": 1, "source_ids": []})
            ).status_code == 200
        elif change == "source_reindex":
            assert (
                await client.post(f"/api/v1/knowledge-sources/{sid}/reindex")
            ).status_code == 202
        elif change == "ui_switch":
            other = (
                await client.post(
                    f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
                    json={"name": "Other user destination"},
                )
            ).json()
            assert (
                await client.patch(
                    f"/api/v1/workspaces/{cid}/selection",
                    json={
                        "base_version": 0,
                        "active_collection_id": other["id"],
                        "action": "clear",
                    },
                )
            ).status_code == 200
        else:
            assert (
                await client.post(
                    f"/api/v1/spaces/{account['spaces'][0]['id']}/collections", json={"name": name}
                )
            ).status_code == 201
        response = await client.post(
            f"/api/v1/conversation-operations/{opid}/confirm-collection",
            json={"create_collection_name": name},
        )
        assert response.status_code == 409, response.text
        with get_session_factory()() as db:
            assert not db.get(ConversationOperation, UUID(opid)).payload.get(
                "reuse_destination_approved"
            )
            outputs = list(
                db.scalars(
                    select(CaseCollection).where(
                        CaseCollection.space_id == UUID(account["spaces"][0]["id"]),
                        CaseCollection.name == name,
                    )
                )
            )
            assert len(outputs) == (1 if change == "namesake" else 0)
            assert not list(
                db.scalars(
                    select(GenerationJob).where(
                        GenerationJob.input_payload["conversation_id"].astext == cid
                    )
                )
            )


@pytest.mark.asyncio
async def test_output_handoff_keeps_origin_binding_through_saved_brief(monkeypatch):
    from fastapi import HTTPException
    from test_collection_references import source

    from casepilot_api.collection_references import (
        assert_reference_binding,
        capture_brief_reference_binding,
    )
    from casepilot_api.models import Account

    reuse_semantics(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, origin, ws = await setup(client)
        sid, _ = source(account)
        path = f"/api/v1/collections/{origin['id']}/references"
        assert (
            await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        ).status_code == 200
        activate(
            monkeypatch,
            [("prepare_reuse", {"destination": {"kind": "new", "name": "Output"}})],
            fixture_plan={"steps": ["Reuse"], "plan_actions": ["CASE_REUSE"]},
        )
        response = await client.post(
            f"/api/v1/conversations/{ws['id']}/messages",
            json={
                "content": "复用并补测试点，测试对象：Account system。",
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 202, response.text
        opid = response.json()["operation_plan"]["operations"][0]["id"]
        response = await client.post(
            f"/api/v1/conversation-operations/{opid}/confirm-collection",
            json={"create_collection_name": "Output"},
        )
        assert response.status_code == 202, response.text
        with get_session_factory()() as db:
            op = db.get(ConversationOperation, UUID(opid))
            conv = db.get(Conversation, UUID(ws["id"]))
            assert conv.collection_id != UUID(origin["id"])
            binding = capture_brief_reference_binding(
                db, conv, {}, inherited=op.payload["reference_binding"]
            )
            assert binding["source_collections"][0]["collection_id"] == origin["id"]
            assert_reference_binding(db, db.get(Account, UUID(account["id"])), conv, binding)
            db.rollback()
        assert (
            await client.put(path, json={"base_version": 1, "source_ids": []})
        ).status_code == 200
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(ws["id"]))
            with pytest.raises(HTTPException) as error:
                assert_reference_binding(db, db.get(Account, UUID(account["id"])), conv, binding)
            assert error.value.detail == "reference_context_changed"


def test_ambiguous_destination_rejection_precedes_mutation_and_planning(monkeypatch):
    from fastapi import HTTPException

    from casepilot_api import reuse_destination
    from casepilot_api.schemas import ReuseDestination
    from casepilot_api.workbench_tools import WorkbenchTools

    conversation = SimpleNamespace(context={}, collection_id=uuid4())
    bridge = WorkbenchTools(None, None, conversation, None)
    monkeypatch.setattr(bridge, "current_payload", lambda: None)
    monkeypatch.setattr(
        bridge, "require_goal_plan", lambda *a: pytest.fail("planned before validation")
    )
    monkeypatch.setattr(bridge, "mark_mutating_intent", lambda: pytest.fail("invalidated old run"))

    def ambiguous(*args):
        raise HTTPException(409, "reuse_destination_name_ambiguous")

    monkeypatch.setattr(reuse_destination, "prepare_destination", ambiguous)
    result = bridge.prepare(
        "CASE_GENERATE",
        strategy="select_and_generate",
        destination=ReuseDestination(kind="new", name="Ambiguous"),
    )
    assert result["error_code"] == "reuse_destination_name_ambiguous"
    assert conversation.context == {}
