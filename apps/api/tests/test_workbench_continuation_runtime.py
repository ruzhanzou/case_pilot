"""Durable multi-segment flow: fake control SDK, real DB/API and domain workers."""
import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import ConversationMessage, WorkbenchContinuation, WorkbenchRun
from casepilot_api.workbench_run_executor import execute_workbench_continuation


def run_state(cid):
    with get_session_factory()() as db:
        run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
        return {"id": run.id, "status": run.status, "cursor": run.cursor,
                "checkpoint": dict(run.checkpoint), "used": dict(run.used),
                "root_message_id": run.root_message_id}


def event_id(run_id, kind, *, source_id=None):
    with get_session_factory()() as db:
        query = select(WorkbenchContinuation).where(
            WorkbenchContinuation.run_id == run_id,
            WorkbenchContinuation.event_kind == kind,
        )
        if source_id is not None:
            query = query.where(WorkbenchContinuation.source_id == str(source_id))
        rows = list(db.scalars(query.order_by(WorkbenchContinuation.created_at)))
        assert rows, f"No durable {kind} event for {source_id}"
        return rows[-1].id


async def execute(event):
    return await asyncio.to_thread(execute_workbench_continuation, event)


@pytest.mark.asyncio
@pytest.mark.parametrize("query_final", [False, True])
async def test_one_request_continues_after_actual_workers_and_exact_human_review(
    monkeypatch, query_final,
):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    first_provider = activate(monkeypatch, [
        ("query_assets", {"search": "", "scope": "current_collection"}),
        ("plan_work", {"steps": ["生成登录用例", "解释验证码测试设计"],
                        "plan_actions": ["CASE_GENERATE",
                                         "CASE_QUERY" if query_final else "KNOWLEDGE_QA"]}),
        ("prepare_generation", {}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        request = {"content": ("先查看当前集合，为手机号验证码登录生成测试用例，"
                               "完成后解释验证码测试设计原则。"),
                   "client_request_id": str(uuid4())}
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
        assert response.status_code == 202, response.text
        turn = response.json()
        job = turn["action"]["job_id"]
        state = run_state(cid)
        assert state["cursor"] == 0
        assert state["checkpoint"]["waiting_job_id"] == job
        calls = len(first_provider.observations)
        await asyncio.to_thread(tasks.draft_test_brief.run, job)
        completed = event_id(state["id"], "job_completed", source_id=job)
        assert (await execute(completed))["status"] == "waiting_approval"
        assert (await execute(completed))["status"] == "ignored"
        assert len(first_provider.observations) == calls
        state = run_state(cid)
        assert state["checkpoint"]["waiting_artifact_kind"] == "test_brief"
        # Polling and reads only project already committed effects.
        for _ in range(2):
            view = await client.get(f"/api/v1/conversations/{cid}")
            assert view.status_code == 200
        assert len(first_provider.observations) == calls
        brief = view.json()["test_briefs"][-1]
        stale = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm",
                                 json={"version": brief["version"] + 1})
        assert stale.status_code == 404, stale.text
        assert run_state(cid)["checkpoint"]["waiting_artifact_kind"] == "test_brief"
        assert len(first_provider.observations) == calls
        confirmed = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm",
                                      json={"version": brief["version"]})
        assert confirmed.status_code == 202, confirmed.text
        next_job = confirmed.json()["action"]["job_id"]
        state = run_state(cid)
        assert state["cursor"] == 0
        assert state["checkpoint"]["waiting_job_id"] == next_job
        assert len(first_provider.observations) == calls
        await asyncio.to_thread(tasks.generate_test_cases.run, next_job)
        generated = event_id(state["id"], "job_completed", source_id=next_job)
        assert (await execute(generated))["status"] == "waiting_approval"
        assert run_state(cid)["checkpoint"]["waiting_artifact_kind"] == "candidates"
        assert len(first_provider.observations) == calls
        candidates = (await client.get(f"/api/v1/conversations/{cid}")).json()["candidates"]
        assert len(candidates) > 1
        first_candidate = candidates[0]
        partial = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={
            "candidate_ids": [first_candidate["id"]],
            "candidate_versions": {first_candidate["id"]: first_candidate["version"]},
        })
        assert partial.status_code == 200, partial.text
        assert run_state(cid)["cursor"] == 0
        assert run_state(cid)["status"] == "waiting_approval"
        assert len(first_provider.observations) == calls
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == state["id"],
                WorkbenchContinuation.event_kind == "next_step")) == 0
        adopted = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={})
        assert adopted.status_code == 200, adopted.text
        approval = event_id(state["id"], "approval_completed", source_id=next_job)
        assert (await execute(approval))["status"] == "active"
        assert run_state(cid)["cursor"] == 1
        next_event = event_id(state["id"], "next_step")
        with get_session_factory()() as db:
            # Existing human confirmation endpoints may log the real click as a
            # user approval. An internal segment must never manufacture input.
            human_user_count = db.scalar(
                select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.conversation_id == UUID(cid),
                ConversationMessage.role == "user"))
        second_provider = activate(monkeypatch, [("get_workspace_context", {}),
            ("query_assets", {"scope": "current_collection", "search": ""}) if query_final
            else ("answer_knowledge", {})])
        result = await execute(next_event)
        assert result["status"] in ({"completed"} if query_final
                                    else {"waiting_worker", "waiting_job"}), result
        next_state = run_state(cid)
        assert next_state["root_message_id"] == state["root_message_id"]
        assert next_state["used"]["segments"] == 2
        second_calls = len(second_provider.observations)
        assert (await execute(next_event))["status"] == "ignored"
        assert len(second_provider.observations) == second_calls
        # The continuation input contains original authority, not invented new users.
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.conversation_id == UUID(cid),
                ConversationMessage.role == "user")) == human_user_count
        if not query_final:
            final_job = next_state["checkpoint"]["waiting_job_id"]
            await asyncio.to_thread(tasks.answer_knowledge_question.run, final_job)
            final_event = event_id(state["id"], "job_completed", source_id=final_job)
            assert (await execute(final_event))["status"] == "completed"
        assert run_state(cid)["cursor"] == 2
        assert len(second_provider.observations) == second_calls


