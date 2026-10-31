"""Fake control model, real API/database and mock-provider domain workers. No live calls."""

import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from casepilot_api import conversations, workbench_tools
from casepilot_api.main import app
from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolCall

# These are explicit goals of the supplied offline script, not production intent
# inference. Bare-preparation rejection tests use their own provider instead.
SCRIPTED_DOMAIN_ACTIONS = {
    "prepare_generation": "CASE_GENERATE", "prepare_rewrite": "CASE_MODIFY",
    "prepare_delete": "CASE_DELETE", "prepare_review": "CASE_REVIEW",
    "prepare_dedup": "CASE_DEDUP", "prepare_coverage": "COVERAGE_ANALYZE",
    "answer_knowledge": "KNOWLEDGE_QA", "prepare_reuse": "CASE_REUSE",
    "create_collection": "COLLECTION_CREATE", "rename_collection": "COLLECTION_RENAME",
    "delete_collection": "COLLECTION_DELETE",
}


class Provider:
    def __init__(self, calls, *, inject_plan=True, fixture_plan=None):
        self.calls = calls
        self.observations = []
        actions = list(dict.fromkeys(SCRIPTED_DOMAIN_ACTIONS[name] for name, _ in calls
                                     if name in SCRIPTED_DOMAIN_ACTIONS))
        self.fixture_plan = (fixture_plan or {"steps": list(actions), "plan_actions": actions}
                             if inject_plan and actions
                             and not any(name == "plan_work" for name, _ in calls) else None)

    def complete(self, messages, tools, instructions):
        self.observations.append(list(messages))
        index = len(self.observations) - 1
        if index < len(self.calls):
            name, arguments = self.calls[index]
            if callable(arguments):
                arguments = arguments(messages)
            existing_continuation = any(
                item.get("role") == "developer" and isinstance(item.get("content"), str)
                and "Durable server plan:" in item["content"] for item in messages
            )
            if (self.fixture_plan and not existing_continuation and name in SCRIPTED_DOMAIN_ACTIONS
                    and isinstance(arguments, dict) and "plan" not in arguments):
                arguments = {**arguments, "plan": self.fixture_plan}
            return ModelTurn(calls=[ToolCall(str(index + 1), name, json.dumps(arguments))])
        outputs = [
            json.loads(item["output"])
            for item in messages
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        receipts = [item["_receipt"] for item in outputs if item.get("_receipt")]
        receipt = receipts[-1]
        return ModelTurn(
            final=FinalAnswer(
                kind="action",
                message="请按预览确认。",
                effect=receipt["effect"],
                receipt_ids=[receipt["id"]],
            )
        )


async def setup(client):
    account = (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"bridge-{uuid4().hex}@casepilot.test",
                "display_name": "Bridge",
                "password": "CasePilot123!",
            },
        )
    ).json()
    collection = (
        await client.post(
            f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
            json={"name": "Bridge collection"},
        )
    ).json()
    conversation = (
        await client.post("/api/v1/conversations", json={"collection_id": collection["id"]})
    ).json()
    return account, collection, conversation


def activate(monkeypatch, calls, *, inject_plan=True, fixture_plan=None):
    monkeypatch.setattr(conversations.settings, "workbench_agent_enabled", True)
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **kw: None)
    provider = Provider(calls, inject_plan=inject_plan, fixture_plan=fixture_plan)
    monkeypatch.setattr(workbench_tools, "make_provider", lambda *a: provider)
    return provider


