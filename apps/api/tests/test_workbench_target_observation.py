"""Resolved request targets are visible without pretending they are persisted selection."""
import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup

from casepilot_api.main import app


def observation(provider):
    message = next(item for item in provider.observations[0]
                   if item.get("role") == "developer"
                   and "Current workspace observation" in str(item.get("content")))
    return json.loads(message["content"].split("\n", 1)[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical", [False, True])
@pytest.mark.parametrize("prior", ["terminal", "pending_review"])
async def test_target_observation_context_and_prepare_across_prior_run(
    monkeypatch, canonical, prior,
):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, conversation = await setup(client)
        cid = conversation["id"]
        created = await client.post(f"/api/v1/collections/{collection['id']}/test-cases", json={
            "title": "Synthetic selected", "module": "Login", "priority": "P2",
            "case_type": "functional", "preconditions": [],
            "steps": [{"action": "Act", "expected": "Pass"}],
        })
        assert created.status_code == 201, created.text
        case = created.json()
        target = {"target_scope": "selected", "target_case_ids": [case["id"]],
                  "targets": [{"kind": "case", "case_ids": [case["id"]]}]}
        if canonical:
            selected = await client.patch(f"/api/v1/workspaces/{cid}/selection", json={
                "base_version": 0,
                "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
            })
            assert selected.status_code == 200, selected.text
            target["selection_version"] = 1
        activate(monkeypatch, [("query_assets", {})] if prior == "terminal"
                 else [("prepare_rewrite", {})])
        first = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "查询当前集合" if prior == "terminal" else "把选中用例优先级改为P1",
            "client_request_id": str(uuid4()), **target,
        })
        assert first.status_code == 202, first.text
        job_id = first.json()["action"].get("job_id")
        if job_id:
            await asyncio.to_thread(tasks.rewrite_test_cases_batch.run, job_id)
        provider = activate(monkeypatch, [("get_workspace_context", {}), ("prepare_rewrite", {})])
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "将已选用例优先级改为P0，保留标题和步骤",
            "client_request_id": str(uuid4()), **target,
        })
        assert response.status_code == 202, response.text
        observed = observation(provider)
        assert observed["selected_count"] == 1
        assert observed["target_origin"] == ("canonical" if canonical else "explicit_request")
        assert observed["canonical_selection_present"] is canonical
        assert observed["canonical_selected_count"] == (1 if canonical else None)
        outputs = [json.loads(item["output"]) for turn in provider.observations
                   for item in turn if item.get("type") == "function_call_output"]
        assert any(value.get("selected_case_ids") == [case["id"]] for value in outputs)
        assert response.json().get("operation_plan", {}).get("operations")
        after = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
        assert after["current_revision_id"] == case["current_revision_id"]
