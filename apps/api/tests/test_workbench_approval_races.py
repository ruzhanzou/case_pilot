"""Two-session barriers prove approval reloads canonical state before any write."""

import asyncio
import threading
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    CollectionCaseMembership,
    Conversation,
    GenerationJob,
    WorkspaceTestBrief,
)
from casepilot_api.schemas import GenerationAssetConfirmRequest


@pytest.mark.asyncio
async def test_asset_approval_reloads_destination_after_concurrent_selection(monkeypatch):
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **kw: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"asset-race-{uuid4().hex}@casepilot.test",
                    "display_name": "Race",
                    "password": "CasePilot123!",
                },
            )
        ).json()
        space = user["spaces"][0]["id"]
        collections = []
        for name in ["Origin", "Destination A", "Destination B"]:
            collections.append(
                (
                    await client.post(f"/api/v1/spaces/{space}/collections", json={"name": name})
                ).json()
            )
        origin, destination, replacement = collections
        case = (
            await client.post(
                f"/api/v1/collections/{origin['id']}/test-cases",
                json={
                    "title": "Existing case",
                    "module": "Account",
                    "steps": [{"action": "Login", "expected": "Success"}],
                },
            )
        ).json()
        conversation = (
            await client.post(
                "/api/v1/conversations",
                json={
                    "collection_id": destination["id"],
                },
            )
        ).json()
        cid, job_id = UUID(conversation["id"]), uuid4()
        selection = {
            "status": "awaiting_confirmation",
            "strategy": "select",
            "job_id": str(job_id),
            "test_object": "Account",
            "sources": [
                {
                    "key": f"asset:{case['id']}",
                    "kind": "formal",
                    "case_id": case["id"],
                    "test_object_match": "same",
                    "snapshot": case,
                }
            ],
        }
        with get_session_factory()() as db:
            db.add(
                GenerationJob(
                    id=job_id,
                    space_id=UUID(space),
                    account_id=UUID(user["id"]),
                    collection_id=UUID(destination["id"]),
                    operation="draft_brief",
                    status="completed",
                    stage="completed",
                    input_payload={"conversation_id": str(cid)},
                    output_payload={"test_brief": {"asset_selection": selection}},
                )
            )
            db.add(
                WorkspaceTestBrief(
                    conversation_id=cid,
                    version=1,
                    status="draft",
                    content={"test_object": "Account", "asset_selection": selection},
                    created_by=UUID(user["id"]),
                )
            )
            db.commit()
        loaded, release = threading.Event(), threading.Event()
        approval_session = []
        original_ensure = conversations._ensure_conversation

        def paused_ensure(db, account_id, conversation_id):
            value = original_ensure(db, account_id, conversation_id)
            if approval_session and db is approval_session[0] and not loaded.is_set():
                assert value.collection_id == UUID(destination["id"])
                loaded.set()
                assert release.wait(10), "selection session did not release approval"
            return value

        monkeypatch.setattr(conversations, "_ensure_conversation", paused_ensure)

        def approve():
            with get_session_factory()() as db:
                approval_session.append(db)
                account = db.get(Account, UUID(user["id"]))
                try:
                    conversations.confirm_generation_assets(
                        cid,
                        GenerationAssetConfirmRequest(version=1, case_ids=[case["id"]]),
                        account,
                        db,
                    )
                except HTTPException as error:
                    db.rollback()
                    return error.status_code, error.detail
                raise AssertionError("stale destination approval wrote assets")

        task = asyncio.create_task(asyncio.to_thread(approve))
        try:
            if not await asyncio.to_thread(loaded.wait, 5):
                await task
                raise AssertionError("approval did not reach the read barrier")
            changed = await client.patch(
                f"/api/v1/workspaces/{cid}/selection",
                json={
                    "base_version": 0,
                    "action": "clear",
                    "active_collection_id": replacement["id"],
                },
            )
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        assert await task == (409, "workbench_destination_changed")
        with get_session_factory()() as db:
            current = db.get(Conversation, cid)
            assert current.collection_id == UUID(replacement["id"])
            assert current.context["workbench_selection"]["version"] == 1
            for collection in [destination, replacement]:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(CollectionCaseMembership)
                        .where(CollectionCaseMembership.collection_id == UUID(collection["id"]))
                    )
                    == 0
                )
            brief = db.scalar(
                select(WorkspaceTestBrief).where(WorkspaceTestBrief.conversation_id == cid)
            )
            assert brief.status == "draft"
