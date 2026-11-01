"""Real PG/API owner isolation for temporary uploads; no authorization mocks."""

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import setup
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401

from casepilot_api import knowledge
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SpaceMembership,
    TaskOutbox,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["list", "get", "preview", "download", "reindex", "delete"])
@pytest.mark.parametrize("shared", [False, True])
async def test_owner_and_same_space_member_knowledge_access(
    monkeypatch, tmp_path, endpoint, shared
):
    monkeypatch.setattr(knowledge.settings, "knowledge_storage_path", str(tmp_path))
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as owner,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as peer,
    ):
        a, collection, _ = await setup(owner)
        b, _, _ = await setup(peer)
        space = collection["space_id"]
        with get_session_factory()() as db:
            db.add(SpaceMembership(space_id=UUID(space), account_id=UUID(b["id"]), role="member"))
            db.commit()
        upload = await owner.post(
            f"/api/v1/spaces/{space}/" + ("knowledge-sources" if shared else "knowledge-documents"),
            data={"name": "Synthetic private reference"},
            files={"files": ("synthetic.txt", b"Synthetic private requirement", "text/plain")},
        )
        assert upload.status_code == 202
        sid = upload.json()["source"]["id"]
        did = upload.json()["document_ids"][0]
        with get_session_factory()() as db:
            source = db.get(KnowledgeSource, UUID(sid))
            source.status = "ready"
            document = db.get(KnowledgeDocument, UUID(did))
            document.status = "ready"
            db.add(
                KnowledgeChunk(
                    source_id=source.id,
                    document_id=document.id,
                    space_id=UUID(space),
                    chunk_type="parent",
                    ordinal=0,
                    content="Synthetic private requirement",
                    contextual_content="Synthetic private requirement",
                    search_text="Synthetic private requirement",
                    token_count=3,
                )
            )
            db.commit()
            before = (
                source.status,
                source.reference_revision,
                source.deleted_at,
                document.status,
                db.scalar(select(func.count()).select_from(TaskOutbox)),
            )
        paths = {
            "list": ("GET", f"/spaces/{space}/knowledge-sources"),
            "get": ("GET", f"/knowledge-sources/{sid}"),
            "preview": ("GET", f"/knowledge-documents/{did}/preview"),
            "download": ("GET", f"/knowledge-documents/{did}/download"),
            "reindex": ("POST", f"/knowledge-sources/{sid}/reindex"),
            "delete": ("DELETE", f"/knowledge-sources/{sid}"),
        }
        method, path = paths[endpoint]
        response = await peer.request(method, "/api/v1" + path)
        expected = 204 if endpoint == "delete" else 202 if endpoint == "reindex" else 200
        if shared:
            assert response.status_code == expected
            if endpoint == "list":
                assert sid in {row["id"] for row in response.json()}
            if endpoint == "download":
                assert response.content == b"Synthetic private requirement"
            if endpoint == "preview":
                assert response.json()["content"] == "Synthetic private requirement"
            return
        if endpoint == "list":
            assert response.status_code == 200 and sid not in {row["id"] for row in response.json()}
            assert did not in response.text and "Synthetic private requirement" not in response.text
        else:
            assert response.status_code == 404
            assert (
                sid not in response.text
                and did not in response.text
                and "Synthetic private" not in response.text
            )
        with get_session_factory()() as db:
            source = db.get(KnowledgeSource, UUID(sid))
            document = db.get(KnowledgeDocument, UUID(did))
            after = (
                source.status,
                source.reference_revision,
                source.deleted_at,
                document.status,
                db.scalar(select(func.count()).select_from(TaskOutbox)),
            )
            assert after == before
        response = await owner.request(method, "/api/v1" + path)
        assert response.status_code == expected
        if endpoint == "download":
            assert response.content == b"Synthetic private requirement"
        if endpoint == "preview":
            assert response.json()["content"] == "Synthetic private requirement"


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["document_ids", "knowledge_source_ids"])
async def test_other_members_temporary_reference_cannot_enter_generation_or_chat(reference):
    from test_collection_references import source

    from casepilot_api.models import GenerationJob

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as owner,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as peer,
    ):
        a, collection, _ = await setup(owner)
        b, _, _ = await setup(peer)
        sid, did = source(a, temporary=True)
        with get_session_factory()() as db:
            db.add(
                SpaceMembership(
                    space_id=UUID(collection["space_id"]), account_id=UUID(b["id"]), role="member"
                )
            )
            db.commit()
            before = db.scalar(select(func.count()).select_from(GenerationJob))
        ids = [did] if reference == "document_ids" else [sid]
        rejected = await peer.post(
            "/api/v1/generation-jobs",
            json={
                "collection_id": collection["id"],
                "prompt": "Synthetic generation",
                reference: ids,
            },
        )
        assert rejected.status_code == 409
        conversation = await peer.post(
            "/api/v1/conversations", json={"collection_id": collection["id"]}
        )
        assert conversation.status_code == 201
        rejected = await peer.post(
            f"/api/v1/conversations/{conversation.json()['id']}/messages",
            json={"content": "Use the reference", reference: ids},
        )
        assert rejected.status_code == 422
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(GenerationJob)) == before
