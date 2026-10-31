"""Real PG/API/outbox/worker/executor with deterministic providers; no live calls."""

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401
from test_workbench_continuation_scope import selected_pair
from test_workbench_goal_completion import activate, send
from workbench_agent_live_journey import JourneyFailure
from workbench_request_continuation import RequestContinuation

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    CaseChangeSet,
    ConversationMessage,
    TaskOutbox,
    WorkbenchContinuation,
    WorkbenchRun,
)
from casepilot_api.task_outbox import enqueue_task
from casepilot_api.workbench_run_executor import execute_workbench_continuation

pytestmark = pytest.mark.usefixtures("isolated_outbox_db")


async def late_prepare(client, monkeypatch):
    from casepilot_agent.pipeline import _explicit_rewrite_candidate
    from casepilot_agent.providers.mock import MockProvider

    # Deterministic provider response only; worker diff/store/approval stay real.
    def priority_candidate(_provider, request):
        assert "P2" in request.instruction
        return _explicit_rewrite_candidate(
            request.model_copy(update={"instruction": "把选中用例优先级改为P2"})
        )

    monkeypatch.setattr(MockProvider, "rewrite", priority_candidate)
    cid, cases = await selected_pair(client)
    provider = activate(
        monkeypatch,
        [
            ("query_assets", {"search": "", "scope": "selection"}),
            (
                "plan_work",
                {
                    "steps": ["Inspect", "Prepare priority update"],
                    "plan_actions": ["CASE_QUERY", "CASE_MODIFY"],
                },
            ),
            "read",
            ("prepare_rewrite", {}),
            "prepare",
        ],
    )
    # activate() deliberately blocks delivery in unrelated tests. Here restore
    # the real transactional outbox, not a direct task fixture.
    monkeypatch.setattr(conversations, "enqueue_task", enqueue_task)
    turn = await send(client, cid, "先查看当前选择，再只把优先级改为P2，等待我确认应用")
    assert not turn.get("operation_plan")
    return cid, cases, provider, turn


@pytest.mark.asyncio
async def test_late_plan_real_prepare_worker_review_apply_terminal(monkeypatch):
    from casepilot_agent import tasks

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases, provider, initial = await late_prepare(client, monkeypatch)
        report = {}
        helper = RequestContinuation(cid, initial, report)
        try:
            prepared = await helper.advance(tasks, "message")
        except JourneyFailure:
            import json

            pytest.fail(json.dumps(report))
        assert prepared is not initial and prepared["operation_plan"]["operations"]
        state = helper.state()
        assert state["status"] == "waiting_job" and state["pending_outbox"] == 1
        assert report["durable_domain_tasks"] == 0
        calls = len(provider.observations)
        await helper.advance(tasks, "workers")
        state = helper.state()
        assert state["status"] == "waiting_approval" and state["artifact_kind"] == "change_set"
        assert state["pending_outbox"] == 0 and len(provider.observations) == calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, helper.run_id)
            change = db.get(CaseChangeSet, UUID(run.checkpoint["waiting_artifact_id"]))
            change_id = str(change.id)
            assert change.status == "ready"
            assert all(
                any(d["field"] == "priority" and d["after"] == "P2" for d in item["field_diff"])
                for item in change.items
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ConversationMessage)
                    .where(
                        ConversationMessage.conversation_id == UUID(cid),
                        ConversationMessage.role == "user",
                    )
                )
                == 1
            )
        for case in cases:
            assert (await client.get(f"/api/v1/test-cases/{case['id']}")).json()[
                "current_revision_id"
            ] == case["current_revision_id"]
        current = (await client.get(f"/api/v1/conversations/{cid}")).json()
        approval = await client.post(
            f"/api/v1/case-change-sets/{change_id}/apply",
            json={
                "selection_version": current["context"]["workbench_selection"]["version"],
                "review_refs": [case["id"] for case in cases],
                "accepted_fields": {case["id"]: ["priority"] for case in cases},
            },
        )
        assert approval.status_code == 200
        await helper.advance(tasks, "applied")
        assert helper.state()["status"] == "completed" and helper.state()["cursor"] == 2
        assert len(provider.observations) == calls
        revisions = [
            (await client.get(f"/api/v1/test-cases/{c['id']}")).json()["current_revision_id"]
            for c in cases
        ]
        for event_id in helper.continuation_ids:
            assert execute_workbench_continuation(event_id)["status"] == "ignored"
        assert revisions == [
            (await client.get(f"/api/v1/test-cases/{c['id']}")).json()["current_revision_id"]
            for c in cases
        ]
        assert len(provider.observations) == calls


