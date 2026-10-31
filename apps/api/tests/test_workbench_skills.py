"""Built-in capabilities compose tools, never bypass their authority or review gates."""

import json
from uuid import UUID

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from test_workbench_agent import Args, Provider, action, call
from test_workbench_bridge_integration import activate, setup
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import ConversationOperation, GenerationJob, WorkbenchRun
from casepilot_api.workbench_agent import ToolSpec, WorkbenchAgent
from casepilot_api.workbench_skills import (
    SkillSelection,
    assert_bindings,
    catalog,
    load,
    manifest,
)
from casepilot_api.workbench_tools import WorkbenchTools


def chosen(skill_id):
    entry = manifest(skill_id)
    return {"skill_id": skill_id, "version": entry["version"]}


def test_catalog_is_metadata_and_load_is_versioned_guidance_only():
    entries = catalog()
    specs = {s.name: s for s in WorkbenchTools.__new__(WorkbenchTools).specs()}
    assert len(entries) == 4
    for entry in entries:
        assert "instructions" not in entry
        assert set(entry["tools"]) <= specs.keys()
        assert all(not specs[name].requires_approval for name in entry["tools"])
        assert not any(name.startswith(("apply", "approve", "adopt")) for name in entry["tools"])
        loaded = load(SkillSelection(**chosen(entry["skill_id"])))
        assert loaded["instructions"] and loaded["applied"] is False
        assert loaded["authority"] == "guidance_only"
        assert_bindings({entry["skill_id"]: entry["version"]})
    rewrite = manifest("rewrite_cases")
    assert "prepare_generation" not in rewrite["tools"]
    assert "point generation" in rewrite["instructions"]


def test_unknown_path_version_and_arbitrary_authority_are_rejected():
    for change in ({"skill_id": "../../secret"}, {"account_id": "foreign"}):
        with pytest.raises(ValidationError):
            SkillSelection(**{**chosen("rewrite_cases"), **change})
    assert load(SkillSelection(skill_id="rewrite_cases", version="0" * 64)) == {
        "error_code": "skill_version_changed",
    }
    for bindings in ({"unknown": "0" * 64}, {"rewrite_cases": "0" * 64}, []):
        with pytest.raises(HTTPException) as error:
            assert_bindings(bindings)
        assert error.value.detail == "skill_version_changed"


@pytest.mark.parametrize("skill_ids", [
    ["rewrite_cases"], ["inspect_reuse", "plan_test_points"], ["generate_cases"],
])
def test_agent_selects_and_composes_loaded_guidance_within_existing_budget(skill_ids):
    loaded = []
    def loader(args):
        result = load(args)
        loaded.append(result["skill_id"])
        return result
    calls = [call("load_workbench_skill", str(i), json.dumps(chosen(sid)))
             for i, sid in enumerate(skill_ids)]
    provider = Provider(*calls, call("prepare", "execute"), action)
    prepared = []
    result = WorkbenchAgent(provider, [
        ToolSpec("load_workbench_skill", "Load built-in guidance", SkillSelection, loader),
        ToolSpec("prepare", "Synthetic domain boundary", Args,
                 lambda _: prepared.append(True) or {"status": "queued", "applied": False},
                 "prepare"),
    ], max_turns=len(calls) + 2).run(
        [{"role": "user", "content": "Synthetic goal; choose relevant capabilities"}], "Scoped",
    )
    assert result.error_code is None
    assert loaded == skill_ids and prepared == [True]
    assert len(provider.requests) == len(calls) + 2
    observed = [json.loads(item["output"]) for item in provider.requests[-1]
                if item.get("type") == "function_call_output"]
    assert {item["skill_id"]: item["instructions"] for item in observed
            if "skill_id" in item} == {sid: manifest(sid)["instructions"] for sid in skill_ids}
    assert result.final.receipt_ids == [result.tool_results[-1]["receipt"]["id"]]


@pytest.mark.asyncio
async def test_real_api_skill_load_has_no_preparation_or_write(monkeypatch):
    provider = activate(monkeypatch, [("load_workbench_skill", chosen("rewrite_cases"))])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, conversation = await setup(client)
        cid = conversation["id"]
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "了解改写能力的约束，不修改任何用例",
        })
        assert response.status_code == 202, response.text
        with get_session_factory()() as db:
            run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
            assert run.checkpoint["loaded_skills"] == {
                "rewrite_cases": chosen("rewrite_cases")["version"],
            }
            assert run.plan.get("steps", []) == [] and run.cursor == 0
            assert db.scalar(select(func.count()).select_from(ConversationOperation).where(
                ConversationOperation.conversation_id == UUID(cid))) == 0
            assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                GenerationJob.account_id == run.account_id)) == 0
        assert len(provider.observations) == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_outbox_db")
