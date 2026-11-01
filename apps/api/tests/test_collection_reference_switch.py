"""A tool-driven collection switch never promotes automatic references to chat attachments."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from test_collection_references import source
from test_workbench_bridge_integration import setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Conversation, ConversationMessage
from casepilot_api.schemas import ConversationMessageCreate
from casepilot_api.workbench_continuation import create_run
from casepilot_api.workbench_tools import CollectionSelectionArguments, WorkbenchTools


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["clear", "preserve"])
@pytest.mark.parametrize("other_bound", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
async def test_switch_reference_origins(policy, other_bound, explicit):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, a, ws = await setup(client)
        b = (
            await client.post(
                f"/api/v1/spaces/{account['spaces'][0]['id']}/collections", json={"name": "Other"}
            )
        ).json()
        ra, da = source(account, name="A material")
        rb, dbid = source(account, name="B material")
        for col, ids in [(a, [ra]), (b, [rb] if other_bound else [])]:
            response = await client.put(
                f"/api/v1/collections/{col['id']}/references",
                json={"base_version": 0, "source_ids": ids},
            )
            assert response.status_code == 200, response.text
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(ws["id"]))
            owner = db.get(Account, conv.account_id)
            msg = ConversationMessage(conversation_id=conv.id, role="user", content="Switch")
            db.add(msg)
            db.flush()
            run = create_run(db, owner, conv, msg.id, uuid4())
            payload = ConversationMessageCreate(
                content="Switch",
                document_ids=[UUID(da)] if explicit else [],
                knowledge_source_ids=[UUID(ra)] if explicit else [],
            )
            bridge = WorkbenchTools(db, owner, conv, payload, durable_run=run, initial=True)
            # Exercise the formerly lossy initial materialization, then the actual tool.
            bridge.payload = bridge.current_payload()
            old_binding = bridge.reference_binding
            result = bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=b["id"], base_version=0, selection_policy=policy
                )
            )
            assert result["status"] == "completed"
            current = bridge.current_payload()
            expected_sources = ({ra} if explicit else set()) | ({rb} if other_bound else set())
            expected_docs = ({da} if explicit else set()) | ({dbid} if other_bound else set())
            assert set(map(str, current.knowledge_source_ids)) == expected_sources
            assert set(map(str, current.document_ids)) == expected_docs
            assert bridge.reference_binding != old_binding
            assert set(bridge.reference_binding["bound_source_ids"]) == (
                {rb} if other_bound else set()
            )
            checkpoint = run.checkpoint["authorized_scope_request"]
            assert set(checkpoint["knowledge_source_ids"]) == ({ra} if explicit else set())
            from casepilot_api.workbench_scope import restore_authorized_scope

            # Durable resumption uses only explicit conversation attachments; the
            # currently bound collection is enriched afresh at each tool boundary.
            resumed = WorkbenchTools(
                db, owner, conv, restore_authorized_scope(run, conv), durable_run=run, initial=True
            )
            assert set(map(str, resumed.current_payload().knowledge_source_ids)) == expected_sources
            bridge = resumed
            bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=a["id"], base_version=1, selection_policy=policy
                )
            )
            current = bridge.current_payload()
            assert set(map(str, current.knowledge_source_ids)) == {ra}
            assert set(map(str, current.document_ids)) == {da}