@pytest.mark.asyncio
async def test_new_selection_invalidates_old_work_without_resuming_it(monkeypatch):
    from casepilot_agent import tasks

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases, provider, initial = await late_prepare(client, monkeypatch)
        helper = RequestContinuation(cid, initial, {})
        with get_session_factory()() as db:
            event_id = str(
                db.scalar(
                    select(WorkbenchContinuation.id).where(
                        WorkbenchContinuation.run_id == helper.run_id
                    )
                )
            )
        changed = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 1,
                "sources": [
                    {"ref": f"asset:{cases[1]['id']}", "version": cases[1]["current_revision_id"]}
                ],
            },
        )
        assert changed.status_code == 200
        calls = len(provider.observations)
        await helper.advance(tasks, "message")
        assert helper.state()["status"] in {"cancelled", "invalidated"}
        assert helper.executed == 1 and len(provider.observations) == calls
        assert execute_workbench_continuation(event_id)["status"] == "ignored"
        assert len(provider.observations) == calls


@pytest.mark.asyncio
async def test_foreign_pending_outbox_is_untouched(monkeypatch):
    from casepilot_agent import tasks

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as first:
        cid, _, provider, initial = await late_prepare(first, monkeypatch)
        helper = RequestContinuation(cid, initial, {})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            await late_prepare(other, monkeypatch)
        with get_session_factory()() as db:
            before = [
                (r.id, r.status, r.attempts)
                for r in db.scalars(select(TaskOutbox).order_by(TaskOutbox.id))
            ]
        with pytest.raises(JourneyFailure, match="durable_foreign_delivery"):
            await helper.advance(tasks, "message")
        with get_session_factory()() as db:
            after = [
                (r.id, r.status, r.attempts)
                for r in db.scalars(select(TaskOutbox).order_by(TaskOutbox.id))
            ]
        assert after == before and helper.executed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["clarify", "query_only", "select_only"])
async def test_nonworker_stops_do_not_poll_or_create_writes(monkeypatch, kind):
    from casepilot_agent import tasks

    from casepilot_api.workbench_agent import FinalAnswer

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await selected_pair(client)
        if kind == "clarify":
            steps = [FinalAnswer(kind="clarify", message="请说明范围")]
        elif kind == "query_only":
            steps = [
                ("plan_work", {"steps": ["Inspect"], "plan_actions": ["CASE_QUERY"]}),
                ("query_assets", {"scope": "selection"}),
                "read",
            ]
        else:
            steps = [
                ("query_assets", {"scope": "selection"}),
                (
                    "select_assets",
                    {
                        "action": "remove",
                        "base_version": 1,
                        "sources": [
                            {
                                "ref": f"asset:{cases[1]['id']}",
                                "version": cases[1]["current_revision_id"],
                            }
                        ],
                    },
                ),
                "prepare",
            ]
        provider = activate(monkeypatch, steps)
        monkeypatch.setattr(conversations, "enqueue_task", enqueue_task)
        turn = await send(client, cid, "仅查看或更新选择，不改写用例")
        helper = RequestContinuation(cid, turn, {})
        calls = len(provider.observations)
        await helper.advance(tasks, "message")
        assert helper.executed == 0 and len(provider.observations) == calls
        assert helper.state()["pending_outbox"] == helper.state()["pending_events"] == 0
        if kind == "query_only":
            assert helper.state()["status"] == "completed"
        for case in cases:
            assert (await client.get(f"/api/v1/test-cases/{case['id']}")).json()[
                "current_revision_id"
            ] == case["current_revision_id"]


@pytest.mark.asyncio
async def test_pending_event_without_delivery_is_failure_not_completion(monkeypatch):
    from casepilot_agent import tasks

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, _, provider, turn = await late_prepare(client, monkeypatch)
        helper = RequestContinuation(cid, turn, {})
        with get_session_factory()() as db:
            event = db.scalar(
                select(WorkbenchContinuation).where(WorkbenchContinuation.run_id == helper.run_id)
            )
            row = db.scalar(select(TaskOutbox).where(TaskOutbox.task_id == str(event.id)))
            db.delete(row)  # Isolated synthetic transport-loss fault only.
            db.commit()
        calls = len(provider.observations)
        with pytest.raises(JourneyFailure, match="durable_pending_not_consumed"):
            await helper.advance(tasks, "message")
        assert helper.state()["pending_events"] == 1
        assert helper.executed == 0 and len(provider.observations) == calls
