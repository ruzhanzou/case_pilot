"""Exercise generation replacement and reuse adoption against the persisted workspace."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from casepilot_agent.store import JobStore, workspace_candidates
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import GenerationJob, WorkspaceCandidate, WorkspaceTestBrief


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["suggested", "copy", "stale"])
async def test_partial_generation_preserves_siblings_and_commit_reuses_only_live_assets(choice):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registration = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"boundaries-{uuid4().hex}@casepilot.test",
                "display_name": "Generation boundaries",
                "password": "CasePilot123!",
            },
        )
        assert registration.status_code == 201
        account = registration.json()
        space = account["spaces"][0]["id"]
        collection = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]
        case = (
            await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": "有效验证码",
                    "module": "登录",
                    "priority": "P0",
                    "case_type": "功能",
                    "preconditions": ["已发送验证码"],
                    "steps": [{"action": "提交有效验证码", "expected": "登录成功"}],
                },
            )
        ).json()
        workspace = (await client.put(f"/api/v1/collections/{collection['id']}/workspace")).json()
        cid = UUID(workspace["id"])
        points = [
            {"id": point, "title": point, "feature_point_ids": ["F1"]} for point in ["P1", "P2"]
        ]
        source = {
            "key": f"asset:{case['id']}",
            "kind": "formal",
            "case_id": case["id"],
            "revision": case["current_revision_id"],
            "snapshot": case,
        }
        plan = {
            "feature_points": [{"id": "F1", "name": "验证码", "module": "登录"}],
            "test_points": points,
            "reuse": {
                "strategy": "regression",
                "user_choices": {"P1": "copy"} if choice == "copy" else {},
                "decisions": [
                    {"point_id": p["id"], "action": "reuse", "source": source} for p in points
                ],
            },
        }
        snapshot = {
            key: case[key]
            for key in (
                "title",
                "module",
                "priority",
                "case_type",
                "preconditions",
                "steps",
                "tags",
            )
        }
        snapshot.update(id="old", test_point_ids=["P1", "P2"])
        with get_session_factory()() as db:
            brief = WorkspaceTestBrief(
                conversation_id=cid, version=1, content={"planning": plan}, status="confirmed"
            )
            db.add(brief)
            job = GenerationJob(
                space_id=UUID(space),
                account_id=UUID(account["id"]),
                collection_id=UUID(collection["id"]),
                operation="generate",
                status="completed",
                stage="completed",
                input_payload={
                    "conversation_id": str(cid),
                    "confirmed_test_brief_version": 1,
                    "confirmed_plan": {**plan, "test_points": [points[0]]},
                },
                output_payload={},
            )
            db.add(job)
            db.flush()
            job_id = job.id
            old = WorkspaceCandidate(
                conversation_id=cid,
                generation_job_id=job.id,
                ref="old",
                version=1,
                position=0,
                snapshot=snapshot,
                status="candidate",
                included=True,
            )
            db.add(old)
            db.commit()
            old_id = old.id
        store = JobStore(conversations.settings.database_url, conversations.settings.redis_url)
        draft = {**deepcopy(snapshot), "id": "old", "test_point_ids": ["P1"]}
        with store.connection() as connection:
            matches = store.search_reuse_cases(connection, space_id=UUID(space), terms=["登录成功"])
            assert [item["ref"] for item in matches] == [case["id"]]
            loaded = store.get_job(connection, job_id)
            store.persist_workspace_candidates(connection, loaded, [])
            unchanged = (
                connection.execute(
                    select(workspace_candidates).where(workspace_candidates.c.id == old_id)
                )
                .mappings()
                .one()
            )
            assert unchanged["snapshot"]["test_point_ids"] == ["P1", "P2"]
            store.persist_workspace_previews(connection, loaded, [draft])
            # Identical progress must not rewrite the existing preview.
            query = select(workspace_candidates).where(
                workspace_candidates.c.generation_job_id == job_id,
                workspace_candidates.c.ref == "old",
                workspace_candidates.c.status == "generating",
            )
            preview = connection.execute(query).mappings().one()
            store.persist_workspace_previews(connection, loaded, [draft])
            assert connection.execute(query).mappings().one()["updated_at"] == preview["updated_at"]
            ids = store.persist_workspace_candidates(connection, loaded, [draft])
        with get_session_factory()() as db:
            retained = db.get(WorkspaceCandidate, old_id)
            assert retained.status == "candidate" and retained.snapshot["test_point_ids"] == ["P2"]
            assert retained.version == 2
            assert retained.ref != draft["id"]
        if choice == "stale":
            edited = await client.patch(
                f"/api/v1/test-cases/{case['id']}",
                json={
                    **case,
                    "title": "人工更新标题",
                    "base_revision_id": case["current_revision_id"],
                },
            )
            assert edited.status_code == 200, edited.text
        result = await client.post(
            f"/api/v1/workspaces/{cid}/candidates/commit", json={"candidate_ids": ids}
        )
        if choice == "stale":
            assert result.status_code == 409, result.text
            return
        assert result.status_code == 200, result.text
        assert (result.json()[0]["id"] == case["id"]) == (choice == "suggested")
        after = (await client.get(f"/api/v1/collections/{collection['id']}/test-cases")).json()
        assert len(after) == (1 if choice == "suggested" else 2)
        original = next(item for item in after if item["id"] == case["id"])
        assert original["current_revision_id"] == case["current_revision_id"]
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert any(
            link["test_point_id"] == "P1" and link["test_case_id"] == result.json()[0]["id"]
            for link in state["planning_case_links"]
        )
