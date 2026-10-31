"""A real original goal must be planned before any controlled domain preparation.

These providers intentionally bypass the older scripted-provider convenience
fixtures: missing plans are the subject, never automatically inserted by tests.
"""
import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import setup
from test_workbench_continuation_runtime import event_id, execute, run_state

from casepilot_api import conversations, workbench_tools
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    CaseChangeSet,
    CaseCollection,
    Conversation,
    ConversationMessage,
    ConversationOperation,
    GenerationJob,
    WorkbenchRun,
)
from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolCall


class ExplicitProvider:
    def __init__(self, steps):
        self.steps = list(steps)
        self.observations = []

    def complete(self, messages, tools, instructions):
        self.observations.append(list(messages))
        index = len(self.observations) - 1
        if index < len(self.steps):
            step = self.steps[index]
            if isinstance(step, FinalAnswer):
                return ModelTurn(final=step)
            name, arguments = step
            return ModelTurn(calls=[ToolCall(str(index + 1), name, json.dumps(arguments))])
        outputs = [json.loads(item["output"]) for item in messages
                   if item.get("type") == "function_call_output"]
        receipts = [item["_receipt"] for item in outputs if item.get("_receipt")]
        if receipts and receipts[-1]["effect"] in {"read", "prepare"}:
            receipt = receipts[-1]
            return ModelTurn(final=FinalAnswer(kind="action", message="Actual tool result",
                effect=receipt["effect"], receipt_ids=[receipt["id"]]))
        return ModelTurn(final=FinalAnswer(kind="answer", message="Only an intention; no effect."))

    def outputs(self):
        return [json.loads(item["output"]) for message in self.observations for item in message
                if item.get("type") == "function_call_output"]


def activate_explicit(monkeypatch, steps):
    monkeypatch.setattr(conversations.settings, "workbench_agent_enabled", True)
    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: None)
    provider = ExplicitProvider(steps)
    monkeypatch.setattr(workbench_tools, "make_provider", lambda *args: provider)
    return provider


def collection_snapshot(space_id):
    with get_session_factory()() as db:
        return [(str(row.id), row.name, row.deleted_at) for row in db.scalars(
            select(CaseCollection).where(CaseCollection.space_id == UUID(space_id))
            .order_by(CaseCollection.id))]


def assert_no_preparation(cid, space_id, before_collections):
    with get_session_factory()() as db:
        conversation = db.get(Conversation, UUID(cid))
        assert not dict(conversation.context).get("workbench_collection_proposal")
        assert db.scalar(select(func.count()).select_from(ConversationOperation).where(
            ConversationOperation.conversation_id == UUID(cid))) == 0
        assert db.scalar(select(func.count()).select_from(CaseChangeSet).where(
            CaseChangeSet.conversation_id == UUID(cid))) == 0
        assert db.scalar(select(func.count()).select_from(GenerationJob).where(
            GenerationJob.input_payload["conversation_id"].astext == cid)) == 0
        assert collection_snapshot(space_id) == before_collections
        run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
        assert not run.plan.get("steps")
        assert run.status != "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [
    "prepare_generation", "prepare_rewrite", "prepare_delete", "prepare_review",
    "prepare_dedup", "prepare_coverage", "answer_knowledge", "prepare_reuse",
    "create_collection", "rename_collection", "delete_collection",
])
async def test_every_domain_preparation_requires_explicit_typed_plan_before_effects(
    monkeypatch, tool,
):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        before = collection_snapshot(account["spaces"][0]["id"])
        arguments = {}
        if tool in {"create_collection", "rename_collection"}:
            arguments["name"] = "Planned destination"
        if tool in {"rename_collection", "delete_collection"}:
            arguments["collection_id"] = collection["id"]
        provider = activate_explicit(monkeypatch, [(tool, arguments)])
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "完成这项操作，然后查询结果核验。", "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        outputs = provider.outputs()
        rejected = [item for item in outputs if item.get("error_code") == "plan_required"]
        assert rejected, outputs
        assert all(item.get("_receipt") is None for item in rejected)
        assert len(provider.observations) <= conversations.settings.workbench_agent_max_turns
        assert_no_preparation(workspace["id"], account["spaces"][0]["id"], before)


