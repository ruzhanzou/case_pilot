"""Canonical workbench edits compute drafts immediately; only review applies writes."""

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseChangeSet, ConversationOperation, GenerationJob


async def selected_case(client):
    _, collection, workspace = await setup(client)
    case = (
        await client.post(
            f"/api/v1/collections/{collection['id']}/test-cases",
            json={
                "title": "Login",
                "priority": "P2",
                "steps": [{"action": "Login", "expected": "Success"}],
            },
        )
    ).json()
    cid = workspace["id"]
    selected = await client.patch(
        f"/api/v1/workspaces/{cid}/selection",
        json={
            "base_version": 0,
            "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
        },
    )
    assert selected.status_code == 200, selected.text
    return cid, case


@pytest.mark.asyncio
async def test_canonical_draft_compute_replay_worker_then_exact_review(monkeypatch):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    provider = activate(monkeypatch, [("prepare_rewrite", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, case = await selected_case(client)
        url = f"/api/v1/conversations/{cid}/messages"
        request = {"content": "把选中用例优先级改为P1", "client_request_id": str(uuid4())}
        response = await client.post(url, json=request)
        assert response.status_code == 202, response.text
        turn = response.json()
        assert turn["action"].get("job_id"), turn
        assert not turn["assistant_message"]["metadata"].get("modification_confirmation")
        operation = turn["operation_plan"]["operations"][0]
        assert operation["payload"]["preparation_mode"] == "canonical_draft_compute"
        assert not operation["payload"].get("last_confirmed_modification")
        assert operation["payload"]["prepared_modification"]["sources"] == [
            {
                "ref": f"asset:{case['id']}",
                "version": case["current_revision_id"],
            }
        ]
        assert operation["payload"]["rewrite_draft"]["phase"] == "executing"
        agent = turn["assistant_message"]["metadata"]["workbench_agent"]
        assert agent["domain_status"] == "queued"
        assert agent["requires_human_review"] is False
        calls = len(provider.observations)
        assert (await client.post(url, json=request)).json() == turn
        assert len(provider.observations) == calls
        premature = await client.post(
            f"/api/v1/case-change-sets/{turn['action']['change_set_id']}/apply", json={}
        )
        assert premature.status_code == 409
        await asyncio.to_thread(tasks.rewrite_test_cases_batch.run, turn["action"]["job_id"])
        unchanged = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert unchanged["current_revision_id"] == case["current_revision_id"]
        change = (
            await client.get(f"/api/v1/case-change-sets/{turn['action']['change_set_id']}")
        ).json()
        assert change["status"] == "ready"
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert state["context"]["workbench_agent"]["domain_status"] == "awaiting_input"
        assert state["context"]["workbench_agent"]["requires_human_review"] is True
        assert len(provider.observations) == calls
        applied = await client.post(f"/api/v1/case-change-sets/{change['id']}/apply", json={})
        assert applied.status_code == 200, applied.text
        changed = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert changed["priority"] == "P1"
        assert changed["current_revision_id"] != case["current_revision_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("supplement", [{}, {"content": "把选中用例优先级改为P0"}])
async def test_failed_compute_retry_and_supplement_keep_computation_not_approval(
    monkeypatch, supplement
):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    activate(monkeypatch, [("prepare_rewrite", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, case = await selected_case(client)
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "把选中用例优先级改为P1",
                "client_request_id": str(uuid4()),
            },
        )
        turn = response.json()
        assert turn["action"].get("job_id"), turn
        opid = turn["operation_plan"]["operations"][0]["id"]
        with get_session_factory()() as db:
            db.get(GenerationJob, UUID(turn["action"]["job_id"])).status = "failed"
            db.get(ConversationOperation, UUID(opid)).status = "failed"
            db.get(CaseChangeSet, UUID(turn["action"]["change_set_id"])).status = "failed"
            db.commit()
        retry = await client.post(f"/api/v1/conversation-operations/{opid}/resume", json=supplement)
        assert retry.status_code == 202, retry.text
        assert retry.json()["action"].get("job_id"), retry.text
        assert retry.json()["action"]["job_id"] != turn["action"]["job_id"]
        payload = retry.json()["operation_plan"]["operations"][0]["payload"]
        assert not payload.get("last_confirmed_modification")
        await asyncio.to_thread(
            tasks.rewrite_test_cases_batch.run, retry.json()["action"]["job_id"]
        )
        activate(monkeypatch, [("prepare_rewrite", {})])
        continued = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "把选中用例优先级改为P0",
                "client_request_id": str(uuid4()),
            },
        )
        assert continued.status_code == 202, continued.text
        assert continued.json()["action"].get("job_id"), continued.text
        operation = continued.json()["operation_plan"]["operations"][0]
        assert operation["payload"]["preparation_mode"] == "canonical_draft_compute"
        assert not operation["payload"].get("last_confirmed_modification")
        cancelled = await client.post(
            f"/api/v1/generation-jobs/{continued.json()['action']['job_id']}/cancel"
        )
        assert cancelled.status_code == 200, cancelled.text
        cancelled_worker = await asyncio.to_thread(
            tasks.rewrite_test_cases_batch.run,
            continued.json()["action"]["job_id"],
        )
        assert cancelled_worker["status"] == "duplicate_ignored"
        with get_session_factory()() as db:
            cancelled_job = db.get(GenerationJob, UUID(continued.json()["action"]["job_id"]))
            assert cancelled_job.status == "cancelled"
        current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert current["current_revision_id"] == case["current_revision_id"]


@pytest.mark.asyncio
async def test_legacy_canonical_edit_still_has_scope_confirmation(monkeypatch):
    monkeypatch.setattr(conversations.settings, "workbench_agent_enabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, _ = await selected_case(client)
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "把选中用例优先级改为P1",
                "intent_override": "CASE_MODIFY",
            },
        )
        assert response.status_code == 202, response.text
        assert not response.json()["action"].get("job_id")
        assert response.json()["assistant_message"]["metadata"]["modification_confirmation"]


def test_current_generation_test_object_wins_over_old_memory(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    fallback = Mock(side_effect=AssertionError("current object must avoid another model call"))
    monkeypatch.setattr(conversations, "_test_object_from_memory", fallback)
    assert (
        conversations._generation_test_object(
            SimpleNamespace(test_object="  New payment flow  "),
            [{"role": "user", "content": "Old login flow"}],
        )
        == "New payment flow"
    )
    fallback.assert_not_called()


@pytest.mark.parametrize("current", [None, "", "  "])
def test_missing_generation_test_object_uses_history(monkeypatch, current):
    from types import SimpleNamespace
    from unittest.mock import Mock

    fallback = Mock(return_value="Historical target")
    monkeypatch.setattr(conversations, "_test_object_from_memory", fallback)
    memory = [{"role": "user", "content": "Historical target"}]
    assert conversations._generation_test_object(SimpleNamespace(test_object=current), memory) == (
        "Historical target"
    )
    fallback.assert_called_once_with(memory)
