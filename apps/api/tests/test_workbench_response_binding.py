"""Real ASGI/DB response binding; model is injected, no live provider calls."""
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseChangeSet, ConversationOperation, GenerationJob
from casepilot_api.models import TestCase as CaseRecord


@pytest.mark.asyncio
async def test_controlled_rewrite_returns_same_bound_operation_as_persisted_history(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts" / "qa"))
    from workbench_agent_live_journey import validate_operation_binding

    provider = activate(monkeypatch, [("prepare_rewrite", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, conversation = await setup(client)
        cid = conversation["id"]
        response = await client.post(
            f"/api/v1/collections/{collection['id']}/test-cases",
            json={"title": "Bound rewrite", "module": "Login", "priority": "P1",
                  "case_type": "功能", "tags": [], "preconditions": [],
                  "steps": [{"action": "Submit code", "expected": "Rejected"}]},
        )
        assert response.status_code == 201, response.text
        case = response.json()
        response = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={"base_version": 0, "action": "replace",
                  "sources": [{"ref": f"asset:{case['id']}",
                               "version": case["current_revision_id"]}]},
        )
        assert response.status_code == 200, response.text
        canonical = response.json()["context"]["workbench_selection"]
        request = {"content": "把选中用例优先级改为P2", "selection_version": 1,
                   "client_request_id": str(uuid4())}
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
        assert response.status_code == 202, response.text
        body = response.json()
        job_id = body["action"]["job_id"]
        change_id = body["action"]["change_set_id"]
        returned = next(op for op in body["operation_plan"]["operations"]
                        if op["related_job_id"] == job_id)
        # Invoke the actual live harness contract against the actual API response.
        validate_operation_binding(returned, canonical, collection["id"])
        assert returned["payload"]["selection_version"] == 1
        assert returned["payload"]["destination_collection_id"] == collection["id"]
        assert returned["related_change_set_id"] == change_id
        observations = [json.loads(item["output"]) for item in provider.observations[-1]
                        if item.get("type") == "function_call_output"]
        tool_operation = next(op for op in observations[-1]["operation_plan"]["operations"]
                              if op["id"] == returned["id"])
        assert tool_operation["payload"] == returned["payload"]
        assert observations[-1]["status"] == "queued"
        assert observations[-1]["requires_human_review"] is False

        workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
        persisted = next(op for op in workspace["operation_history"] if op["id"] == returned["id"])
        assert persisted["payload"] == returned["payload"]
        replay = await client.post(f"/api/v1/conversations/{cid}/messages", json=request)
        assert replay.status_code == 202, replay.text
        assert replay.json() == body

    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(returned["id"]))
        job = db.get(GenerationJob, UUID(job_id))
        change = db.get(CaseChangeSet, UUID(change_id))
        assert operation.related_job_id == job.id == change.generation_job_id
        assert operation.related_change_set_id == change.id
        assert change.conversation_id == operation.conversation_id == UUID(cid)
        assert job.input_payload["conversation_id"] == cid
        assert job.input_payload["conversation_operation_id"] == returned["id"]
        assert operation.payload["selection_version"] == 1
        assert operation.payload["destination_collection_id"] == collection["id"]
        assert change.status == "generating"
        assert db.get(CaseRecord, UUID(case["id"])).current_revision_id == UUID(
            case["current_revision_id"]
        )
