"""Deterministic provider; real API, persisted goals, receipt and approval guards."""

import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import setup

from casepilot_api import conversations, workbench_tools
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseCollection, WorkbenchRun
from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolCall


class GoalProvider:
    def __init__(self, steps):
        self.steps = steps
        self.observations = []

    def complete(self, messages, tools, instructions):
        self.observations.append(list(messages))
        index = len(self.observations) - 1
        step = self.steps[index] if index < len(self.steps) else "read"
        if isinstance(step, tuple):
            name, args = step
            return ModelTurn(calls=[ToolCall(str(index), name, json.dumps(args))])
        if isinstance(step, FinalAnswer):
            return ModelTurn(final=step)
        outputs = [
            json.loads(x["output"]) for x in messages if x.get("type") == "function_call_output"
        ]
        receipt = next(
            x["_receipt"]
            for x in reversed(outputs)
            if x.get("_receipt") and x["_receipt"]["effect"] == step
        )
        return ModelTurn(
            final=FinalAnswer(
                kind="answer" if step == "read" else "action",
                message="Synthetic visible result",
                effect=step,
                receipt_ids=[receipt["id"]],
            )
        )


def activate(monkeypatch, steps):
    provider = GoalProvider(steps)
    monkeypatch.setattr(conversations.settings, "workbench_agent_enabled", True)
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **kw: None)
    monkeypatch.setattr(workbench_tools, "make_provider", lambda *a: provider)
    return provider


async def send(client, cid, content="请软删除当前集合，仅准备精确提案等待确认，不删除用例"):
    response = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": content, "client_request_id": str(uuid4())},
    )
    assert response.status_code == 202
    return response.json()


def latest(cid):
    with get_session_factory()() as db:
        run = db.scalar(
            select(WorkbenchRun)
            .where(WorkbenchRun.conversation_id == UUID(cid))
            .order_by(WorkbenchRun.created_at.desc())
        )
        return {
            "status": run.status,
            "plan": run.plan,
            "cursor": run.cursor,
            "checkpoint": run.checkpoint,
        }