async def pending_segment(client, *, budget=None):
    from casepilot_api.models import Account, Conversation
    from casepilot_api.schemas import ConversationMessageCreate
    from casepilot_api.workbench_continuation import create_run, enqueue_event

    _, _, workspace = await setup(client)
    cid = workspace["id"]
    with get_session_factory()() as db:
        conversation = db.get(Conversation, UUID(cid))
        account = db.get(Account, conversation.account_id)
        payload = ConversationMessageCreate(
            content="解释验证码测试设计原则", client_request_id=uuid4())
        root = ConversationMessage(
            conversation_id=conversation.id, role="user", content=payload.content,
            intent="KNOWLEDGE_QA", intent_confidence=1.0, status="completed", citations=[],
            target_case_ids=[], message_metadata={"request": payload.model_dump(mode="json")},
        )
        db.add(root)
        db.flush()
        run = create_run(db, account, conversation, root.id,
                         payload.client_request_id, budget=budget)
        run.checkpoint = {"original_request": payload.model_dump(mode="json")}
        event = enqueue_event(db, run, "next_step", root.id, "1")
        db.commit()
        return cid, run.id, event.id


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cancel", "binding", "budget"])
async def test_cancel_binding_change_or_budget_exhaustion_never_calls_model(monkeypatch, reason):
    from casepilot_api import workbench_tools
    from casepilot_api.models import Conversation
    from casepilot_api.workbench_continuation import cancel_run

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid authority/budget must be rejected before provider creation")

    monkeypatch.setattr(workbench_tools, "make_provider", forbidden)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        budget = {"segments": 0, "model_turns": 0, "tool_calls": 0, "reserved_sdk_requests": 0}
        cid, run_id, pending = await pending_segment(
            client, budget=budget if reason == "budget" else None)
    with get_session_factory()() as db:
        if reason == "cancel":
            cancel_run(db, run_id)
        elif reason == "binding":
            conversation = db.get(Conversation, UUID(cid))
            conversation.context = {**conversation.context, "workbench_selection": {
                "version": 1, "items": [],
            }}
        db.commit()
    outcome = await execute(pending)
    assert outcome["status"] == ("budget_exhausted" if reason == "budget" else "ignored")
    assert run_state(cid)["status"] == {"cancel": "cancelled", "binding": "invalidated",
                                        "budget": "budget_exhausted"}[reason]


