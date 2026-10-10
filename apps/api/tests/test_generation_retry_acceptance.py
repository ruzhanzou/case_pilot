"""Retry a confirmed generation without losing its identity or reviving stale work."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api import generation
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Conversation, GenerationJob, Space, WorkspaceTestBrief


@pytest.mark.parametrize("operation", ["generate", "draft_brief"])
@pytest.mark.asyncio
async def test_retry_restores_failed_context_and_rejects_duplicate_or_changed_brief(
    monkeypatch, operation,
):
    enqueued = []
    monkeypatch.setattr(generation, "enqueue_task", lambda *args, **kwargs: enqueued.append(args))
    account_id = space_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registration = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"retry-{uuid4().hex}@casepilot.test",
                    "display_name": "Retry acceptance",
                    "password": "CasePilot123!",
                },
            )
            assert registration.status_code == 201
            account_id = UUID(registration.json()["id"])
            space_id = UUID(registration.json()["spaces"][0]["id"])
            collection = (await client.get(f"/api/v1/spaces/{space_id}/collections")).json()[0]
            workspace = (
                await client.put(f"/api/v1/collections/{collection['id']}/workspace")
            ).json()
            cid = UUID(workspace["id"])
            with get_session_factory()() as db:
                conversation = db.get(Conversation, cid)
                conversation.context = {
                    **conversation.context,
                    "phase": "brief_review",
                    "active_job_id": None,
                    "active_operation_id": None,
                    "confirmed_brief_version": 1,
                }
                job = GenerationJob(
                    space_id=space_id,
                    account_id=account_id,
                    collection_id=UUID(collection["id"]),
                    operation=operation,
                    status="failed",
                    stage="failed",
                    input_payload={"conversation_id": str(cid), "confirmed_test_brief_version": 1},
                    output_payload={},
                    error_code="RateLimitError",
                )
                db.add(job)
                db.commit()
                job_id = job.id
            response = await client.post(f"/api/v1/generation-jobs/{job_id}/retry")
            assert response.status_code == 202, response.text
            assert len(enqueued) == 1
            with get_session_factory()() as db:
                conversation = db.get(Conversation, cid)
                assert conversation.context["phase"] == (
                    "brief_drafting" if operation == "draft_brief" else "generating"
                )
                assert enqueued[0][1] == (
                    "casepilot.agent.draft_brief" if operation == "draft_brief"
                    else "casepilot.agent.generate"
                )
                assert conversation.context["active_job_id"] == str(job_id)
            response = await client.post(f"/api/v1/generation-jobs/{job_id}/retry")
            assert response.status_code == 409
            assert len(enqueued) == 1
            with get_session_factory()() as db:
                job = db.get(GenerationJob, job_id)
                job.status = "failed"
                conversation = db.get(Conversation, cid)
                conversation.context = {
                    **conversation.context,
                    "active_job_id": None,
                    "confirmed_brief_version": 2,
                }
                if operation == "draft_brief":
                    db.add(WorkspaceTestBrief(conversation_id=cid, version=1, content={}))
                db.commit()
            response = await client.post(f"/api/v1/generation-jobs/{job_id}/retry")
            assert response.status_code == 409
            assert response.json()["detail"] == "retry_context_mismatch"
            assert len(enqueued) == 1
    finally:
        if space_id and account_id:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == space_id))
                db.execute(delete(Account).where(Account.id == account_id))
                db.commit()