@pytest.mark.asyncio
async def test_repeated_missing_plan_is_bounded_and_never_synthesizes_single_goal(monkeypatch):
    provider = activate_explicit(monkeypatch, [
        ("prepare_generation", {}),
        FinalAnswer(kind="answer", message="I intended to generate."),
        ("prepare_generation", {}),
        FinalAnswer(kind="answer", message="I still only intended to generate."),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, workspace = await setup(client)
        before = collection_snapshot(account["spaces"][0]["id"])
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "为手机号验证码登录生成测试用例，然后查询正式结果核验。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert len(provider.observations) <= 4
        assert_no_preparation(workspace["id"], account["spaces"][0]["id"], before)
        assert any(item.get("error_code") == "plan_required" for item in provider.outputs())
        text = response.json()["assistant_message"]["content"]
        assert text and "已生成" not in text and "已提交" not in text


@pytest.mark.asyncio
async def test_missing_plan_correction_preserves_full_goal_through_real_worker_and_approval(
    monkeypatch,
):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    first = activate_explicit(monkeypatch, [
        ("query_assets", {"scope": "current_collection", "search": ""}),
        ("prepare_generation", {}),
        FinalAnswer(kind="answer", message="I have only inspected the collection."),
        ("plan_work", {"steps": ["查看当前集合", "生成登录用例并等待人工采纳", "查询正式结果核验"],
                        "plan_actions": ["CASE_QUERY", "CASE_GENERATE", "CASE_QUERY"]}),
        ("prepare_generation", {}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        content = "先查看当前集合，为手机号验证码登录生成测试用例，采纳后查询正式结果核验。"
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": content, "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert any(output.get("error_code") == "plan_required" for output in first.outputs())
        job = response.json()["action"]["job_id"]
        state = run_state(cid)
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, state["id"])
            assert [step["action"] for step in run.plan["steps"]] == [
                "CASE_QUERY", "CASE_GENERATE", "CASE_QUERY"]
            assert run.plan["id"] == f"{run.id}:{run.epoch}"
            assert run.plan["root_message_id"] == str(run.root_message_id)
            assert run.plan["epoch"] == run.epoch
            assert run.cursor == 1
            assert run.plan["steps"][0]["status"] == "completed"
            assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                GenerationJob.input_payload["conversation_id"].astext == cid)) == 1
        first_calls = len(first.observations)
        await asyncio.to_thread(tasks.draft_test_brief.run, job)
        assert (await execute(event_id(state["id"], "job_completed", source_id=job)))[
            "status"] == "waiting_approval"
        view = (await client.get(f"/api/v1/conversations/{cid}")).json()
        brief = view["test_briefs"][-1]
        approved = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
            "version": brief["version"],
        })
        assert approved.status_code == 202, approved.text
        generation_job = approved.json()["action"]["job_id"]
        assert len(first.observations) == first_calls
        await asyncio.to_thread(tasks.generate_test_cases.run, generation_job)
        assert (await execute(event_id(state["id"], "job_completed", source_id=generation_job)))[
            "status"] == "waiting_approval"
        adopted = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={})
        assert adopted.status_code == 200, adopted.text
        assert (await execute(event_id(state["id"], "approval_completed",
                                       source_id=generation_job)))["status"] == "active"
        second = activate_explicit(monkeypatch, [
            ("query_assets", {"scope": "current_collection", "search": ""}),
        ])
        assert (await execute(event_id(state["id"], "next_step")))["status"] == "completed"
        assert any(output.get("cases") for output in second.outputs())
        assert run_state(cid)["cursor"] == 3
        assert run_state(cid)["root_message_id"] == state["root_message_id"]
        with get_session_factory()() as db:
            users = list(db.scalars(select(ConversationMessage).where(
                ConversationMessage.conversation_id == UUID(cid),
                ConversationMessage.role == "user")))
            assert len(users) == 1 and users[0].content == content