@pytest.mark.asyncio
async def test_crash_after_reservation_recovery_is_conservative_and_idempotent(monkeypatch):
    from casepilot_api import workbench_tools

    provider = activate(monkeypatch, [("get_workspace_context", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, _, pending = await pending_segment(client)
    original = workbench_tools.run_workbench_turn

    def crash(*args, **kwargs):
        raise SystemExit("simulated process loss after durable reservation")

    monkeypatch.setattr(workbench_tools, "run_workbench_turn", crash)
    with pytest.raises(SystemExit):
        execute_workbench_continuation(pending)
    before = run_state(cid)
    assert before["used"]["segments"] == 1
    assert not provider.observations
    monkeypatch.setattr(workbench_tools, "run_workbench_turn", original)
    assert (await execute(pending))["status"] == "completed"
    after = run_state(cid)
    assert after["used"]["segments"] == 2
    for key in ("model_turns", "tool_calls", "reserved_sdk_requests"):
        assert after["used"][key] == before["used"][key] * 2
    count = len(provider.observations)
    assert count > 0
    assert (await execute(pending))["status"] == "ignored"
    assert len(provider.observations) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during_model", [False, True])
async def test_simultaneous_delivery_is_serialized_and_cancel_is_rechecked(
    monkeypatch, cancel_during_model,
):
    import threading

    from casepilot_api.workbench_continuation import cancel_run

    provider = activate(monkeypatch, [("get_workspace_context", {})])
    started, release = threading.Event(), threading.Event()
    complete = provider.complete

    def blocked(*args, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10), "Test failed to release model boundary"
        return complete(*args, **kwargs)

    provider.complete = blocked
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, run_id, pending = await pending_segment(client)
    active = asyncio.create_task(execute(pending))
    try:
        assert await asyncio.to_thread(started.wait, 10)
        # A second worker cannot steal an in-flight provider turn.
        assert (await execute(pending))["status"] == "busy"
        if cancel_during_model:
            def cancel():
                with get_session_factory()() as db:
                    cancel_run(db, run_id)
                    db.commit()
            await asyncio.wait_for(asyncio.to_thread(cancel), 3)
    finally:
        release.set()
    outcome = await active
    assert outcome["status"] == ("obsolete" if cancel_during_model else "completed")
    assert run_state(cid)["status"] == ("cancelled" if cancel_during_model else "completed")
    assert len(provider.observations) == (1 if cancel_during_model else 2)
    assert run_state(cid)["used"]["segments"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("use_request_id", [False, True])
async def test_cancel_endpoint_persists_after_sdk_segment_terminal(monkeypatch, use_request_id):
    from casepilot_agent import tasks

    provider = activate(monkeypatch, [("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid, request_id = workspace["id"], uuid4()
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "为手机号验证码登录生成测试用例", "client_request_id": str(request_id),
        })
        assert response.status_code == 202, response.text
        state = run_state(cid)
        job = state["checkpoint"]["waiting_job_id"]
        await asyncio.to_thread(tasks.draft_test_brief.run, job)
        terminal_event = event_id(state["id"], "job_completed", source_id=job)
        assert (await execute(terminal_event))["status"] == "waiting_approval"
        count = len(provider.observations)
        route_id = request_id if use_request_id else state["id"]
        cancelled = await client.post(f"/api/v1/conversations/{cid}/agent-runs/{route_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert run_state(cid)["status"] == "cancelled"
        reloaded = await client.get(f"/api/v1/conversations/{cid}")
        assert reloaded.status_code == 200, reloaded.text
        assert (await execute(terminal_event))["status"] == "ignored"
        assert len(provider.observations) == count
        assert run_state(cid)["status"] == "cancelled"


def test_busy_celery_delivery_retries_same_event_instead_of_acknowledging(monkeypatch):
    from celery.exceptions import Retry

    from casepilot_api import workbench_run_executor as executor

    identifier = str(uuid4())
    calls, retries = [], []

    def execute_same(event):
        calls.append(event)
        return {"status": "busy" if len(calls) == 1 else "completed"}

    def retry(**kwargs):
        retries.append(kwargs)
        raise Retry()

    monkeypatch.setattr(executor, "execute_workbench_continuation", execute_same)
    monkeypatch.setattr(executor.continue_workbench, "retry", retry)
    with pytest.raises(Retry):
        executor.continue_workbench.run(identifier)
    assert retries == [{"countdown": 1}]
    assert executor.continue_workbench.run(identifier) == {"status": "completed"}
    assert calls == [identifier, identifier]
