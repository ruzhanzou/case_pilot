"""Real API/DB/worker contracts for durable side questions; no live provider calls."""
import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import activate, setup
from test_workbench_continuation_runtime import event_id, execute

from casepilot_api import workbench_tools
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import TaskOutbox, WorkbenchContinuation, WorkbenchRun
from casepilot_api.workbench_agent import AgentProviderError
from casepilot_api.workbench_continuation import cancel_run
from casepilot_api.workbench_turn_pause import pause_prior_runs


def snapshot(run_id):
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        return {"status": run.status, "epoch": run.epoch, "cursor": run.cursor,
                "used": dict(run.used), "budget": dict(run.budget),
                "plan": dict(run.plan), "checkpoint": dict(run.checkpoint),
                "account_id": run.account_id, "conversation_id": run.conversation_id}


async def waiting_review(client, monkeypatch, *, reconcile=True):
    from casepilot_agent import tasks

    provider = activate(monkeypatch, [
        ("plan_work", {"steps": ["生成", "查询"],
                        "plan_actions": ["CASE_GENERATE", "CASE_QUERY"]}),
        ("prepare_generation", {}),
    ])
    _, _, workspace = await setup(client)
    cid = workspace["id"]
    response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
        "content": "为手机号验证码登录生成用例，然后查看当前集合用例。",
        "client_request_id": str(uuid4()),
    })
    assert response.status_code == 202, response.text
    with get_session_factory()() as db:
        run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
        run_id = run.id
    await asyncio.to_thread(tasks.draft_test_brief.run, response.json()["action"]["job_id"])
    completion = event_id(run_id, "job_completed")
    if reconcile:
        assert (await execute(completion))["status"] == "waiting_approval"
    return cid, run_id, completion, provider


@pytest.mark.asyncio
async def test_read_only_question_preserves_exact_waiting_goal_without_continuation(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, run_id, _, first = await waiting_review(client, monkeypatch)
        before = snapshot(run_id)
        original_calls = len(first.observations)
        question = activate(monkeypatch, [("get_workspace_context", {})])
        original = question.complete

        def inspect_pause(*args):
            assert snapshot(run_id)["status"] == "paused_question"
            return original(*args)

        question.complete = inspect_pause
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "这一步正在等待我确认什么？", "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        assert snapshot(run_id) == before
        assert len(first.observations) == original_calls
        assert len(question.observations) == 2
        for _ in range(2):
            view = await client.get(f"/api/v1/conversations/{cid}")
            assert view.status_code == 200
            progress = view.json()["context"]["workbench_agent"]["durable_run"]
            assert progress["id"] == str(run_id)
            assert progress["status"] == "waiting_approval"
        assert len(question.observations) == 2
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id,
                WorkbenchContinuation.event_kind == "next_step")) == 0


@pytest.mark.asyncio
async def test_actual_selection_change_invalidates_old_goal_not_read_receipt(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, run_id, _, _ = await waiting_review(client, monkeypatch)
        before = snapshot(run_id)
        activate(monkeypatch, [("select_assets", {"base_version": 0,
                                                 "action": "clear", "sources": []})])
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "清空当前选中范围，停止之前的计划。", "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        after = snapshot(run_id)
        assert after["status"] == "invalidated"
        assert after["epoch"] == before["epoch"] + 1
        assert after["used"] == before["used"]
        assert after["checkpoint"]["invalidation_reason"] == "new_mutating_instruction"


@pytest.mark.asyncio
async def test_cancel_during_side_question_is_never_restored(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, run_id, _, _ = await waiting_review(client, monkeypatch)
        before = snapshot(run_id)
        question = activate(monkeypatch, [("get_workspace_context", {})])
        original = question.complete
        cancelled = False

        def cancel_during_model(*args):
            nonlocal cancelled
            if not cancelled:
                assert snapshot(run_id)["status"] == "paused_question"
                with get_session_factory()() as db:
                    cancel_run(db, run_id)
                    db.commit()
                cancelled = True
            return original(*args)

        question.complete = cancel_during_model
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "解释当前待确认结果。", "client_request_id": str(uuid4()),
        })
        assert response.status_code == 202, response.text
        after = snapshot(run_id)
        assert after["status"] == "cancelled"
        assert after["epoch"] == before["epoch"] + 1
        assert after["used"] == before["used"]


