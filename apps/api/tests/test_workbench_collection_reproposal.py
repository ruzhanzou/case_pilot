from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import setup
from test_workbench_collection_delete import approval_url, proposal

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseCollection


@pytest.mark.asyncio
async def test_member_change_reject_then_fresh_user_delete_proposal(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid, target = workspace["id"], collection["id"]

        async def seed(title):
            result = await client.post(
                f"/api/v1/collections/{target}/test-cases",
                json={"title": title, "steps": [{"action": "run", "expected": "pass"}]},
            )
            assert result.status_code == 201
            return result.json()

        case = await seed("first")
        selected = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
            },
        )
        assert selected.status_code == 200
        first = await proposal(client, monkeypatch, cid, target)
        assert first["impact"]["member_case_count"] == 1
        await seed("membership changed")
        stale = await client.post(
            approval_url(cid, first), json={"name": collection["name"], "collection_id": target}
        )
        assert stale.status_code == 409
        rejected = await client.post(
            approval_url(cid, first).removesuffix("confirm") + "reject", json={}
        )
        assert rejected.json() == {"status": "rejected"}
        fresh = await proposal(client, monkeypatch, cid, target)
        assert fresh["id"] != first["id"] and fresh["status"] == "pending"
        assert fresh["impact"]["member_case_count"] == 2
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(target)).deleted_at is None
        assert len((await client.get(f"/api/v1/collections/{target}/test-cases")).json()) == 2
