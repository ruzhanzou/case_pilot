"""Old audit hashes fail closed; explicit new work does not recycle the old budget."""

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest
from casepilot_agent.planning_review import digest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_collection_references import source
from test_planning_review_lifecycle import PLAN, Provider
from test_workbench_bridge_integration import setup

from casepilot_api.collection_references import capture_reference_binding
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Conversation, GenerationJob, PlanningReview, WorkspaceTestBrief
from casepilot_api.planning_review import execute
from casepilot_api.schemas import ConversationMessageCreate


@pytest.mark.asyncio
async def test_legacy_material_hash_invalidates_without_budget_reset_and_new_session_can_review():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, ws = await setup(client)
        sid, _ = source(account)
        bound = await client.put(
            f"/api/v1/collections/{collection['id']}/references",
            json={"base_version": 0, "source_ids": [sid]},
        )
        assert bound.status_code == 200
        content = {"test_object": "Synthetic", "planning": deepcopy(PLAN)}
        assert (
            await client.post(
                f"/api/v1/workspaces/{ws['id']}/test-briefs", json={"content": content}
            )
        ).status_code == 201
        url = f"/api/v1/workspaces/{ws['id']}/planning-reviews"
        row = (await client.post(url, json={"base_version": 1})).json()
        assert await asyncio.to_thread(execute, row["id"], "audit", Provider()) == "reviewed"
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(ws["id"]))
            review = db.get(PlanningReview, UUID(row["id"]))
            brief = db.get(WorkspaceTestBrief, review.brief_id)
            # Exact pre-0040 shape for a plan with only user-input citations:
            # automatic collection materials were in reference_binding, not sources.
            legacy = digest(
                {
                    "brief": str(brief.id),
                    "version": brief.version,
                    "status": brief.status,
                    "content": brief.content,
                    "sources": [],
                    "reference_binding": capture_reference_binding(
                        db, conv, ConversationMessageCreate(content="Review authority")
                    ),
                    "collection": str(conv.collection_id),
                    "selection": (conv.context or {}).get("workbench_selection"),
                }
            )
            assert legacy != review.binding
            review.binding = legacy
            brief.reference_binding = {}  # Migration default, never fabricated authority.
            db.commit()
        old = (await client.get(url)).json()[0]
        assert old["status"] == "invalidated" and old["requests_used"] == 1
        retry = (await client.post(url, json={"base_version": 1})).json()
        assert retry["id"] == row["id"] and retry["requests_used"] == 1
        assert await asyncio.to_thread(execute, row["id"], "audit", Provider()) == "ignored"
        # A real user starts a NEW conversation and explicitly supplies a new plan.
        fresh = (
            await client.post("/api/v1/conversations", json={"collection_id": collection["id"]})
        ).json()
        assert (
            await client.post(
                f"/api/v1/workspaces/{fresh['id']}/test-briefs", json={"content": content}
            )
        ).status_code == 201
        new_url = f"/api/v1/workspaces/{fresh['id']}/planning-reviews"
        new = (await client.post(new_url, json={"base_version": 1})).json()
        assert new["id"] != row["id"] and new["requests_used"] == 0
        assert await asyncio.to_thread(execute, new["id"], "audit", Provider()) == "reviewed"
        with get_session_factory()() as db:
            assert db.get(PlanningReview, UUID(row["id"])).requests_used == 1
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(GenerationJob)
                    .where(GenerationJob.collection_id == UUID(collection["id"]))
                )
                == 0
            )