@pytest.mark.asyncio
async def test_interrupted_question_stays_paused_and_same_request_can_resolve(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, run_id, _, _ = await waiting_review(client, monkeypatch)
        before = snapshot(run_id)
        question_id = uuid4()
        request = {"content": "解释当前待确认结果。", "client_request_id": str(question_id)}

        def unavailable(*args):
            raise AgentProviderError("agent_configuration_missing")

        monkeypatch.setattr(workbench_tools, "make_provider", unavailable)
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
        assert response.status_code == 503, response.text
        paused = snapshot(run_id)
        assert paused["status"] == "paused_question"
        assert paused["checkpoint"]["question_pause"]["request_id"] == str(question_id)
        assert paused["used"] == before["used"]
        activate(monkeypatch, [("get_workspace_context", {})])
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
        assert response.status_code == 202, response.text
        assert snapshot(run_id) == before


@pytest.mark.asyncio
async def test_paused_delivery_republishes_same_observation_after_read_question(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, run_id, pending, _ = await waiting_review(client, monkeypatch, reconcile=False)
        before = snapshot(run_id)
        question_id = uuid4()
        pause_prior_runs(get_session_factory(), before["account_id"],
                         before["conversation_id"], question_id)
        assert (await execute(pending))["status"] == "ignored"
        with get_session_factory()() as db:
            assert db.get(WorkbenchContinuation, pending).status == "pending"
            deliveries_before = db.scalar(select(func.count()).select_from(TaskOutbox).where(
                TaskOutbox.task_id == str(pending)))
        question = activate(monkeypatch, [("get_workspace_context", {})])
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "解释当前任务进展。", "client_request_id": str(question_id),
        })
        assert response.status_code == 202, response.text
        assert snapshot(run_id) == before
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(TaskOutbox).where(
                TaskOutbox.task_id == str(pending))) == deliveries_before + 1
        calls = len(question.observations)
        assert (await execute(pending))["status"] == "waiting_approval"
        assert len(question.observations) == calls


@pytest.mark.asyncio
async def test_initial_segment_cancel_is_durable_before_root_commit_and_replay(monkeypatch):
    import threading

    from casepilot_api.models import WorkbenchReservation
    from casepilot_api.workbench_events import WorkbenchEventStore

    provider = activate(monkeypatch, [("get_workspace_context", {})])
    started, release = threading.Event(), threading.Event()
    original = provider.complete

    def blocked(*args):
        started.set()
        assert release.wait(10), "Test failed to release initial provider boundary"
        return original(*args)

    provider.complete = blocked
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, workspace = await setup(client)
        cid, request_id = workspace["id"], uuid4()
        request = {"content": "查看当前工作区上下文。", "client_request_id": str(request_id)}
        active = asyncio.create_task(client.post(f"/api/v1/conversations/{cid}/messages",
                                                json=request))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            # Real user message/run remain uncommitted while the model is blocked.
            with get_session_factory()() as db:
                assert db.scalar(select(func.count()).select_from(WorkbenchRun).where(
                    WorkbenchRun.conversation_id == UUID(cid))) == 0
            cancelled = await asyncio.wait_for(client.post(
                f"/api/v1/conversations/{cid}/agent-runs/{request_id}/cancel"), 3)
            assert cancelled.status_code == 200, cancelled.text
            with get_session_factory()() as db:
                ledger = db.scalar(select(WorkbenchReservation).where(
                    WorkbenchReservation.conversation_id == UUID(cid),
                    WorkbenchReservation.request_id == request_id))
                assert ledger.cancelled_at is not None
            # Cancellation must survive complete loss of the ephemeral Redis flag.
            monkeypatch.setattr(WorkbenchEventStore, "is_cancelled", lambda self: False)
        finally:
            release.set()
        response = await active
        assert response.status_code == 202, response.text
        assert len(provider.observations) == 1
        assert response.json()["assistant_message"]["metadata"]["workbench_agent"][
            "completion"]["completion_code"] == "cancelled"
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
            assert run.status == "cancelled"
        replay = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
        assert replay.status_code == 202, replay.text
        assert len(provider.observations) == 1
