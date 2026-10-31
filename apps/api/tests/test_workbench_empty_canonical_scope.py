"""Empty canonical projection stays selected and never becomes a collection selector."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401
from test_workbench_continuation_runtime import event_id, execute, run_state
from test_workbench_continuation_scope import selected_pair
from test_workbench_goal_completion import send

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Conversation, WorkbenchRun
from casepilot_api.workbench_continuation import validate_binding

pytestmark = pytest.mark.usefixtures("isolated_outbox_db")


async def empty(client):
    cid, cases = await selected_pair(client)
    result = await client.patch(
        f"/api/v1/workspaces/{cid}/selection",
        json={"base_version": 1, "action": "clear", "sources": []},
    )
    assert result.status_code == 200
    return cid, cases


@pytest.mark.asyncio
async def test_empty_canonical_generation_job_completion_waits_for_human(monkeypatch):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    provider = activate(monkeypatch, [("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await empty(client)
        turn = await send(client, cid, "生成新的登录测试点，先规划让我确认。")
        state = run_state(cid)
        original = deepcopy(state["checkpoint"]["original_request"])
        assert original["target_scope"] == "selected"
        assert original["targets"][0]["case_ids"] == []
        job = turn["action"]["job_id"]
        tasks.draft_test_brief.run(job)
        before = len(provider.observations)
        assert (await execute(event_id(state["id"], "job_completed", source_id=job)))[
            "status"
        ] == "waiting_approval"
        assert len(provider.observations) == before
        assert run_state(cid)["checkpoint"]["original_request"] == original
        for case in cases:
            assert (await client.get(f"/api/v1/test-cases/{case['id']}")).json()[
                "current_revision_id"
            ] == case["current_revision_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["prepare_rewrite", "prepare_delete"])
async def test_empty_selection_cannot_modify_or_delete(monkeypatch, tool):
    activate(monkeypatch, [(tool, {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await empty(client)
        turn = await send(client, cid, "只处理当前选中的用例，不扩大范围。")
        assert not turn.get("action", {}).get("change_set_id")
        for case in cases:
            value = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert value["current_revision_id"] == case["current_revision_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["case", "candidate", "symbolic", "no_canonical", "version", "foreign", "stale_ref"]
)
async def test_nonempty_or_changed_authority_still_fails_closed(monkeypatch, bad):
    activate(monkeypatch, [("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await empty(client)
        await send(client, cid, "生成新的登录测试点，先规划让我确认。")
        state = run_state(cid)
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, state["id"])
            conv = db.get(Conversation, UUID(cid))
            checkpoint = deepcopy(run.checkpoint)
            request = checkpoint["original_request"]
            if bad == "case":
                request["targets"][0]["case_ids"] = [cases[0]["id"]]
            elif bad == "candidate":
                request["targets"][0]["candidate_refs"] = ["unbound-candidate"]
            elif bad == "symbolic":
                request["targets"][0]["kind"] = "module"
            elif bad == "no_canonical":
                context = deepcopy(conv.context)
                context.pop("workbench_selection")
                conv.context = context
            elif bad == "version":
                run.binding = {**run.binding, "selection_version": 0}
            elif bad == "foreign":
                run.account_id = uuid4()
            else:
                run.binding = {
                    **run.binding,
                    "sources": [{"ref": f"asset:{cases[0]['id']}", "version": str(uuid4())}],
                }
            run.checkpoint = checkpoint
            with pytest.raises(HTTPException):
                validate_binding(db, run, conv)
            db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["case", "candidate", "symbolic"])
async def test_unbound_nonempty_job_completion_invalidates_without_model(monkeypatch, kind):
    from casepilot_agent import tasks

    from casepilot_api.models import WorkbenchContinuation

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    provider = activate(monkeypatch, [("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await empty(client)
        turn = await send(client, cid, "生成新的登录测试点，先规划让我确认。")
        state = run_state(cid)
        job = turn["action"]["job_id"]
        tasks.draft_test_brief.run(job)
        eid = event_id(state["id"], "job_completed", source_id=job)
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, state["id"])
            checkpoint = deepcopy(run.checkpoint)
            target = checkpoint["original_request"]["targets"][0]
            if kind == "case":
                target["case_ids"] = [cases[0]["id"]]
            elif kind == "candidate":
                target["candidate_refs"] = ["unbound-candidate"]
            else:
                target["kind"] = "module"
                target["module"] = "Login"
            run.checkpoint = checkpoint
            db.commit()
        calls = len(provider.observations)
        await execute(eid)
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            assert db.get(WorkbenchRun, state["id"]).status == "invalidated"
            event = db.get(WorkbenchContinuation, eid)
            assert event.status == "invalidated"
            assert event.receipt == {"error_code": "workbench_legacy_scope_requires_reselection"}