@pytest.mark.asyncio
async def test_generation_rewrite_approval_apply_cancel_and_replay(monkeypatch):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    provider = activate(monkeypatch, [("get_workspace_context", {}), ("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, conversation = await setup(client)
        cid = conversation["id"]
        url = f"/api/v1/conversations/{cid}/messages"
        request = {"content": "为手机号验证码登录生成测试用例", "client_request_id": str(uuid4())}
        turn = await client.post(url, json=request)
        assert turn.status_code == 202, turn.text
        replay = await client.post(url, json=request)
        assert replay.json() == turn.json()
        assert len(provider.observations) == 3
        await asyncio.to_thread(tasks.draft_test_brief.run, turn.json()["action"]["job_id"])
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        brief = state["test_briefs"][-1]
        confirmed = await client.post(
            f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={"version": brief["version"]}
        )
        assert confirmed.status_code == 202, confirmed.text
        await asyncio.to_thread(tasks.generate_test_cases.run, confirmed.json()["action"]["job_id"])
        adopted = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={})
        assert adopted.status_code == 200, adopted.text
        case = adopted.json()[0]
        selected = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "action": "replace",
                "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
            },
        )
        assert selected.status_code == 200, selected.text
        provider = activate(monkeypatch, [("get_workspace_context", {}), ("prepare_rewrite", {})])
        rewrite = await client.post(
            url,
            json={
                "content": "把选中用例优先级改为P2",
                "selection_version": 1,
                "client_request_id": str(uuid4()),
            },
        )
        assert rewrite.status_code == 202, rewrite.text
        body = rewrite.json()
        assert body["action"].get("job_id"), body
        assert body["assistant_message"]["metadata"]["workbench_agent"]["receipts"]
        operation_id = body["operation_plan"]["operations"][0]["id"]
        await asyncio.to_thread(tasks.rewrite_test_cases_batch.run, body["action"]["job_id"])
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        operation = next(item for item in state["operation_history"] if item["id"] == operation_id)
        change_id = operation["related_change_set_id"]
        preview = (await client.get(f"/api/v1/case-change-sets/{change_id}")).json()
        assert preview["status"] == "ready", preview
        assert preview["items"][0]["proposed_snapshot"]["priority"] == "P2", preview
        before = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert before["current_revision_id"] == case["current_revision_id"]
        applied = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json={})
        assert applied.status_code == 200, applied.text
        after = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert after["priority"] == "P2"
        assert after["current_revision_id"] != before["current_revision_id"]
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        canonical = state["context"]["workbench_selection"]
        assert canonical["items"][0]["version"] == after["current_revision_id"]
        activate(monkeypatch, [("prepare_rewrite", {})])
        cancelled_turn = await client.post(
            url,
            json={
                "content": "把选中用例优先级改为P1",
                "selection_version": canonical["version"],
                "client_request_id": str(uuid4()),
            },
        )
        assert cancelled_turn.status_code == 202, cancelled_turn.text
        cancelled = await client.post(
            f"/api/v1/generation-jobs/{cancelled_turn.json()['action']['job_id']}/cancel"
        )
        assert cancelled.status_code == 200, cancelled.text
        final = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert final["current_revision_id"] == after["current_revision_id"]


@pytest.mark.asyncio
async def test_collection_creation_is_exact_human_approval_only(monkeypatch):
    activate(monkeypatch, [("create_collection", {"name": "Requested collection"})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, conversation = await setup(client)
        cid, space = conversation["id"], account["spaces"][0]["id"]
        turn = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "创建集合 Requested collection", "client_request_id": str(uuid4())},
        )
        assert turn.status_code == 202, turn.text
        proposal = turn.json()["action"]["proposal"]
        collections = (await client.get(f"/api/v1/spaces/{space}/collections")).json()
        assert not any(item["name"] == "Requested collection" for item in collections)
        url = f"/api/v1/workspaces/{cid}/collection-proposals/{proposal['id']}/confirm"
        wrong = await client.post(url, json={"name": "Other"})
        assert wrong.status_code == 409
        confirmed = await client.post(url, json={"name": proposal["name"], "collection_id": None})
        assert confirmed.status_code == 200, confirmed.text
        duplicate = await client.post(url, json={"name": proposal["name"], "collection_id": None})
        assert duplicate.json() == confirmed.json()
        collections = (await client.get(f"/api/v1/spaces/{space}/collections")).json()
        assert sum(item["name"] == "Requested collection" for item in collections) == 1


@pytest.mark.asyncio
async def test_same_turn_selection_refresh_and_explicit_old_target_conflict(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, conversation = await setup(client)
        cases = []
        for title in ["Original", "Replacement"]:
            response = await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": title,
                    "priority": "P1",
                    "steps": [{"action": "Run", "expected": "Pass"}],
                },
            )
            assert response.status_code == 201, response.text
            cases.append(response.json())
        old, new = cases
        cid = conversation["id"]
        selected = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "sources": [{"ref": f"asset:{old['id']}", "version": old["current_revision_id"]}],
            },
        )
        assert selected.status_code == 200, selected.text
        provider = activate(
            monkeypatch,
            [
                ("query_assets", {}),
                (
                    "select_assets",
                    {
                        "base_version": 1,
                        "sources": [
                            {"ref": f"asset:{new['id']}", "version": new["current_revision_id"]}
                        ],
                    },
                ),
                ("prepare_rewrite", {}),
            ],
        )
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "改选 Replacement 并将它的优先级改为P2",
                "selection_version": 1,
                "target_case_ids": [old["id"]],
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert len(provider.observations) == 4
        assert body["action"].get("job_id"), body
        operation = body["operation_plan"]["operations"][0]
        assert operation["target"]["case_ids"] == [new["id"]]
        await client.post(f"/api/v1/generation-jobs/{body['action']['job_id']}/cancel")
        provider = activate(monkeypatch, [("prepare_rewrite", {})])
        stale = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "优先级改为P0",
                "target_case_ids": [old["id"]],
                "client_request_id": str(uuid4()),
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"] == "workbench_selection_target_conflict"
        assert not provider.observations
