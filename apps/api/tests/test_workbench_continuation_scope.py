"""Exact authorized subsets survive SDK segments and real domain worker boundaries."""
import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import activate, setup
from test_workbench_continuation_runtime import event_id, execute

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    CaseChangeSet,
    Conversation,
    ConversationMessage,
    ConversationOperation,
    WorkbenchRun,
)
from casepilot_api.workbench_scope import apply_authorized_scope_delta, restore_authorized_scope


async def selected_pair(client):
    _, collection, conversation = await setup(client)
    cases = []
    for title in ("Only A", "Untouched B"):
        response = await client.post(f"/api/v1/collections/{collection['id']}/test-cases", json={
            "title": title, "module": "Login", "priority": "P1",
            "case_type": "功能", "tags": [], "preconditions": [],
            "steps": [{"action": "Submit code", "expected": "Rejected"}],
        })
        assert response.status_code == 201, response.text
        cases.append(response.json())
    cid = conversation["id"]
    selected = await client.patch(f"/api/v1/workspaces/{cid}/selection", json={
        "base_version": 0, "action": "replace", "sources": [
            {"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}
            for case in cases
        ],
    })
    assert selected.status_code == 200, selected.text
    return cid, cases


async def query_segment(client, monkeypatch, cid, cases, *, narrow=False):
    calls = [
        ("plan_work", {"steps": ["查看指定 A", "只修改 A 优先级"],
                        "plan_actions": ["CASE_QUERY", "CASE_MODIFY"]}),
        ("query_assets", {"search": "", "scope": "selection"}),
    ]
    if narrow:
        calls.append(("select_assets", {"base_version": 1, "action": "replace", "sources": [
            {"ref": f"asset:{cases[0]['id']}", "version": cases[0]["current_revision_id"]},
        ]}))
    provider = activate(monkeypatch, calls)
    request = {"content": ("先选择 Only A，再查看选中用例，然后把选中用例优先级改为P2。"
                           if narrow else "先查看指定用例，然后把指定用例优先级改为P2。"),
               "selection_version": 1, "client_request_id": str(uuid4())}
    if not narrow:
        request["target_case_ids"] = [cases[0]["id"]]
    response = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
    assert response.status_code == 202, response.text
    with get_session_factory()() as db:
        run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
        assert run.cursor == 1, response.json()
        assert run.checkpoint["authorized_sources"] == [
            {"ref": f"asset:{cases[0]['id']}", "version": cases[0]["current_revision_id"]},
        ]
        assert run.checkpoint["authorized_scope_request"]["target_case_ids"] == [cases[0]["id"]]
        return run.id, provider


@pytest.mark.asyncio
@pytest.mark.parametrize("narrow", [False, True])
async def test_explicit_or_receipted_subset_survives_continuation_and_actual_rewrite(
    monkeypatch, narrow,
):
    from casepilot_agent import tasks

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await selected_pair(client)
        run_id, first = await query_segment(client, monkeypatch, cid, cases, narrow=narrow)
        first_calls = len(first.observations)
        provider = activate(monkeypatch, [("prepare_rewrite", {})])
        continuation = event_id(run_id, "next_step")
        outcome = await execute(continuation)
        assert outcome["status"] == "waiting_job", outcome
        assert len(first.observations) == first_calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            job_id = run.checkpoint["waiting_job_id"]
            operation = db.get(ConversationOperation, UUID(run.checkpoint["waiting_operation_id"]))
            assert operation.payload["prepared_modification"]["sources"] == [
                {"ref": f"asset:{cases[0]['id']}", "version": cases[0]["current_revision_id"]},
            ]
            change_id = operation.related_change_set_id
            assert db.scalar(select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.conversation_id == UUID(cid),
                ConversationMessage.role == "user")) == 1
        await asyncio.to_thread(tasks.rewrite_test_cases_batch.run, job_id)
        with get_session_factory()() as db:
            change = db.get(CaseChangeSet, change_id)
            assert change.status == "ready"
            assert {item["test_case_id"] for item in change.items} == {cases[0]["id"]}
        # Computation is private; both canonical assets retain their versions before approval.
        for case in cases:
            current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert current["current_revision_id"] == case["current_revision_id"]
            assert current["priority"] == "P1"
        calls = len(provider.observations)
        assert (await execute(continuation))["status"] == "ignored"
        assert len(provider.observations) == calls


@pytest.mark.asyncio
async def test_approved_delta_only_rebases_authorized_refs_and_empty_never_broadens(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await selected_pair(client)
        run_id, _ = await query_segment(client, monkeypatch, cid, cases)
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            conversation = db.get(Conversation, UUID(cid))
            a_ref, b_ref = (f"asset:{case['id']}" for case in cases)
            a_next, b_next = str(uuid4()), str(uuid4())
            apply_authorized_scope_delta(db, run, conversation,
                                         approved_updates={a_ref: a_next, b_ref: b_next})
            assert run.checkpoint["authorized_sources"] == [{"ref": a_ref, "version": a_next}]
            assert run.checkpoint["authorized_scope_request"]["target_case_ids"] == [cases[0]["id"]]
            # Removing the sole authorized A leaves broader canonical B available,
            # but never silently turns an empty exact scope into "all selected".
            state = dict(conversation.context["workbench_selection"])
            state["items"] = [item for item in state["items"] if item["ref"] == b_ref]
            state["version"] += 1
            conversation.context = {**conversation.context, "workbench_selection": state}
            apply_authorized_scope_delta(db, run, conversation, removed_refs=[a_ref])
            assert run.checkpoint["authorized_sources"] == []
            assert run.checkpoint["authorized_scope_request"]["target_case_ids"] == []
            with pytest.raises(HTTPException) as error:
                restore_authorized_scope(run, conversation)
            assert error.value.detail == "workbench_scope_requires_selection"
            db.rollback()
