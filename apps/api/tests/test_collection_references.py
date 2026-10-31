"""Real PG authorization, source snapshots and cross-conversation reference state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import setup
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401

from casepilot_api.collection_references import (
    assert_reference_binding,
    capture_reference_binding,
    merge_references,
)
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Conversation, KnowledgeDocument, KnowledgeSource
from casepilot_api.schemas import ConversationMessageCreate


def source(account, *, temporary=False, name="Requirements"):
    with get_session_factory()() as db:
        row = KnowledgeSource(
            space_id=UUID(account["spaces"][0]["id"]),
            account_id=UUID(account["id"]),
            name=name,
            status="ready",
            persistence="temporary" if temporary else "space",
        )
        db.add(row)
        db.flush()
        document = KnowledgeDocument(
            source_id=row.id,
            space_id=row.space_id,
            original_name="synthetic.txt",
            mime_type="text/plain",
            storage_key=uuid4().hex,
            size_bytes=10,
            checksum="a" * 64,
            status="ready",
            expires_at=datetime.now(UTC) + timedelta(hours=1) if temporary else None,
        )
        db.add(document)
        db.commit()
        return str(row.id), str(document.id)


@pytest.mark.asyncio
async def test_explicit_binding_promotion_cas_and_new_conversation_full_context():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        sid, did = source(account, temporary=True)
        path = f"/api/v1/collections/{collection['id']}/references"
        assert (await client.get(path)).json()["sources"] == []
        response = await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 1
        assert (
            await client.put(path, json={"base_version": 0, "source_ids": []})
        ).status_code == 409
        case = (
            await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": "Synthetic full case",
                    "description": "Full description",
                    "preconditions": ["Existing account"],
                    "steps": [{"action": "Submit", "expected": "One record"}],
                },
            )
        ).json()
        fresh = (
            await client.post(
                "/api/v1/conversations",
                json={
                    "collection_id": collection["id"],
                },
            )
        ).json()
        cid = fresh["id"]
        assert (
            await client.patch(
                f"/api/v1/workspaces/{cid}/selection",
                json={
                    "base_version": 0,
                    "sources": [
                        {"ref": "asset:" + case["id"], "version": case["current_revision_id"]}
                    ],
                },
            )
        ).status_code == 200
        response = await client.get(f"/api/v1/workspaces/{cid}/reference-context")
        assert response.status_code == 200, response.text
        context = response.json()
        assert context["sources"][0]["origin"] == "collection"
        assert context["sources"][0]["documents"][0]["id"] == did
        assert context["selected_cases"][0]["snapshot"]["steps"] == case["steps"]
        assert context["selected_cases"][0]["snapshot"]["description"] == "Full description"
        with get_session_factory()() as db:
            assert db.get(KnowledgeDocument, UUID(did)).expires_at is None
            assert db.get(KnowledgeSource, UUID(sid)).persistence == "space"
            convo = db.get(Conversation, UUID(cid))
            assert not convo.context.get("document_ids")  # No permanent-to-temporary leakage.


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unbind", "reindex", "delete", "document_version"])
async def test_source_change_invalidates_exact_snapshot(change):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        sid, did = source(account)
        path = f"/api/v1/collections/{collection['id']}/references"
        assert (
            await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        ).status_code == 200
        with get_session_factory()() as db:
            convo = db.get(Conversation, UUID(conversation["id"]))
            binding = capture_reference_binding(
                db, convo, ConversationMessageCreate(content="Modify")
            )
        if change == "unbind":
            assert (
                await client.put(path, json={"base_version": 1, "source_ids": []})
            ).status_code == 200
        elif change in {"reindex", "delete"}:
            method = client.post if change == "reindex" else client.delete
            suffix = "/reindex" if change == "reindex" else ""
            response = await method(f"/api/v1/knowledge-sources/{sid}{suffix}")
            assert response.status_code in {202, 204}
        else:
            with get_session_factory()() as db:
                db.get(KnowledgeDocument, UUID(did)).version += 1
                db.commit()
        with get_session_factory()() as db:
            convo = db.get(Conversation, UUID(conversation["id"]))
            user = db.get(Account, UUID(account["id"]))
            with pytest.raises(HTTPException) as error:
                assert_reference_binding(db, user, convo, binding)
            assert error.value.status_code == 409
            assert error.value.detail == "reference_context_changed"


@pytest.mark.asyncio
async def test_temporary_sources_remain_temporary_and_foreign_sources_do_not_bind():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        sid, did = source(account, temporary=True)
        with get_session_factory()() as db:
            convo = db.get(Conversation, UUID(conversation["id"]))
            result = merge_references(
                db,
                convo,
                ConversationMessageCreate(
                    content="Use temporary reference", document_ids=[UUID(did)]
                ),
            )
            assert result.document_ids == [UUID(did)]
            assert db.get(KnowledgeSource, UUID(sid)).persistence == "temporary"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            other_account, _, _ = await setup(other)
            foreign_sid, _ = source(other_account)
        path = f"/api/v1/collections/{collection['id']}/references"
        response = await client.put(path, json={"base_version": 0, "source_ids": [foreign_sid]})
        assert response.status_code == 404
        assert (await client.get(path)).json()["version"] == 0


@pytest.mark.asyncio
async def test_multiple_sources_have_visible_origins_and_no_latest_wins_policy():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        first, _ = source(account, name="Norm: minimum 10")
        second, _ = source(account, name="Requirement: minimum 20")
        path = f"/api/v1/collections/{collection['id']}/references"
        await client.put(path, json={"base_version": 0, "source_ids": [first, second]})
        context = (
            await client.get(f"/api/v1/workspaces/{conversation['id']}/reference-context")
        ).json()
        assert len(context["sources"]) == 2
        assert context["warnings"] == ["source_consistency_unverified"]
        assert "No upload-order precedence" in context["authority_policy"]
        assert context["selected_cases"] == []  # Empty selection is not the whole collection.


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_outbox_db")
async def test_reference_binding_change_rejects_real_ready_change_set_atomically(monkeypatch):
    from casepilot_agent import tasks
    from test_qa_request_continuation import late_prepare
    from workbench_request_continuation import RequestContinuation

    from casepilot_api.models import WorkbenchRun

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cid, cases, _, initial = await late_prepare(client, monkeypatch)
        helper = RequestContinuation(cid, initial, {})
        await helper.advance(tasks, "message")
        await helper.advance(tasks, "workers")
        assert helper.state()["status"] == "waiting_approval"
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        # A new reference configuration must also invalidate a proposal created with none.
        with get_session_factory()() as db:
            convo = db.get(Conversation, UUID(cid))
            row = KnowledgeSource(
                space_id=convo.space_id,
                account_id=convo.account_id,
                name="New requirement",
                status="ready",
                persistence="space",
            )
            db.add(row)
            db.flush()
            db.add(
                KnowledgeDocument(
                    source_id=row.id,
                    space_id=row.space_id,
                    original_name="new.txt",
                    mime_type="text/plain",
                    storage_key=uuid4().hex,
                    size_bytes=10,
                    checksum="b" * 64,
                    status="ready",
                )
            )
            db.commit()
            sid = str(row.id)
            run = db.get(WorkbenchRun, helper.run_id)
            change_id = run.checkpoint["waiting_artifact_id"]
        response = await client.put(
            f"/api/v1/collections/{state['collection_id']}/references",
            json={"base_version": 0, "source_ids": [sid]},
        )
        assert response.status_code == 200, response.text
        rejected = await client.post(
            f"/api/v1/case-change-sets/{change_id}/apply",
            json={
                "selection_version": state["context"]["workbench_selection"]["version"],
                "review_refs": [case["id"] for case in cases],
            },
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"] == "reference_context_changed"
        for case in cases:
            actual = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert actual["current_revision_id"] == case["current_revision_id"]


@pytest.mark.asyncio
async def test_external_reference_change_does_not_refresh_an_agents_observed_authority():
    from casepilot_api.workbench_tools import WorkbenchTools

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        sid, _ = source(account)
        path = f"/api/v1/collections/{collection['id']}/references"
        await client.put(path, json={"base_version": 0, "source_ids": [sid]})
        with get_session_factory()() as db:
            tools = WorkbenchTools(
                db,
                db.get(Account, UUID(account["id"])),
                db.get(Conversation, UUID(conversation["id"])),
                ConversationMessageCreate(content="Inspect then rewrite"),
            )
            tools.current_payload()
            old = tools.reference_binding
            assert (
                await client.put(path, json={"base_version": 1, "source_ids": []})
            ).status_code == 200
            with pytest.raises(HTTPException) as error:
                tools.current_payload()
            assert error.value.detail == "reference_context_changed"
            assert tools.reference_binding == old


@pytest.mark.asyncio
async def test_binding_cannot_promote_another_members_temporary_upload():
    from casepilot_api.models import SpaceMembership

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, _ = await setup(client)
        sid, _ = source(account, temporary=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            member, _, _ = await setup(other)
            with get_session_factory()() as db:
                db.add(
                    SpaceMembership(
                        space_id=UUID(collection["space_id"]),
                        account_id=UUID(member["id"]),
                        role="member",
                    )
                )
                db.commit()
            prefix = f"/api/v1/collections/{collection['id']}"
            options = (await other.get(prefix + "/reference-options")).json()
            assert sid not in {row["id"] for row in options}
            refused = await other.put(
                prefix + "/references",
                json={
                    "base_version": 0,
                    "source_ids": [sid],
                },
            )
            assert refused.status_code == 404
        with get_session_factory()() as db:
            assert db.get(KnowledgeSource, UUID(sid)).persistence == "temporary"


@pytest.mark.asyncio
async def test_detaching_a_temporary_reference_invalidates_its_saved_snapshot():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, conversation = await setup(client)
        sid, did = source(account, temporary=True)
        cid = UUID(conversation["id"])
        with get_session_factory()() as db:
            convo = db.get(Conversation, cid)
            convo.context = {**convo.context, "document_ids": [did], "knowledge_source_ids": [sid]}
            db.commit()
            binding = capture_reference_binding(
                db, convo, ConversationMessageCreate(content="Modify", document_ids=[UUID(did)])
            )
        response = await client.delete(f"/api/v1/conversations/{cid}/attachments/{did}")
        assert response.status_code == 200, response.text
        with get_session_factory()() as db:
            with pytest.raises(HTTPException) as error:
                assert_reference_binding(
                    db, db.get(Account, UUID(account["id"])), db.get(Conversation, cid), binding
                )
            assert error.value.detail == "reference_context_changed"


@pytest.mark.asyncio
async def test_bound_screenshot_is_forwarded_as_authorized_image_bytes(monkeypatch, tmp_path):
    import base64
    from hashlib import sha256

    from casepilot_api.config import get_settings
    from casepilot_api.workbench_tools import WorkbenchTools, user_input_message

    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "image_models", settings.resolve_agent_model("auto"))
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3e0AAAAASUVORK5CYII="
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        sid, did = source(account)
        with get_session_factory()() as db:
            document = db.get(KnowledgeDocument, UUID(did))
            document.mime_type = "image/png"
            document.original_name = "synthetic.png"
            document.checksum = sha256(png).hexdigest()
            document.size_bytes = len(png)
            (tmp_path / document.storage_key).write_bytes(png)
            db.commit()
        response = await client.put(
            f"/api/v1/collections/{collection['id']}/references",
            json={
                "base_version": 0,
                "source_ids": [sid],
            },
        )
        assert response.status_code == 200
        with get_session_factory()() as db:
            convo = db.get(Conversation, UUID(conversation["id"]))
            owner = db.get(Account, UUID(account["id"]))
            bridge = WorkbenchTools(
                db, owner, convo, ConversationMessageCreate(content="Use screenshot")
            )
            payload = bridge.current_payload()
            assert payload.document_ids == [UUID(did)]
            message = user_input_message(db, owner, convo, payload, settings)
            image = next(item for item in message["content"] if item["type"] == "input_image")
            assert base64.b64decode(image["image_url"].split(",", 1)[1]) == png
