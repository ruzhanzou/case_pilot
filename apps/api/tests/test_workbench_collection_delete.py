"""Real database approval, replay and NOWAIT boundaries for collection soft deletion."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    AuditEvent,
    CaseCollection,
    CollectionCaseMembership,
    Conversation,
    SpaceMembership,
    WorkspaceCandidate,
)
from casepilot_api.models import (
    TestCase as CaseRecord,
)
from casepilot_api.models import (
    TestCaseRevision as Revision,
)


async def proposal(client, monkeypatch, cid, collection_id):
    activate(monkeypatch, [("delete_collection", {"collection_id": collection_id})])
    response = await client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={
            "content": "软删除这个集合，保留用例",
            "client_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    assert "proposal" in response.json()["action"], response.text
    return response.json()["action"]["proposal"]


def approval_url(cid, proposed):
    return f"/api/v1/workspaces/{cid}/collection-proposals/{proposed['id']}/confirm"


@pytest.mark.asyncio
async def test_soft_delete_exact_approval_preserves_assets_and_cleans_all_affected(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        sid, cid = account["spaces"][0]["id"], workspace["id"]
        other = (
            await client.post(f"/api/v1/spaces/{sid}/collections", json={"name": "Keep"})
        ).json()
        cases = []
        for title in ("Shared", "Target only"):
            response = await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": title,
                    "steps": [{"action": "Run", "expected": "Pass"}],
                },
            )
            assert response.status_code == 201, response.text
            cases.append(response.json())
        source_workspace = (
            await client.post(
                "/api/v1/conversations",
                json={
                    "collection_id": other["id"],
                },
            )
        ).json()
        with get_session_factory()() as db:
            db.add(
                CollectionCaseMembership(
                    collection_id=UUID(other["id"]),
                    test_case_id=UUID(cases[0]["id"]),
                    position=0,
                )
            )
            db.commit()
        for target in (cid, source_workspace["id"]):
            selected = await client.patch(
                f"/api/v1/workspaces/{target}/selection",
                json={
                    "base_version": 0,
                    "sources": [
                        {"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}
                        for case in cases
                    ],
                },
            )
            assert selected.status_code == 200, selected.text
        # Shared collection impact includes another owner's private workspace.
        with get_session_factory()() as db:
            other_owner = Account(
                email=f"private-{uuid4().hex}@test",
                display_name="Private",
                password_hash="x",
            )
            db.add(other_owner)
            db.flush()
            db.add(SpaceMembership(space_id=UUID(sid), account_id=other_owner.id, role="member"))
            private = db.get(Conversation, UUID(source_workspace["id"]))
            private.account_id = other_owner.id
            private.title = "Private conversation title must not leak"
            draft = WorkspaceCandidate(
                conversation_id=private.id,
                ref="keep-draft",
                version=3,
                position=0,
                status="candidate",
                included=False,
                created_by=other_owner.id,
                snapshot={"title": "Private draft", "steps": []},
            )
            db.add(draft)
            canonical = dict(private.context)["workbench_selection"]
            private.context = {
                **dict(private.context),
                "workbench_selection": {
                    **canonical,
                    "items": [
                        *canonical["items"],
                        {
                            "ref": "candidate:keep-draft",
                            "kind": "candidate",
                            "version": "3",
                            "candidate_ref": "keep-draft",
                            "label": "Private draft",
                        },
                    ],
                },
                "workbench_collection_proposal": {
                    "id": str(uuid4()),
                    "status": "pending",
                    "action": "rename",
                    "collection_id": other["id"],
                    "name": "Private proposed name",
                    "destination_collection_id": other["id"],
                },
            }
            db.commit()
        proposed = await proposal(client, monkeypatch, cid, collection["id"])
        assert source_workspace["id"] not in str(proposed)
        assert "Private conversation title" not in str(proposed)
        assert proposed["name"] == collection["name"]
        assert proposed["impact"] == {"member_case_count": 2, "affected_conversation_count": 2}
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert "_workbench_collection_delete_impact" not in state["context"]
        url = approval_url(cid, proposed)
        wrong = await client.post(url, json={"name": "wrong", "collection_id": collection["id"]})
        assert wrong.status_code == 409
        with get_session_factory()() as db:
            before_revisions = db.scalar(select(func.count()).select_from(Revision))
            before_memberships = db.scalar(
                select(func.count()).select_from(CollectionCaseMembership)
            )
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None
        approved = await client.post(
            url, json={"name": proposed["name"], "collection_id": collection["id"]}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["deleted"] and approved.json()["preserved_assets"]
        replay = await client.post(
            url, json={"name": proposed["name"], "collection_id": collection["id"]}
        )
        assert replay.json() == approved.json()
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is not None
            assert db.scalar(select(func.count()).select_from(Revision)) == before_revisions
            assert (
                db.scalar(select(func.count()).select_from(CollectionCaseMembership))
                == before_memberships
            )
            audits = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id == UUID(collection["id"]),
                        AuditEvent.action == "collection.deleted",
                    )
                )
            )
            assert len(audits) == 1
            for case in cases:
                assert db.get(CaseRecord, UUID(case["id"])).deleted_at is None
        for target in (cid, source_workspace["id"]):
            with get_session_factory()() as db:
                row = db.get(Conversation, UUID(target))
                state = {
                    "context": row.context,
                    "collection_id": str(row.collection_id) if row.collection_id else None,
                }
            canonical = state["context"]["workbench_selection"]
            assert canonical["version"] == 2
            assert [item["case_id"] for item in canonical["items"] if item["kind"] == "asset"] == [
                cases[0]["id"]
            ]
            assert canonical["items"][0]["version"] == cases[0]["current_revision_id"]
            assert canonical["items"][0]["collection_ids"] == [other["id"]]
            if target != cid:
                assert canonical["items"][1]["ref"] == "candidate:keep-draft"
                assert canonical["items"][1]["version"] == "3"
                assert state["context"]["workbench_collection_proposal"]["status"] == "invalidated"
            assert state["collection_id"] == (None if target == cid else other["id"])
            assert canonical["active_collection_id"] == (None if target == cid else other["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["locked", "changed"])
async def test_soft_delete_nowait_or_changed_impact_is_zero_write(monkeypatch, conflict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        affected = (
            await client.post(
                "/api/v1/conversations",
                json={
                    "collection_id": collection["id"],
                },
            )
        ).json()
        proposed = await proposal(client, monkeypatch, cid, collection["id"])
        with get_session_factory()() as blocker:
            row = blocker.get(Conversation, UUID(affected["id"]))
            if conflict == "locked":
                blocker.refresh(row, with_for_update=True)
            else:
                row.context = {
                    **dict(row.context),
                    "workbench_selection": {
                        "version": 1,
                        "items": [],
                        "active_collection_id": collection["id"],
                    },
                }
                blocker.commit()
            import asyncio

            response = await asyncio.wait_for(
                client.post(
                    approval_url(cid, proposed),
                    json={
                        "name": proposed["name"],
                        "collection_id": collection["id"],
                    },
                ),
                timeout=3,
            )
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == (
                "collection_impact_busy" if conflict == "locked" else "collection_impact_changed"
            )
            blocker.rollback()
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None
            assert db.get(Conversation, UUID(affected["id"])).collection_id == UUID(
                collection["id"]
            )
            assert not list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id == UUID(collection["id"]),
                        AuditEvent.action == "collection.deleted",
                    )
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("linked_message", [True, False])
async def test_collection_delete_active_job_and_foreign_target_are_rejected(
    monkeypatch, linked_message
):
    from casepilot_api.models import ConversationMessage, GenerationJob

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        cid = workspace["id"]
        affected = (
            await client.post(
                "/api/v1/conversations",
                json={
                    "collection_id": collection["id"],
                },
            )
        ).json()
        proposed = await proposal(client, monkeypatch, cid, collection["id"])
        with get_session_factory()() as db:
            job = GenerationJob(
                space_id=UUID(workspace["space_id"]),
                account_id=UUID(account["id"]),
                collection_id=UUID(collection["id"]),
                status="running",
            )
            db.add(job)
            db.flush()
            if linked_message:
                db.add(
                    ConversationMessage(
                        conversation_id=UUID(affected["id"]),
                        role="assistant",
                        content="Working",
                        related_job_id=job.id,
                    )
                )
            db.commit()
        response = await client.post(
            approval_url(cid, proposed),
            json={
                "name": proposed["name"],
                "collection_id": collection["id"],
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "conversation_task_running"
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None
        rejected = await client.post(
            f"/api/v1/workspaces/{cid}/collection-proposals/{proposed['id']}/reject",
        )
        assert rejected.status_code == 200
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as foreign:
            _, other, _ = await setup(foreign)
            activate(monkeypatch, [("delete_collection", {"collection_id": other["id"]})])
            response = await client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={
                    "content": "删除这个集合",
                    "client_request_id": str(uuid4()),
                },
            )
            assert response.status_code == 202
            assert response.json()["action"].get("type") != "collection_proposal"
            with get_session_factory()() as db:
                assert db.get(CaseCollection, UUID(other["id"])).deleted_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["rename", "delete"])
async def test_collection_revision_token_rejects_rename_away_and_back(monkeypatch, action):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        if action == "delete":
            proposed = await proposal(client, monkeypatch, cid, collection["id"])
        else:
            activate(
                monkeypatch,
                [
                    (
                        "rename_collection",
                        {
                            "collection_id": collection["id"],
                            "name": "Approved next name",
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
            proposed = turn.json()["action"]["proposal"]
        assert proposed["base_updated_at"].startswith("xmin:")
        for name in ("Temporary intervening name", collection["name"]):
            changed = await client.patch(
                f"/api/v1/collections/{collection['id']}", json={"name": name}
            )
            assert changed.status_code == 200
        response = await client.post(
            approval_url(cid, proposed),
            json={
                "name": proposed["name"],
                "collection_id": collection["id"],
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "collection_proposal_stale"
        with get_session_factory()() as db:
            row = db.get(CaseCollection, UUID(collection["id"]))
            assert row.name == collection["name"] and row.deleted_at is None


@pytest.mark.asyncio
async def test_delete_locks_prevent_new_conversation_and_source_selection_phantoms(monkeypatch):
    import asyncio
    import threading

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from casepilot_api import case_management
    from casepilot_api.workbench_selection import SelectionUpdate, update_selection

    entered, release = threading.Event(), threading.Event()
    original_delete = case_management.delete_collection

    def paused_delete(*args, **kwargs):
        entered.set()  # All space/collection/conversation locks are acquired.
        assert release.wait(10)
        return original_delete(*args, **kwargs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, workspace = await setup(client)
        cid, sid = workspace["id"], workspace["space_id"]
        other = (
            await client.post(f"/api/v1/spaces/{sid}/collections", json={"name": "Keep"})
        ).json()
        unrelated = (
            await client.post("/api/v1/conversations", json={"collection_id": other["id"]})
        ).json()
        case = (
            await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": "Only target",
                    "steps": [{"action": "Run", "expected": "Pass"}],
                },
            )
        ).json()
        proposed = await proposal(client, monkeypatch, cid, collection["id"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as foreign:
            _, _, foreign_workspace = await setup(foreign)
        with get_session_factory()() as cross_space:
            foreign_row = cross_space.get(Conversation, UUID(foreign_workspace["id"]))
            cross_space.refresh(foreign_row, with_for_update=True)
            monkeypatch.setattr(case_management, "delete_collection", paused_delete)
            pending = asyncio.create_task(
                client.post(
                    approval_url(cid, proposed),
                    json={
                        "name": proposed["name"],
                        "collection_id": collection["id"],
                    },
                )
            )
            try:
                assert await asyncio.to_thread(entered.wait, 5)

                def try_phantoms():
                    with get_session_factory()() as db:
                        db.execute(text("SET LOCAL lock_timeout = '150ms'"))
                        db.add(
                            Conversation(
                                space_id=UUID(sid),
                                account_id=UUID(account["id"]),
                                collection_id=UUID(other["id"]),
                                context={},
                            )
                        )
                        with pytest.raises(OperationalError) as failure:
                            db.flush()
                        assert failure.value.orig.sqlstate == "55P03"
                        db.rollback()
                        db.execute(text("SET LOCAL lock_timeout = '150ms'"))
                        owner = db.get(Account, UUID(account["id"]))
                        conversation = db.get(Conversation, UUID(unrelated["id"]))
                        with pytest.raises(OperationalError) as failure:
                            update_selection(
                                db,
                                owner,
                                conversation,
                                SelectionUpdate(
                                    base_version=0,
                                    sources=[
                                        {
                                            "ref": f"asset:{case['id']}",
                                            "version": case["current_revision_id"],
                                        }
                                    ],
                                ),
                            )
                        assert failure.value.orig.sqlstate == "55P03"
                        db.rollback()

                await asyncio.to_thread(try_phantoms)
            finally:
                release.set()
            response = await pending
            assert response.status_code == 200, response.text
            cross_space.rollback()
        # Once committed, new workspaces may be created but orphan-only sources
        # cannot be selected as if they still belonged to an active collection.
        fresh = await client.post("/api/v1/conversations", json={"collection_id": other["id"]})
        assert fresh.status_code == 201, fresh.text
        selected = await client.patch(
            f"/api/v1/workspaces/{fresh.json()['id']}/selection",
            json={
                "base_version": 0,
                "sources": [
                    {
                        "ref": f"asset:{case['id']}",
                        "version": case["current_revision_id"],
                    }
                ],
            },
        )
        assert selected.status_code == 404, selected.text
