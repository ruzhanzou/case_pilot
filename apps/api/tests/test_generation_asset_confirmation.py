import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import GenerationJob, TestCase, WorkspaceTestBrief


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["select", "select_and_generate"])
async def test_selected_assets_form_new_collection_and_only_combined_mode_enqueues_planning(
    monkeypatch, mode
):
    dispatched = []
    monkeypatch.setattr(
        conversations, "enqueue_task", lambda *args, **kwargs: dispatched.append(args[1])
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"strategy-{uuid4().hex}@casepilot.test",
                    "display_name": "Strategy test",
                    "password": "CasePilot123!",
                },
            )
        ).json()
        space = account["spaces"][0]["id"]
        origin = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]
        case = (
            await client.post(
                f"/api/v1/collections/{origin['id']}/test-cases",
                json={
                    "title": "Login success",
                    "module": "Account system",
                    "priority": "P1",
                    "case_type": "functional",
                    "preconditions": ["Registered account"],
                    "steps": [{"action": "Login", "expected": "Success"}],
                },
            )
        ).json()
        target = (
            await client.post(
                f"/api/v1/spaces/{space}/collections", json={"name": "Selected output"}
            )
        ).json()
        workspace = (
            await client.post(
                "/api/v1/conversations", json={"collection_id": target["id"], "title": "Selection"}
            )
        ).json()
        cid, job_id = UUID(workspace["id"]), uuid4()
        source = {
            "key": f"asset:{case['id']}",
            "kind": "formal",
            "case_id": case["id"],
            "test_object_match": "same",
            "snapshot": case,
        }
        selection = {
            "status": "awaiting_confirmation",
            "strategy": mode,
            "job_id": str(job_id),
            "test_object": "Account system",
            "sources": [source],
        }
        with get_session_factory()() as db:
            db.add(
                GenerationJob(
                    id=job_id,
                    space_id=UUID(space),
                    account_id=UUID(account["id"]),
                    collection_id=UUID(target["id"]),
                    operation="draft_brief",
                    status="completed",
                    stage="completed",
                    input_payload={
                        "conversation_id": str(cid),
                        "generation_strategy": mode,
                        "prompt": "Account system",
                    },
                    output_payload={"test_brief": {"asset_selection": selection}},
                )
            )
            db.add(
                WorkspaceTestBrief(
                    conversation_id=cid,
                    version=1,
                    status="draft",
                    content={"test_object": "Account system", "asset_selection": selection},
                    created_by=UUID(account["id"]),
                )
            )
            db.commit()
        # Generic generation confirmation cannot bypass the pre-planning gate.
        blocked = await client.post(
            f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={"version": 1}
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "generation_asset_confirmation_required"
        invalid = await client.post(
            f"/api/v1/workspaces/{cid}/generation-assets/confirm",
            json={"version": 1, "case_ids": [str(uuid4())]},
        )
        assert invalid.status_code == 422
        assert dispatched == []
        endpoint = f"/api/v1/workspaces/{cid}/generation-assets/confirm"
        old_version = await client.post(endpoint, json={"version": 99, "case_ids": [case["id"]]})
        assert old_version.status_code == 409
        with get_session_factory()() as db:
            db.get(TestCase, UUID(case["id"])).deleted_at = datetime.now(UTC)
            db.commit()
        deleted = await client.post(endpoint, json={"version": 1, "case_ids": [case["id"]]})
        assert deleted.status_code == 409
        with get_session_factory()() as db:
            db.get(TestCase, UUID(case["id"])).deleted_at = None
            db.commit()
        if mode == "select":
            empty = await client.post(endpoint, json={"version": 1, "case_ids": []})
            assert empty.status_code == 422
        # Changing the test object or reviewed source snapshot must fail closed.
        with get_session_factory()() as db:
            brief = db.scalar(
                select(WorkspaceTestBrief).where(WorkspaceTestBrief.conversation_id == cid)
            )
            pristine = deepcopy(brief.content)
            brief.content = {**pristine, "test_object": "Another product"}
            db.commit()
        changed = await client.post(endpoint, json={"version": 1, "case_ids": [case["id"]]})
        assert changed.status_code == 409
        with get_session_factory()() as db:
            brief = db.scalar(
                select(WorkspaceTestBrief).where(WorkspaceTestBrief.conversation_id == cid)
            )
            stale = deepcopy(pristine)
            stale["asset_selection"]["sources"][0]["snapshot"]["current_revision_id"] = str(uuid4())
            brief.content = stale
            job = db.get(GenerationJob, job_id)
            job.output_payload = {"test_brief": {"asset_selection": stale["asset_selection"]}}
            db.commit()
        changed = await client.post(endpoint, json={"version": 1, "case_ids": [case["id"]]})
        assert changed.status_code == 409
        assert changed.json()["detail"] == "generation_asset_changed"
        with get_session_factory()() as db:
            brief = db.scalar(
                select(WorkspaceTestBrief).where(WorkspaceTestBrief.conversation_id == cid)
            )
            brief.content = pristine
            db.get(GenerationJob, job_id).output_payload = {
                "test_brief": {"asset_selection": pristine["asset_selection"]}
            }
            db.commit()
        # Two simultaneous confirmations must perform exactly one write / dispatch.
        responses = await asyncio.gather(
            *[
                client.post(endpoint, json={"version": 1, "case_ids": [case["id"], case["id"]]})
                for _ in range(2)
            ]
        )
        assert sorted(response.status_code for response in responses) == [200, 409]
        confirmed = next(response for response in responses if response.status_code == 200)
        assert confirmed.status_code == 200, confirmed.text
        target_cases = (await client.get(f"/api/v1/collections/{target['id']}/test-cases")).json()
        assert [item["id"] for item in target_cases] == ([case["id"]] if mode == "select" else [])
        assert dispatched == (
            ["casepilot.agent.draft_brief"] if mode == "select_and_generate" else []
        )
        if mode == "select":
            restored = (await client.get(f"/api/v1/conversations/{cid}")).json()
            assert restored["context"]["active_view"] == "list"
            assert confirmed.json()["assistant_message"]["metadata"]["action"] == "assets_selected"
        if mode == "select_and_generate":
            with get_session_factory()() as db:
                job = db.get(GenerationJob, UUID(confirmed.json()["action"]["job_id"]))
                assert job.input_payload["asset_selection_confirmed"] is True
                assert job.input_payload["confirmed_asset_sources"] == [source]
        replay = await client.post(
            f"/api/v1/workspaces/{cid}/generation-assets/confirm",
            json={"version": 1, "case_ids": [case["id"]]},
        )
        assert replay.status_code == 409
        if mode == "select":
            # Shared collection provenance survives reopening in another member's
            # workspace, without granting access to the author's conversation.
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as peer:
                email = f"provenance-{uuid4().hex}@casepilot.test"
                registered = await peer.post("/api/v1/auth/register", json={
                    "email": email, "password": "CasePilot123!", "display_name": "Peer"})
                assert registered.status_code == 201
                denied = await peer.get(f"/api/v1/conversations/{cid}")
                assert denied.status_code in {403, 404}
                invited = await client.post(f"/api/v1/spaces/{space}/members", json={
                    "email": email, "role": "member"})
                assert invited.status_code in {200, 201}
                reopened = await peer.put(f"/api/v1/collections/{target['id']}/workspace")
                assert reopened.status_code == 200, reopened.text
                assert reopened.json()["context"]["selected_asset_provenance"][case["id"]]["revision"] == case["current_revision_id"]


@pytest.mark.asyncio
async def test_select_launch_preserves_multiple_sources_and_requires_new_target(monkeypatch):
    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"launch-{uuid4().hex}@casepilot.test",
                    "display_name": "Launch test",
                    "password": "CasePilot123!",
                },
            )
        ).json()
        space = account["spaces"][0]["id"]
        source_ids, case_ids = [], []
        for index in range(2):
            collection = (
                await client.post(
                    f"/api/v1/spaces/{space}/collections", json={"name": f"Source {index}"}
                )
            ).json()
            source_ids.append(collection["id"])
            case = (
                await client.post(
                    f"/api/v1/collections/{collection['id']}/test-cases",
                    json={
                        "title": f"Scenario {index}",
                        "module": "Account",
                        "priority": "P1",
                        "case_type": "functional",
                        "preconditions": ["Ready"],
                        "steps": [{"action": "Login", "expected": "Success"}],
                    },
                )
            ).json()
            case_ids.append(case["id"])
        workspace = (
            await client.post(
                "/api/v1/conversations", json={"space_id": space, "title": "Selection"}
            )
        ).json()
        response = await client.post(
            f"/api/v1/conversations/{workspace['id']}/messages",
            json={
                "content": "策略：select。测试对象：账号系统，选用资产组成新集合",
                "intent_override": "CASE_GENERATE",
                "generation_strategy": "select",
                "source_collection_ids": source_ids,
            },
        )
        assert response.status_code == 202, response.text
        turn = response.json()
        assert turn["assistant_message"]["metadata"]["require_new_collection"] is True
        operation_id = turn["operation_plan"]["operations"][0]["id"]
        blocked = await client.post(
            f"/api/v1/conversation-operations/{operation_id}/confirm-collection",
            json={"collection_id": source_ids[0]},
        )
        assert blocked.status_code == 422
        bound = await client.post(
            f"/api/v1/conversation-operations/{operation_id}/confirm-collection",
            json={"create_collection_name": "New output"},
        )
        assert bound.status_code == 202, bound.text
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(bound.json()["action"]["job_id"]))
            assert job.input_payload["generation_strategy"] == "select"
            assert set(job.input_payload["source_collection_ids"]) == set(source_ids)
            assert {item["ref"] for item in job.input_payload["case_context"]} == set(case_ids)
            assert str(job.collection_id) not in source_ids
