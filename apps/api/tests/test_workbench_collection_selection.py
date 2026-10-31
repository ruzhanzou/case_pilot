"""Collection navigation is explicit, reversible, and uses canonical selection CAS."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from test_workbench_bridge_integration import Provider, activate, setup

from casepilot_api import workbench_tools
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, CaseCollection, Conversation, WorkspaceCandidate
from casepilot_api.models import TestCase as CaseRecord
from casepilot_api.schemas import ConversationMessageCreate
from casepilot_api.workbench_tools import CollectionSelectionArguments, NoArguments, WorkbenchTools


async def post(client, path, body):
    response = await client.post("/api/v1" + path, json=body)
    assert response.status_code in {200, 201, 202}, response.text
    return response.json()


async def seed(client, collection, title):
    return await post(
        client,
        f"/collections/{collection}/test-cases",
        {
            "title": title,
            "module": "Auth",
            "priority": "P1",
            "case_type": "functional",
            "preconditions": [],
            "steps": [{"action": "Act", "expected": "Pass"}],
        },
    )


def test_collection_navigation_requires_destination_version_and_selection_policy():
    valid = {"collection_id": str(uuid4()), "base_version": 0, "selection_policy": "clear"}
    for field in valid:
        with pytest.raises(ValidationError):
            CollectionSelectionArguments.model_validate(
                {k: v for k, v in valid.items() if k != field}
            )
    with pytest.raises(ValidationError):
        CollectionSelectionArguments.model_validate({**valid, "approved": True})
    spec = next(
        tool
        for tool in WorkbenchTools(None, None, None, None).specs()
        if tool.name == "select_collection"
    )
    assert spec.effect == "prepare"
    assert spec.fulfilled_actions == ()
    assert not spec.requires_approval


@pytest.mark.asyncio
async def test_confirmed_empty_collection_is_not_selected_until_explicit_tool(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, original, workspace = await setup(client)
        cid = workspace["id"]
        activate(monkeypatch, [("create_collection", {"name": "Empty destination"})])
        turn = await post(
            client,
            f"/conversations/{cid}/messages",
            {"content": "创建 Empty destination，先让我确认", "client_request_id": str(uuid4())},
        )
        proposal = turn["action"]["proposal"]
        destination = await post(
            client,
            f"/workspaces/{cid}/collection-proposals/{proposal['id']}/confirm",
            {"name": proposal["name"], "collection_id": None},
        )
        before = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert before["collection_id"] == original["id"]

        def select_observed(messages):
            observation = next(
                m
                for m in messages
                if m.get("role") == "developer"
                and "authorized_workspace_observation" in m.get("content", "")
            )
            data = json.loads(observation["content"].split("\n", 1)[1])
            assert data["collection_id"] == original["id"]
            assert data["confirmed_collection"]["id"] == destination["id"]
            assert "Empty destination" not in observation["content"]
            return {
                "collection_id": data["confirmed_collection"]["id"],
                "base_version": data["selection_version"],
                "selection_policy": "clear",
            }

        provider = activate(monkeypatch, [("select_collection", select_observed)])
        selected = await post(
            client,
            f"/conversations/{cid}/messages",
            {
                "content": "切换到 Empty destination，清空选择，不创建或修改用例",
                "client_request_id": str(uuid4()),
            },
        )
        after = (await client.get(f"/api/v1/conversations/{cid}")).json()
        canonical = after["context"]["workbench_selection"]
        assert after["collection_id"] == canonical["active_collection_id"] == destination["id"]
        assert canonical["items"] == [] and canonical["version"] == 1
        receipts = selected["assistant_message"]["metadata"]["workbench_agent"]["receipts"]
        assert any(r["tool"] == "select_collection" and r["effect"] == "prepare" for r in receipts)
        output = next(
            json.loads(m["output"])
            for m in provider.observations[-1]
            if m.get("type") == "function_call_output"
        )
        assert output["collection"] == {"id": destination["id"], "name": "Empty destination"}
        assert output["formal_changes_applied"] is False
        assert (
            await client.get(f"/api/v1/collections/{destination['id']}/test-cases")
        ).json() == []


@pytest.mark.asyncio
async def test_preserve_mixed_sources_stale_cas_foreign_and_deleted_identity(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user, original, workspace = await setup(client)
        space = user["spaces"][0]["id"]
        destination = await post(client, f"/spaces/{space}/collections", {"name": "Empty B"})
        other = await post(client, f"/spaces/{space}/collections", {"name": "Sources C"})
        cases = [await seed(client, original["id"], "A"), await seed(client, other["id"], "C")]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as outsider:
            _, foreign, _ = await setup(outsider)
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(workspace["id"]))
            account = db.get(Account, conversation.account_id)
            candidate = WorkspaceCandidate(
                conversation_id=conversation.id,
                ref="private-candidate",
                version=1,
                snapshot=cases[0],
                status="candidate",
                included=False,
                position=0,
                created_by=account.id,
            )
            db.add(candidate)
            db.flush()
            from casepilot_api.workbench_selection import SelectionUpdate, update_selection

            sources = [
                {"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}
                for case in cases
            ] + [{"ref": "candidate:private-candidate", "version": "1"}]
            first = update_selection(
                db, account, conversation, SelectionUpdate(base_version=0, sources=sources)
            )
            bridge = WorkbenchTools(
                db, account, conversation, ConversationMessageCreate(content="切集合，保留所有选择")
            )
            result = bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=destination["id"], base_version=1, selection_policy="preserve"
                )
            )
            assert result["selection"]["items"] == first["items"]
            assert str(conversation.collection_id) == destination["id"]
            assert result["selection"]["active_collection_id"] == destination["id"]
            assert result["selection"]["version"] == 2
            stale = bridge.select_collection(CollectionSelectionArguments(
                collection_id=original["id"], base_version=1, selection_policy="clear"))
            assert stale["error_code"] == "selection_version_conflict"
            with pytest.raises(HTTPException) as error:
                bridge.select_collection(CollectionSelectionArguments(
                    collection_id=foreign["id"], base_version=2, selection_policy="clear"))
            assert error.value.status_code == 404
            assert str(conversation.collection_id) == destination["id"]
            assert conversation.context["workbench_selection"]["items"] == first["items"]
            conversation.context = {
                **conversation.context,
                "workbench_collection_proposal": {
                    "status": "confirmed",
                    "action": "create",
                    "result": {"id": foreign["id"], "name": "Private foreign name"},
                },
            }
            assert bridge.context(NoArguments())["confirmed_collection"] is None
            conversation.context = {
                **conversation.context,
                "workbench_collection_proposal": {
                    "status": "confirmed",
                    "action": "create",
                    "result": {"id": destination["id"]},
                },
            }
            assert bridge.context(NoArguments())["confirmed_collection"]["name"] == "Empty B"
            db.get(CaseCollection, UUID(destination["id"])).deleted_at = datetime.now(UTC)
            db.flush()
            assert bridge.confirmed_collection_receipt() is None
            with pytest.raises(HTTPException) as error:
                bridge.select_collection(
                    CollectionSelectionArguments(
                        collection_id=destination["id"], base_version=2, selection_policy="clear"
                    )
                )
            assert error.value.status_code == 404
            assert conversation.context["workbench_selection"]["items"] == first["items"]
            for case in cases:
                assert (
                    str(db.get(CaseRecord, UUID(case["id"])).current_revision_id)
                    == (case["current_revision_id"])
                )
            assert candidate.version == 1
            db.rollback()


@pytest.mark.asyncio
async def test_switching_collection_keeps_old_preview_but_cannot_approve_it(monkeypatch):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user, original, workspace = await setup(client)
        case = await seed(client, original["id"], "Protected original")
        destination = await post(
            client, f"/spaces/{user['spaces'][0]['id']}/collections", {"name": "Empty destination"}
        )
        cid = workspace["id"]
        selected = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
            },
        )
        assert selected.status_code == 200, selected.text
        activate(monkeypatch, [("prepare_rewrite", {})])
        rewrite = await post(
            client,
            f"/conversations/{cid}/messages",
            {
                "content": "把选中用例优先级改为P2",
                "selection_version": 1,
                "client_request_id": str(uuid4()),
            },
        )
        operation = rewrite["operation_plan"]["operations"][0]
        assert rewrite["action"].get("job_id"), rewrite
        await asyncio.to_thread(tasks.rewrite_test_cases_batch.run, rewrite["action"]["job_id"])
        before_read = (await client.get(f"/api/v1/conversations/{cid}")).json()
        operation = next(
            row for row in before_read["operation_history"] if row["id"] == operation["id"]
        )
        change_id = operation["related_change_set_id"]
        preview = (await client.get(f"/api/v1/case-change-sets/{change_id}")).json()
        assert preview["status"] == "ready"

        class ReadProvider(Provider):
            def complete(self, messages, tools, instructions):
                turn = super().complete(messages, tools, instructions)
                if turn.final:
                    turn.final.kind = "answer"
                    turn.final.message = "已读取集合；尚未批准或应用预览。"
                return turn

        reader = ReadProvider([
            ("plan_work", {"steps": ["Read collection choices only"],
                           "plan_actions": ["COLLECTION_QUERY"]}),
            ("get_workspace_context", {}), ("query_collections", {})])
        monkeypatch.setattr(workbench_tools, "make_provider", lambda *a: reader)
        reply = await post(
            client,
            f"/conversations/{cid}/messages",
            {
                "content": "先不确认改写。现在有哪些集合可选？只查看，不改变预览。",
                "client_request_id": str(uuid4()),
            },
        )
        activity = reply["assistant_message"]["metadata"]["workbench_agent"]
        assert activity["final"]["kind"] == "answer"
        assert activity["final"]["effect"] == "read"
        assert {receipt["tool"] for receipt in activity["receipts"]} == {
            "plan_work",
            "get_workspace_context",
            "query_collections",
        }
        after_read = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert after_read["operation_history"] == before_read["operation_history"]
        assert (
            after_read["context"]["workbench_selection"]
            == (before_read["context"]["workbench_selection"])
        )
        assert after_read["collection_id"] == original["id"]
        activate(
            monkeypatch,
            [
                (
                    "select_collection",
                    {
                        "collection_id": destination["id"],
                        "base_version": 1,
                        "selection_policy": "clear",
                    },
                )
            ],
        )
        await post(
            client,
            f"/conversations/{cid}/messages",
            {
                "content": "切换到 Empty destination并清空选择，原改写预览先不应用",
                "client_request_id": str(uuid4()),
            },
        )
        switched = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert switched["collection_id"] == destination["id"]
        assert switched["context"]["workbench_selection"]["items"] == []
        rejected = await client.post(
            f"/api/v1/case-change-sets/{change_id}/apply",
            json={},
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"] == "workbench_selection_changed"
        after = (await client.get(f"/api/v1/conversations/{cid}")).json()
        old = next(item for item in after["operation_history"] if item["id"] == operation["id"])
        assert old["status"] == operation["status"]
        assert old["related_job_id"] == rewrite["action"]["job_id"]
        assert old["related_change_set_id"] == change_id
        assert (await client.get(f"/api/v1/case-change-sets/{change_id}")).json() == preview
        current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert current["current_revision_id"] == case["current_revision_id"]
        assert (
            await client.get(f"/api/v1/collections/{destination['id']}/test-cases")
        ).json() == []
