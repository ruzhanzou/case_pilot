"""Canonical asset scope is independent of the output destination, never unbounded."""

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup
from test_workbench_carryover_scope import audit_count, finish_worker, select_cases
from test_workbench_collection_selection import post, seed

from casepilot_api import conversations
from casepilot_api.agent_router import CaseScopeDecision
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CollectionCaseMembership, Conversation
from casepilot_api.schemas import ConversationMessageCreate


def memberships(case_ids):
    with get_session_factory()() as db:
        return set(
            db.execute(
                select(
                    CollectionCaseMembership.test_case_id,
                    CollectionCaseMembership.collection_id,
                ).where(CollectionCaseMembership.test_case_id.in_([UUID(v) for v in case_ids]))
            )
        )


@pytest.mark.asyncio
async def test_preserved_cross_collection_subset_rewrites_assets_not_destination(monkeypatch):
    from casepilot_agent import tasks
    from casepilot_agent.pipeline import _explicit_rewrite_candidate
    from casepilot_agent.providers.mock import MockProvider

    def rewrite(_provider, request):
        # Offline semantic provider seam: keep the real worker/guard/store path.
        assert "仅修改保留选择中的P1" in request.instruction
        return _explicit_rewrite_candidate(
            request.model_copy(update={"instruction": "把选中用例优先级改为P2"})
        )

    monkeypatch.setattr(MockProvider, "rewrite", rewrite)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, original, workspace = await setup(client)
        sid, cid = account["spaces"][0]["id"], workspace["id"]
        destination = await post(client, f"/spaces/{sid}/collections", {"name": "Output B"})
        references = await post(client, f"/spaces/{sid}/collections", {"name": "References C"})
        target = await seed(client, original["id"], "P1 selected")
        protected = await post(
            client,
            f"/collections/{original['id']}/test-cases",
            {
                "title": "P0 selected",
                "priority": "P0",
                "steps": [{"action": "Run", "expected": "Pass"}],
            },
        )
        outside = await seed(client, original["id"], "P1 not selected")
        reference = await seed(client, references["id"], "P1 background only")
        cases = [target, protected, outside, reference]
        before_memberships = memberships([case["id"] for case in cases])
        before_audits = {case["id"]: audit_count(case["id"]) for case in cases}
        await select_cases(client, cid, 0, [target, protected])
        activate(
            monkeypatch,
            [
                (
                    "select_collection",
                    {
                        "collection_id": destination["id"],
                        "base_version": 1,
                        "selection_policy": "preserve",
                    },
                )
            ],
        )
        await post(
            client,
            f"/conversations/{cid}/messages",
            {
                "content": "切换到 Output B，保留当前勾选，不创建或修改用例",
                "client_request_id": str(uuid4()),
            },
        )
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert state["collection_id"] == destination["id"]
        assert state["context"]["workbench_selection"]["version"] == 2
        assert {item["case_id"] for item in state["context"]["workbench_selection"]["items"]} == {
            target["id"],
            protected["id"],
        }
        activate(monkeypatch, [("query_assets", {"scope": "selection"}), ("prepare_rewrite", {})])
        monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
        observed = []

        def scope(content, catalog, context, **kwargs):
            observed.append(catalog)
            return CaseScopeDecision(
                ids=[target["id"]],
                ambiguous=False,
                clarification="",
                reference="selection",
                referenced_case_keys=[],
                requested_count=None,
            )

        monkeypatch.setattr(conversations, "select_case_scope", scope)
        turn = await post(
            client,
            f"/conversations/{cid}/messages",
            {
                "content": "仅修改保留选择中的P1用例，把优先级改为P2；P0保持不变",
                "selection_version": 2,
                "client_request_id": str(uuid4()),
                "source_collection_ids": [references["id"]],
            },
        )
        operation = turn["operation_plan"]["operations"][0]
        assert operation["target"]["case_ids"] == [target["id"]], turn
        assert observed and {str(row["id"]) for row in observed[0]} == {
            target["id"],
            protected["id"],
        }
        snapshots = operation["payload"]["prepared_modification"]["cases"]
        assert snapshots[0]["snapshot"]["collection_ids"] == [original["id"]]
        change = await finish_worker(client, cid, operation, turn["action"]["job_id"])
        assert [item["ref"] for item in change["items"]] == [target["id"]]
        approved = await client.post(f"/api/v1/case-change-sets/{change['id']}/apply", json={})
        assert approved.status_code == 200, approved.text
        assert memberships([case["id"] for case in cases]) == before_memberships
        assert (
            await client.get(f"/api/v1/collections/{destination['id']}/test-cases")
        ).json() == []
        for case in cases:
            current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            if case["id"] == target["id"]:
                assert current["priority"] == "P2"
                assert current["current_revision_id"] != case["current_revision_id"]
            else:
                assert current["current_revision_id"] == case["current_revision_id"]
                assert audit_count(case["id"]) == before_audits[case["id"]]
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        assert state["collection_id"] == destination["id"]
        assert state["context"]["workbench_selection"]["active_collection_id"] == destination["id"]


@pytest.mark.asyncio
async def test_cross_collection_exception_requires_persisted_exact_canonical_scope(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, original, workspace = await setup(client)
        sid, cid = account["spaces"][0]["id"], workspace["id"]
        other = await post(client, f"/spaces/{sid}/collections", {"name": "Other"})
        allowed = await seed(client, other["id"], "Allowed")
        forbidden = await seed(client, other["id"], "Not selected")
        request = ConversationMessageCreate(content="修改指定用例", target_case_ids=[allowed["id"]])
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(cid))
            with pytest.raises(HTTPException) as error:
                conversations._expand_conversation_targets(db, conversation, request)
            assert error.value.detail == "target_collection_mismatch"
        await select_cases(client, cid, 0, [allowed])
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(cid))
            expanded = conversations._expand_conversation_targets(db, conversation, request)
            assert list(map(str, expanded.target_case_ids)) == [allowed["id"]]
            with pytest.raises(HTTPException) as error:
                conversations._expand_conversation_targets(
                    db,
                    conversation,
                    request.model_copy(update={"target_case_ids": [UUID(forbidden["id"])]}),
                )
            assert error.value.detail == "workbench_selection_target_conflict"
        updated = await client.patch(
            f"/api/v1/test-cases/{allowed['id']}",
            json={
                "base_revision_id": allowed["current_revision_id"],
                "title": "Externally changed",
                "steps": allowed["steps"],
                "priority": "P2",
            },
        )
        assert updated.status_code == 200, updated.text
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(cid))
            with pytest.raises(HTTPException) as error:
                conversations._expand_conversation_targets(db, conversation, request)
            assert error.value.detail == "workbench_source_changed"
