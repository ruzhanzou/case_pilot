"""Real PG/API: each artifact retains the material authority that produced it."""

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_collection_references import source
from test_planning_review_lifecycle import PLAN, Provider
from test_workbench_bridge_integration import setup

from casepilot_api.collection_references import capture_reference_binding
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Conversation,
    ConversationMessage,
    ConversationOperation,
    GenerationJob,
    WorkspaceCandidate,
    WorkspaceTestBrief,
)
from casepilot_api.models import TestCase as CaseRecord
from casepilot_api.planning_review import execute
from casepilot_api.schemas import ConversationMessageCreate


async def change_material(client, kind, path, sid):
    if kind == "unbind":
        assert (
            await client.put(path, json={"base_version": 1, "source_ids": []})
        ).status_code == 200
    elif kind == "reindex":
        assert (await client.post(f"/api/v1/knowledge-sources/{sid}/reindex")).status_code == 202
    elif kind == "revoke":
        assert (await client.delete(f"/api/v1/knowledge-sources/{sid}")).status_code == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "unbind", "reindex", "revoke", "mixed"])
async def test_candidate_adoption_checks_each_job_material_atomically(change):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, ws = await setup(client)
        sid, _ = source(account)
        path = f"/api/v1/collections/{collection['id']}/references"
        assert (
            await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        ).status_code == 200
        ids = []
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(ws["id"]))
            stamp = capture_reference_binding(
                db, conv, ConversationMessageCreate(content="Generate")
            )
            for index in range(2):
                job = GenerationJob(
                    space_id=conv.space_id,
                    account_id=conv.account_id,
                    collection_id=conv.collection_id,
                    input_payload={
                        "conversation_id": str(conv.id),
                        "reference_binding": deepcopy(stamp),
                    },
                )
                db.add(job)
                db.flush()
                candidate = WorkspaceCandidate(
                    conversation_id=conv.id,
                    generation_job_id=job.id,
                    ref=f"material-{index}",
                    position=index,
                    snapshot={
                        "title": f"Case {index}",
                        "steps": [{"action": "Submit", "expected": "Accepted"}],
                    },
                )
                db.add(candidate)
                db.flush()
                ids.append(str(candidate.id))
            db.commit()
        await change_material(client, "unbind" if change == "mixed" else change, path, sid)
        if change == "mixed":
            with get_session_factory()() as db:
                conv = db.get(Conversation, UUID(ws["id"]))
                candidate = db.get(WorkspaceCandidate, UUID(ids[1]))
                job = db.get(GenerationJob, candidate.generation_job_id)
                job.input_payload = {
                    **job.input_payload,
                    "reference_binding": capture_reference_binding(
                        db, conv, ConversationMessageCreate(content="New generation")
                    ),
                }
                db.commit()
        response = await client.post(
            f"/api/v1/workspaces/{ws['id']}/candidates/commit",
            json={"candidate_ids": ids, "candidate_versions": {i: 1 for i in ids}},
        )
        assert response.status_code == (200 if change == "unchanged" else 409), response.text
        with get_session_factory()() as db:
            assert db.scalar(
                select(func.count())
                .select_from(CaseRecord)
                .where(CaseRecord.space_id == UUID(account["spaces"][0]["id"]))
            ) == (2 if change == "unchanged" else 0)
            statuses = list(
                db.scalars(
                    select(WorkspaceCandidate.status).where(
                        WorkspaceCandidate.id.in_(list(map(UUID, ids)))
                    )
                )
            )
            assert statuses == (
                ["incorporated"] * 2 if change == "unchanged" else ["candidate"] * 2
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "unbind", "reindex", "revoke"])
@pytest.mark.parametrize("with_operation", [False, True])
@pytest.mark.parametrize("boundary", ["review_apply", "brief_confirm", "saved_brief_confirm"])
async def test_review_revision_retains_collection_material_authority(
    change, boundary, with_operation
):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, ws = await setup(client)
        sid, _ = source(account)
        path = f"/api/v1/collections/{collection['id']}/references"
        await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        with get_session_factory()() as db:
            opid = None
            if with_operation:
                conv = db.get(Conversation, UUID(ws["id"]))
                message = ConversationMessage(conversation_id=conv.id, role="user", content="Plan")
                db.add(message)
                db.flush()
                operation = ConversationOperation(
                    conversation_id=conv.id,
                    message_id=message.id,
                    sequence=0,
                    intent="CASE_GENERATE",
                    status="completed",
                    payload={
                        "reference_binding": capture_reference_binding(
                            db, conv, ConversationMessageCreate(content="Plan")
                        )
                    },
                )
                db.add(operation)
                db.flush()
                opid = operation.id
            db.add(
                WorkspaceTestBrief(
                    conversation_id=UUID(ws["id"]),
                    version=1,
                    source_operation_id=opid,
                    status="draft",
                    created_by=UUID(account["id"]),
                    content={"test_object": "Synthetic", "planning": deepcopy(PLAN)},
                )
            )
            db.commit()
        url = f"/api/v1/workspaces/{ws['id']}/planning-reviews"
        response = await client.post(url, json={"base_version": 1})
        assert response.status_code == 202, response.text
        row = response.json()
        assert await asyncio.to_thread(execute, row["id"], "audit", Provider()) == "reviewed"
        assert (
            await client.post(
                f"{url}/{row['id']}/revise", json={"base_version": 1, "issue_ids": ["issue-1"]}
            )
        ).status_code == 200
        assert await asyncio.to_thread(execute, row["id"], "revision", Provider()) == "proposed"
        row = (await client.get(url)).json()[0]
        if boundary == "review_apply":
            await change_material(client, change, path, sid)
        applied = await client.post(
            f"{url}/{row['id']}/apply",
            json={"base_version": 1, "confirm": True, "proposal_hash": row["proposal_hash"]},
        )
        if boundary == "review_apply":
            assert applied.status_code == (200 if change == "unchanged" else 409), applied.text
        else:
            assert applied.status_code == 200, applied.text
            with get_session_factory()() as db:
                revised = db.get(WorkspaceTestBrief, UUID(applied.json()["applied_brief_id"]))
                assert revised.source_operation_id == opid
            version = 2
            if boundary == "saved_brief_confirm":
                for _ in range(2):
                    with get_session_factory()() as db:
                        latest = db.scalar(
                            select(WorkspaceTestBrief).where(
                                WorkspaceTestBrief.conversation_id == UUID(ws["id"]),
                                WorkspaceTestBrief.version == version,
                            )
                        )
                        content = deepcopy(latest.content)
                    saved = await client.post(
                        f"/api/v1/workspaces/{ws['id']}/test-briefs",
                        json={"base_version": version, "content": content},
                    )
                    assert saved.status_code == 201, saved.text
                    version += 1
            await change_material(client, change, path, sid)
            response = await client.post(
                f"/api/v1/workspaces/{ws['id']}/test-briefs/confirm", json={"version": version}
            )
            assert response.status_code == (202 if change == "unchanged" else 409), response.text
        with get_session_factory()() as db:
            assert db.scalar(
                select(func.count())
                .select_from(GenerationJob)
                .where(GenerationJob.collection_id == UUID(collection["id"]))
            ) == (
                1
                if boundary in {"brief_confirm", "saved_brief_confirm"} and change == "unchanged"
                else 0
            )
