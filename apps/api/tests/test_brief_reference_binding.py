"""Every brief producer keeps a server-owned material snapshot; user content cannot clear it."""

from copy import deepcopy
from uuid import UUID

import pytest
from casepilot_agent.store import JobStore
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_collection_references import source
from test_planning_review_lifecycle import PLAN
from test_workbench_bridge_integration import setup

from casepilot_api.collection_references import capture_reference_binding
from casepilot_api.config import get_settings
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Conversation, WorkspaceTestBrief
from casepilot_api.schemas import ConversationMessageCreate


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["manual", "worker"])
@pytest.mark.parametrize("bound", [False, True])
async def test_initial_copy_and_reconcile_versions_keep_reference_guard(producer, bound):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, ws = await setup(client)
        url = f"/api/v1/workspaces/{ws['id']}/test-briefs"
        path = f"/api/v1/collections/{collection['id']}/references"
        if bound:
            sid, _ = source(account)
            assert (
                await client.put(path, json={"base_version": 0, "source_ids": [sid]})
            ).status_code == 200
        content = {"test_object": "Synthetic", "planning": deepcopy(PLAN)}
        if producer == "manual":
            result = await client.post(url, json={"content": content, "reference_binding": {}})
            assert result.status_code == 201, result.text
        else:
            with get_session_factory()() as db:
                conv = db.get(Conversation, UUID(ws["id"]))
                stamp = capture_reference_binding(
                    db, conv, ConversationMessageCreate(content="Plan")
                )
            settings = get_settings()
            store = JobStore(settings.database_url, settings.redis_url)
            with store.engine.begin() as connection:
                assert (
                    store.persist_test_brief(
                        connection,
                        {
                            "account_id": UUID(account["id"]),
                            "input_payload": {
                                "conversation_id": ws["id"],
                                "reference_binding": stamp,
                            },
                        },
                        content,
                    )
                    == 1
                )
        for version in [1, 2]:
            # Same-content copy and incremental edit both create a new ordinary draft.
            if version == 2:
                content["planning"]["test_points"][0]["objective"] = "Clarified expected outcome"
            result = await client.post(
                url, json={"base_version": version, "content": content, "reference_binding": {}}
            )
            assert result.status_code == 201, result.text
        with get_session_factory()() as db:
            briefs = list(
                db.scalars(
                    select(WorkspaceTestBrief)
                    .where(WorkspaceTestBrief.conversation_id == UUID(ws["id"]))
                    .order_by(WorkspaceTestBrief.version)
                )
            )
            assert len(briefs) == 3
            assert all(b.reference_binding["schema_version"] == 1 for b in briefs)
            assert all(
                b.reference_binding["bound_source_ids"] == ([sid] if bound else []) for b in briefs
            )
        if bound:
            await client.put(path, json={"base_version": 1, "source_ids": []})
            failed_save = await client.post(url, json={"base_version": 3, "content": content})
            assert failed_save.status_code == 409
        confirmed = await client.post(url + "/confirm", json={"version": 3})
        assert confirmed.status_code == (409 if bound else 202), confirmed.text


@pytest.mark.asyncio
async def test_manual_source_reference_does_not_grant_foreign_access():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as owner:
        account, _, _ = await setup(owner)
        sid, did = source(account, temporary=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        _, _, ws = await setup(other)
        plan = deepcopy(PLAN)
        plan["test_points"][0]["source_refs"][0].update(source_id=sid, document_id=did)
        result = await other.post(
            f"/api/v1/workspaces/{ws['id']}/test-briefs",
            json={"content": {"test_object": "Synthetic", "planning": plan}},
        )
        assert result.status_code == 404
        with get_session_factory()() as db:
            assert (
                db.scalar(
                    select(WorkspaceTestBrief).where(
                        WorkspaceTestBrief.conversation_id == UUID(ws["id"])
                    )
                )
                is None
            )