@pytest.mark.parametrize("ending", ["apply", "version_changed", "cancel"])
@pytest.mark.parametrize("inspect_first", [False, True])
async def test_skill_bound_real_worker_review_and_lifecycle(monkeypatch, ending, inspect_first):
    from casepilot_agent import tasks
    from test_workbench_continuation_scope import selected_pair
    from test_workbench_goal_completion import activate as goal_provider
    from test_workbench_goal_completion import send
    from workbench_request_continuation import RequestContinuation

    from casepilot_api import conversations, workbench_skills
    from casepilot_api.models import CaseChangeSet
    from casepilot_api.task_outbox import enqueue_task
    from casepilot_api.workbench_run_executor import execute_workbench_continuation

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases = await selected_pair(client)
        selection = chosen("rewrite_cases")
        prefix = ([
            ("load_workbench_skill", chosen("inspect_reuse")),
            ("query_assets", {"search": "", "scope": "selection"}),
            ("plan_work", {"steps": ["Inspect", "Rewrite selected priority"],
                           "plan_actions": ["CASE_QUERY", "CASE_MODIFY"]}),
            "read",
        ] if inspect_first else [])
        provider = goal_provider(monkeypatch, prefix + [
            ("load_workbench_skill", selection),
            ("prepare_rewrite", {} if inspect_first else {"plan": {
                "steps": ["Change selected priority"], "plan_actions": ["CASE_MODIFY"],
            }}),
            "prepare",
        ])
        monkeypatch.setattr(conversations, "enqueue_task", enqueue_task)
        initial = await send(client, cid, "把选中用例优先级改为P2")
        helper = RequestContinuation(cid, initial, {})
        await helper.advance(tasks, "message")
        await helper.advance(tasks, "workers")
        assert helper.state()["status"] == "waiting_approval"
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, helper.run_id)
            expected_skills = {"rewrite_cases": selection["version"]}
            if inspect_first:
                expected_skills["inspect_reuse"] = chosen("inspect_reuse")["version"]
            assert run.checkpoint["loaded_skills"] == expected_skills
            operation = db.get(ConversationOperation, UUID(run.checkpoint["waiting_operation_id"]))
            assert operation.payload["skill_bindings"] == run.checkpoint["loaded_skills"]
            change_id = run.checkpoint["waiting_artifact_id"]
            assert db.get(CaseChangeSet, UUID(change_id)).status == "ready"
        before = [(await client.get(f"/api/v1/test-cases/{case['id']}")).json()
                  for case in cases]
        assert [row["current_revision_id"] for row in before] == [
            case["current_revision_id"] for case in cases]
        calls = len(provider.observations)
        if ending == "version_changed":
            original_manifest = workbench_skills.manifest
            def changed_manifest(skill_id):
                value = original_manifest(skill_id)
                return {**value, "version": "f" * 64} if value else None
            monkeypatch.setattr(workbench_skills, "manifest", changed_manifest)
        elif ending == "cancel":
            cancelled = await client.post(
                f"/api/v1/conversation-operations/{operation.id}/cancel")
            assert cancelled.status_code == 200
        workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
        body = {
            "selection_version": workspace["context"]["workbench_selection"]["version"],
            "review_refs": [case["id"] for case in cases],
            "accepted_fields": {case["id"]: ["priority"] for case in cases},
        }
        response = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json=body)
        if ending == "apply":
            assert response.status_code == 200, response.text
            await helper.advance(tasks, "applied")
            assert helper.state()["status"] == "completed"
            after = [(await client.get(f"/api/v1/test-cases/{case['id']}")).json()
                     for case in cases]
            assert all(row["priority"] == "P2" for row in after)
            replay = await client.post(f"/api/v1/case-change-sets/{change_id}/apply", json=body)
            assert replay.status_code == 200
        elif ending == "version_changed":
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == "skill_version_changed"
            after = before
        else:
            # Cancelling the proposal rejects it. Replaying apply is an idempotent
            # read of that rejected artifact, not a new write or approval.
            assert response.status_code == 200, response.text
            assert response.json()["change_set"]["status"] == "rejected"
            assert helper.state()["status"] == "cancelled"
            after = before
        for event_id in helper.continuation_ids:
            assert execute_workbench_continuation(event_id)["status"] == "ignored"
        assert [(await client.get(f"/api/v1/test-cases/{case['id']}")).json()
                for case in cases] == after
        assert len(provider.observations) == calls
