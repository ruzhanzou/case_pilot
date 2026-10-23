import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    CaseCollection,
    ConversationMessage,
    ConversationOperation,
    GenerationJob,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("create_new", [True, False])
@pytest.mark.parametrize("concurrent", [True, False])
@pytest.mark.parametrize("completed", [True, False])
async def test_collection_confirmation_replay_preserves_original_task(
    monkeypatch, create_new, concurrent, completed
):
    dispatched = []
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **k: dispatched.append(a[1]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"confirmation-{uuid4().hex}@casepilot.test",
                    "display_name": "Replay test",
                    "password": "CasePilot123!",
                },
            )
        ).json()
        space = account["spaces"][0]["id"]
        workspace = (await client.post("/api/v1/conversations", json={"space_id": space})).json()
        cid = workspace["id"]
        response = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={
                "content": "为账号登录生成1条测试用例",
                "intent_override": "CASE_GENERATE",
            },
        )
        assert response.status_code == 202, response.text
        op_id = response.json()["operation_plan"]["current_operation_id"]
        choice = {"create_collection_name": f"Replay {uuid4().hex}"}
        if not create_new:
            collection = (
                await client.post(f"/api/v1/spaces/{space}/collections", json={"name": "Existing"})
            ).json()
            choice = {"collection_id": collection["id"]}
        url = f"/api/v1/conversation-operations/{op_id}/confirm-collection"
        if concurrent:
            first, simultaneous = await asyncio.gather(
                client.post(url, json=choice),
                client.post(url, json=choice),
            )
            assert simultaneous.status_code == 202, simultaneous.text
            assert simultaneous.json()["action"] == first.json()["action"]
        else:
            first = await client.post(url, json=choice)
        assert first.status_code == 202, first.text
        assert len(dispatched) == 1

        def counts():
            with get_session_factory()() as db:
                return (
                    db.scalar(
                        select(func.count())
                        .select_from(CaseCollection)
                        .where(CaseCollection.space_id == UUID(space))
                    ),
                    db.scalar(
                        select(func.count())
                        .select_from(ConversationMessage)
                        .where(ConversationMessage.conversation_id == UUID(cid))
                    ),
                    db.scalar(
                        select(func.count())
                        .select_from(GenerationJob)
                        .where(GenerationJob.space_id == UUID(space))
                    ),
                    len(dispatched),
                )

        if completed:
            with get_session_factory()() as db:
                operation = db.get(ConversationOperation, UUID(op_id))
                operation.status = "completed"
                operation.result = {"completed_by_worker": True}
                db.get(GenerationJob, operation.related_job_id).status = "completed"
                db.get(
                    ConversationMessage, UUID(first.json()["assistant_message"]["id"])
                ).status = "completed"
                db.commit()
        before = counts()
        replay = await client.post(url, json=choice)
        assert replay.status_code == 202, replay.text
        assert replay.json()["action"] == first.json()["action"]
        assert replay.json()["assistant_message"]["id"] == first.json()["assistant_message"]["id"]
        assert replay.json()["conversation_id"] == cid
        assert counts() == before
        conflict = await client.post(url, json={"create_collection_name": "Different choice"})
        assert conflict.status_code == 409
        assert counts() == before
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as peer:
            await peer.post(
                "/api/v1/auth/register",
                json={
                    "email": f"peer-{uuid4().hex}@casepilot.test",
                    "display_name": "Peer",
                    "password": "CasePilot123!",
                },
            )
            denied = await peer.post(url, json=choice)
            assert denied.status_code in {403, 404}
        assert counts() == before
