"""Existing collection rename uses a bounded row token, not nonexistent updated_at."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseCollection, Conversation


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [None, "aba", "expired"])
async def test_exact_rename_row_revision_and_expiry(monkeypatch, conflict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        activate(
            monkeypatch,
            [
                (
                    "rename_collection",
                    {
                        "collection_id": collection["id"],
                        "name": "Approved name",
                    },
                )
            ],
        )
        turn = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "重命名集合",
                "client_request_id": str(uuid4()),
            },
        )
        assert turn.status_code == 202, turn.text
        assert "proposal" in turn.json()["action"], turn.text
        proposed = turn.json()["action"]["proposal"]
        assert proposed["base_updated_at"].startswith("xmin:")
        assert datetime.fromisoformat(proposed["expires_at"]) > datetime.now(UTC)
        if conflict == "aba":
            for name in ("Intervening", collection["name"]):
                response = await client.patch(
                    f"/api/v1/collections/{collection['id']}", json={"name": name}
                )
                assert response.status_code == 200
        elif conflict == "expired":
            with get_session_factory()() as db:
                conversation = db.get(Conversation, UUID(cid))
                expired = {
                    **proposed,
                    "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                }
                conversation.context = {
                    **dict(conversation.context),
                    "workbench_collection_proposal": expired,
                }
                db.commit()
        url = f"/api/v1/workspaces/{cid}/collection-proposals/{proposed['id']}/confirm"
        request = {"name": proposed["name"], "collection_id": collection["id"]}
        response = await client.post(url, json=request)
        if conflict:
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == (
                "collection_proposal_stale" if conflict == "aba" else "collection_proposal_expired"
            )
        else:
            assert response.status_code == 200, response.text
            assert response.json()["name"] == "Approved name"
            replay = await client.post(url, json=request)
            assert replay.json() == response.json()
        with get_session_factory()() as db:
            actual = db.get(CaseCollection, UUID(collection["id"]))
            assert actual.name == (collection["name"] if conflict else "Approved name")