@pytest.mark.asyncio
@pytest.mark.parametrize("with_followup", [False, True])
async def test_inline_complete_plan_prepares_without_an_extra_plan_roundtrip(
    monkeypatch, with_followup,
):
    actions = ["CASE_GENERATE", "CASE_QUERY"] if with_followup else ["CASE_GENERATE"]
    steps = ["生成验证码登录用例", "采纳后查询核验"] if with_followup else ["生成验证码登录用例"]
    provider = activate_explicit(monkeypatch, [("prepare_generation", {
        "plan": {"steps": steps, "plan_actions": actions},
    })])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        content = ("为手机号验证码登录生成测试用例"
                   + ("，采纳后查询正式结果核验" if with_followup else ""))
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": content, "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert response.json()["action"].get("job_id")
        assert len(provider.observations) == 2
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(
                WorkbenchRun.conversation_id == UUID(workspace["id"])))
            assert [step["action"] for step in run.plan["steps"]] == actions
            assert run.plan["id"] == f"{run.id}:{run.epoch}"
            assert run.plan["root_message_id"] == str(run.root_message_id)
            assert run.plan["epoch"] == run.epoch
            assert run.cursor == 0
            assert run.checkpoint["original_request"]["content"] == content


@pytest.mark.asyncio
async def test_descriptive_outline_is_not_an_executable_plan_for_later_preparation(monkeypatch):
    provider = activate_explicit(monkeypatch, [
        ("plan_work", {"steps": ["整理生成与核验思路"]}),
        ("prepare_generation", {}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, workspace = await setup(client)
        before = collection_snapshot(account["spaces"][0]["id"])
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "生成测试用例，然后核验。", "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert any(output.get("error_code") == "plan_required" for output in provider.outputs())
        assert_no_preparation(workspace["id"], account["spaces"][0]["id"], before)


@pytest.mark.asyncio
async def test_inline_full_plan_consumes_only_actual_leading_query_receipt(monkeypatch):
    provider = activate_explicit(monkeypatch, [
        ("query_assets", {"scope": "current_collection", "search": ""}),
        ("prepare_generation", {"plan": {
            "steps": ["查看集合", "生成登录测试用例", "采纳后查询核验"],
            "plan_actions": ["CASE_QUERY", "CASE_GENERATE", "CASE_QUERY"],
        }}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "先查看当前集合，为手机号验证码登录生成测试用例，采纳后查询核验。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert response.json()["action"].get("job_id")
        assert len(provider.observations) == 3
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(
                WorkbenchRun.conversation_id == UUID(workspace["id"])))
            assert run.cursor == 1
            assert run.plan["steps"][0]["status"] == "completed"
            assert run.plan["steps"][0]["receipt_ids"]
            assert run.plan["steps"][2]["status"] == "pending"
            assert not run.plan["steps"][2].get("receipt_ids")


@pytest.mark.asyncio
async def test_one_query_receipt_cannot_satisfy_two_leading_query_steps(monkeypatch):
    provider = activate_explicit(monkeypatch, [
        ("query_assets", {"scope": "current_collection", "search": ""}),
        ("prepare_generation", {"plan": {
            "steps": ["第一次查询", "第二次独立核验", "生成登录测试用例"],
            "plan_actions": ["CASE_QUERY", "CASE_QUERY", "CASE_GENERATE"],
        }}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "先查询并独立核验当前集合，再为手机号验证码登录生成测试用例。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert not response.json()["action"].get("job_id")
        assert any(output.get("error_code") == "workbench_plan_step_mismatch"
                   for output in provider.outputs())
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(
                WorkbenchRun.conversation_id == UUID(workspace["id"])))
            assert run.cursor == 1
            assert run.plan["steps"][0]["status"] == "completed"
            assert run.plan["steps"][1]["status"] == "pending"
            assert not run.plan["steps"][1].get("receipt_ids")
            assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                GenerationJob.input_payload["conversation_id"].astext == workspace["id"])) == 0


@pytest.mark.asyncio
async def test_outline_only_request_finishes_naturally_without_forcing_preparation(monkeypatch):
    provider = activate_explicit(monkeypatch, [
        ("plan_work", {"steps": ["先整理目标", "列出检查思路"], "plan_actions": []}),
        FinalAnswer(kind="answer", message="这里只列思路，没有执行任何操作。"),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, workspace = await setup(client)
        before = collection_snapshot(account["spaces"][0]["id"])
        cid = workspace["id"]
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "只给我计划思路，不要创建任务、生成、修改或执行。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert len(provider.observations) == 2
        assert response.json()["action"] == {"type": "workbench_agent", "status": "completed"}
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(cid))
            state = conversation.context["workbench_agent"]
            assert not any(item["type"] == "plan_continuation" for item in state["events"])
            assert not conversation.context.get("workbench_collection_proposal")
            run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
            assert run.status == "completed" and not run.plan.get("steps")
            assert db.scalar(select(func.count()).select_from(ConversationOperation).where(
                ConversationOperation.conversation_id == UUID(cid))) == 0
            assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                GenerationJob.input_payload["conversation_id"].astext == cid)) == 0
        assert collection_snapshot(account["spaces"][0]["id"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("correct_case_query", [False, True])
async def test_collection_receipt_cannot_complete_case_query(monkeypatch, correct_case_query):
    steps = [
        ("plan_work", {"steps": ["查询集合内用例", "生成登录测试用例"],
                       "plan_actions": ["CASE_QUERY", "CASE_GENERATE"]}),
        ("query_collections", {"search": ""}),
        ("prepare_generation", {}),
    ]
    if correct_case_query:
        steps += [("query_assets", {"scope": "current_collection", "search": "no-match-title"}),
                  ("prepare_generation", {})]
    provider = activate_explicit(monkeypatch, steps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "先查询当前集合内已有用例，再为手机号验证码登录生成测试用例。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert bool(response.json()["action"].get("job_id")) is correct_case_query
        assert any(output.get("error_code") == "workbench_plan_step_mismatch"
                   for output in provider.outputs())
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(
                WorkbenchRun.conversation_id == UUID(workspace["id"])))
            assert run.cursor == int(correct_case_query)
            assert run.plan["steps"][0]["status"] == (
                "completed" if correct_case_query else "pending")
            if not correct_case_query:
                assert not run.plan["steps"][0].get("receipt_ids")
                assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                    GenerationJob.input_payload["conversation_id"].astext == workspace["id"])) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("typed_plan", [False, True])
async def test_collection_entity_query_completes_without_case_read(monkeypatch, typed_plan):
    steps = []
    if typed_plan:
        steps.append(("plan_work", {"steps": ["查询集合实体"],
                                    "plan_actions": ["COLLECTION_QUERY"]}))
    steps.append(("query_collections", {"search": ""}))
    provider = activate_explicit(monkeypatch, steps)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        response = await client.post(f"/api/v1/conversations/{workspace['id']}/messages", json={
            "content": "只查询有哪些集合，不查询用例，不生成或修改。",
            "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert len(provider.observations) == 3
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(
                WorkbenchRun.conversation_id == UUID(workspace["id"])))
            assert run.status == ("completed" if typed_plan else "waiting_approval")
            if not typed_plan:
                assert run.checkpoint["completion"]["completion_code"] == "goal_unverified"
            assert run.cursor == int(typed_plan)
            assert db.scalar(select(func.count()).select_from(ConversationOperation).where(
                ConversationOperation.conversation_id == UUID(workspace["id"]))) == 0