@pytest.mark.asyncio
async def test_unplanned_read_reproduction(monkeypatch):
    provider = activate(monkeypatch, [("query_collections", {"search": ""}), "read"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        body = await send(client, workspace["id"])
        state = latest(workspace["id"])
        assert state["status"] != "completed"
        assert state["checkpoint"]["completion"]["completion_code"] == "goal_unverified"
        assert not state["plan"].get("steps")
        assert len(provider.observations) == 3
        assert (
            body["assistant_message"]["metadata"]["workbench_agent"]["final"]["kind"] == "clarify"
        )
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("late_plan", [False, True])
async def test_query_only_plan_completes_from_real_receipt(monkeypatch, late_plan):
    query = ("query_collections", {"search": ""})
    plan = ("plan_work", {"steps": ["Read collections"], "plan_actions": ["COLLECTION_QUERY"]})
    provider = activate(
        monkeypatch, [query, "read", plan, "read"] if late_plan else [plan, query, "read"]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        body = await send(client, workspace["id"], "仅查询集合")
        state = latest(workspace["id"])
        assert state["status"] == "completed" and state["cursor"] == 1
        assert len(state["plan"]["steps"][0]["receipt_ids"]) == 1
        assert state["checkpoint"]["completion"]["completion_code"] == "goal_satisfied"
        assert len(provider.observations) == (4 if late_plan else 3)
        assert not body["action"].get("proposal")


@pytest.mark.asyncio
async def test_corrected_full_goal_stops_at_pending_delete_then_reject_new_goal(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        provider = activate(
            monkeypatch,
            [
                ("query_collections", {"search": ""}),
                "read",
                (
                    "plan_work",
                    {
                        "steps": ["Inspect target", "Prepare exact deletion"],
                        "plan_actions": ["COLLECTION_QUERY", "COLLECTION_DELETE"],
                    },
                ),
                ("delete_collection", {"collection_id": collection["id"]}),
                "prepare",
            ],
        )
        body = await send(client, cid)
        proposal = body["action"]["proposal"]
        assert proposal["status"] == "pending" and proposal["collection_id"] == collection["id"]
        state = latest(cid)
        assert state["status"] == "waiting_approval" and state["cursor"] == 1
        assert state["plan"]["steps"][0]["receipt_ids"]
        assert not state["plan"]["steps"][1].get("receipt_ids")
        assert len(provider.observations) == 5
        rejected = await client.post(
            f"/api/v1/workspaces/{cid}/collection-proposals/{proposal['id']}/reject", json={}
        )
        assert rejected.json() == {"status": "rejected"}
        activate(monkeypatch, [("query_collections", {"search": ""}), "read"])
        await send(client, cid)
        fresh = latest(cid)
        assert not fresh["plan"].get("steps") and fresh["status"] != "completed"
        assert fresh["checkpoint"]["completion"]["completion_code"] == "goal_unverified"
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "steps",
    [
        [FinalAnswer(kind="answer", message="普通对话")],
        [FinalAnswer(kind="clarify", message="请明确目标")],
        [("get_workspace_context", {}), "read"],
        [("read_attachment_evidence", {}), "read"],
        [
            ("query_collections", {"search": ""}),
            ("select_assets", {"base_version": 0, "action": "clear", "sources": []}),
            "prepare",
        ],
    ],
)
async def test_no_goal_context_and_select_only_do_not_invent_mutations(monkeypatch, steps):
    provider = activate(monkeypatch, steps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        body = await send(client, workspace["id"], "仅查看或选择，不准备写入")
        state = latest(workspace["id"])
        assert not state["plan"].get("steps")
        assert not body["action"].get("proposal") and not body["action"].get("job_id")
        assert len(provider.observations) == len(steps)
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None


@pytest.mark.asyncio
async def test_exhausted_existing_budget_does_not_add_goal_correction(monkeypatch):
    provider = activate(monkeypatch, [("query_collections", {"search": ""}), "read"])
    monkeypatch.setattr(conversations.settings, "workbench_agent_max_turns", 2)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        await send(client, workspace["id"])
        assert len(provider.observations) == 2
        assert (
            latest(workspace["id"])["checkpoint"]["completion"]["completion_code"]
            == "goal_unverified"
        )


@pytest.mark.asyncio
async def test_corrected_query_side_question_restores_old_goal_without_copying_it(monkeypatch):
    from test_workbench_side_questions import snapshot, waiting_review

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, old_run, _, _ = await waiting_review(client, monkeypatch)
        before = snapshot(old_run)
        provider = activate(
            monkeypatch,
            [
                ("query_collections", {"search": ""}),
                "read",
                (
                    "plan_work",
                    {"steps": ["Read collections only"], "plan_actions": ["COLLECTION_QUERY"]},
                ),
                "read",
            ],
        )
        await send(client, cid, "只是旁问：有哪些集合？不要推进之前的任务。")
        assert snapshot(old_run) == before
        assert len(provider.observations) == 4
        fresh = latest(cid)
        assert fresh["status"] == "completed" and fresh["cursor"] == 1
        assert [s["action"] for s in fresh["plan"]["steps"]] == ["COLLECTION_QUERY"]


@pytest.mark.asyncio
async def test_old_query_receipt_cannot_complete_new_query_goal(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        plan = ("plan_work", {"steps": ["Read"], "plan_actions": ["COLLECTION_QUERY"]})
        activate(monkeypatch, [plan, ("query_collections", {"search": ""}), "read"])
        await send(client, workspace["id"], "查询集合")
        assert latest(workspace["id"])["status"] == "completed"
        activate(monkeypatch, [plan, FinalAnswer(kind="clarify", message="缺少本轮查询结果")])
        await send(client, workspace["id"], "重新查询集合")
        state = latest(workspace["id"])
        assert state["status"] != "completed" and state["cursor"] == 0
        assert not state["plan"]["steps"][0].get("receipt_ids")


@pytest.mark.asyncio
async def test_planned_query_segment_keeps_existing_continuation_and_pending_goal(monkeypatch):
    from test_workbench_continuation_runtime import event_id

    activate(
        monkeypatch,
        [
            (
                "plan_work",
                {
                    "steps": ["Inspect", "Prepare deletion"],
                    "plan_actions": ["COLLECTION_QUERY", "COLLECTION_DELETE"],
                },
            ),
            ("query_collections", {"search": ""}),
            "read",
        ],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        body = await send(client, workspace["id"])
        state = latest(workspace["id"])
        assert state["status"] == "active" and state["cursor"] == 1
        assert state["checkpoint"]["completion"]["completion_code"] == "goal_pending"
        progress = body["assistant_message"]["metadata"]["workbench_agent"]["durable_run"]
        assert event_id(UUID(progress["id"]), "next_step")
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None


@pytest.mark.asyncio
async def test_uploaded_preview_only_remains_legal_without_invented_write_goal(
    monkeypatch, tmp_path
):
    from test_workbench_bridge_integration import activate as activate_fixture
    from test_workbench_uploaded_bridge import observed_sources, seed_sheet

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        doc = seed_sheet(tmp_path, account, workspace)
        activate_fixture(
            monkeypatch,
            [
                ("query_uploaded_cases", {}),
                (
                    "preview_uploaded_cases",
                    lambda m: {"sources": observed_sources(m, "query_uploaded_cases")},
                ),
            ],
            inject_plan=False,
        )
        response = await client.post(
            f"/api/v1/conversations/{workspace['id']}/messages",
            json={
                "content": "只预览上传历史用例，不改写不采纳",
                "document_ids": [doc],
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert not body["action"].get("job_id") and not body["action"].get("proposal")
        assert not latest(workspace["id"])["plan"].get("steps")
        assert (
            body["assistant_message"]["metadata"]["workbench_agent"]["completion"][
                "completion_code"
            ]
            == "tool_result_only"
        )
        assert (await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json() == []
