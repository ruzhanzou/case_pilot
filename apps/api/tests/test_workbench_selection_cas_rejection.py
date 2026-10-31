import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Conversation, WorkbenchRun
from casepilot_api.schemas import ConversationMessageCreate
from casepilot_api.workbench_continuation import validate_binding
from casepilot_api.workbench_selection import SelectionUpdate, update_selection
from casepilot_api.workbench_tools import CollectionSelectionArguments, WorkbenchTools


async def fixture(client):
    user, a, w = await setup(client)
    b = (
        await client.post(
            f"/api/v1/spaces/{user['spaces'][0]['id']}/collections", json={"name": "Synthetic B"}
        )
    ).json()
    response = await client.patch(
        f"/api/v1/workspaces/{w['id']}/selection", json={"base_version": 0, "action": "clear"}
    )
    assert response.status_code == 200
    return a, b, w


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [True, False])
async def test_query_then_switch_fixed_vs_stale_model_base(monkeypatch, stale):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a, b, w = await fixture(c)
        provider = activate(
            monkeypatch,
            [
                ("query_collections", {"search": "Synthetic B"}),
                (
                    "select_collection",
                    {
                        "collection_id": b["id"],
                        "base_version": 0 if stale else 1,
                        "selection_policy": "clear",
                    },
                ),
                ("get_workspace_context", {}),
            ],
        )
        r = await c.post(
            f"/api/v1/conversations/{w['id']}/messages",
            json={
                "content": "切换到Synthetic B，清空选择，不修改用例",
                "client_request_id": str(uuid4()),
            },
        )
        assert r.status_code == 202
        meta = r.json()["assistant_message"]["metadata"]["workbench_agent"]
        state = (await c.get(f"/api/v1/conversations/{w['id']}")).json()
        if stale:
            assert meta.get("error_code") is None
            rejected = next(x for x in meta["events"] if x["type"] == "tool_rejected")
            assert rejected["diagnostic"]["rejection_code"] == "selection_version_conflict"
            assert rejected["diagnostic"]["argument_base_version"] == 0
            assert rejected["diagnostic"]["canonical_version"] == 1
            assert (
                state["collection_id"] == a["id"]
                and state["context"]["workbench_selection"]["version"] == 1
            )
        else:
            assert (
                state["collection_id"] == b["id"]
                and state["context"]["workbench_selection"]["version"] == 2
            )
        print(
            json.dumps(
                {
                    "case": "api_stale_model_base" if stale else "api_current_base",
                    "model_base": 0 if stale else 1,
                    "initial_version": 1,
                    "final_version": state["context"]["workbench_selection"]["version"],
                    "error_code": meta.get("error_code"),
                    "provider_mock_calls": len(provider.observations),
                }
            )
        )


@pytest.mark.asyncio
async def test_direct_stale_argument_vs_stale_envelope_and_own_advance():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a, b, w = await fixture(c)
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(w["id"]))
            acct = db.get(Account, conv.account_id)
            bridge = WorkbenchTools(
                db, acct, conv, ConversationMessageCreate(content="switch", selection_version=1)
            )
            rejected = bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=b["id"], base_version=0, selection_policy="clear"
                )
            )
            assert rejected["error_code"] == "selection_version_conflict"
            assert not bridge.mutating_intent
            first = bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=b["id"], base_version=1, selection_policy="clear"
                )
            )
            assert first["selection"]["version"] == 2 and bridge.payload.selection_version is None
            second = bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=a["id"], base_version=2, selection_policy="clear"
                )
            )
            assert second["selection"]["version"] == 3
            stale = WorkbenchTools(
                db, acct, conv, ConversationMessageCreate(content="switch", selection_version=1)
            )
            with pytest.raises(HTTPException) as err2:
                stale.select_collection(
                    CollectionSelectionArguments(
                        collection_id=b["id"], base_version=3, selection_policy="clear"
                    )
                )
            assert err2.value.detail == "workbench_selection_version_conflict"
            assert (
                str(conv.collection_id) == a["id"]
                and conv.context["workbench_selection"]["version"] == 3
            )
            print(
                json.dumps(
                    {
                        "case": "direct_comparison",
                        "stale_arg_code": rejected["error_code"],
                        "stale_envelope_code": err2.value.detail,
                        "own_success_versions": [2, 3],
                        "formal_case_writes": 0,
                    }
                )
            )
            db.rollback()


@pytest.mark.asyncio
async def test_external_authority_change_is_not_model_base_refresh(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a, b, w = await fixture(c)
        activate(
            monkeypatch,
            [
                (
                    "select_collection",
                    {"collection_id": b["id"], "base_version": 1, "selection_policy": "clear"},
                )
            ],
        )
        r = await c.post(
            f"/api/v1/conversations/{w['id']}/messages",
            json={"content": "switch", "client_request_id": str(uuid4())},
        )
        assert r.status_code == 202
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(w["id"]))
            acct = db.get(Account, conv.account_id)
            run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == conv.id))
            validate_binding(db, run, conv, allow_legacy=True)
            old = deepcopy(run.binding)
            update_selection(
                db,
                acct,
                conv,
                SelectionUpdate(base_version=2, action="clear", active_collection_id=UUID(a["id"])),
            )
            with pytest.raises(HTTPException) as err:
                validate_binding(db, run, conv, allow_legacy=True)
            assert err.value.detail == "workbench_run_binding_changed"
            assert run.binding == old and conv.context["workbench_selection"]["version"] == 3
            print(
                json.dumps(
                    {
                        "case": "external_authority_change",
                        "code": err.value.detail,
                        "run_bound_version": 2,
                        "current_version": 3,
                        "binding_not_refreshed": True,
                    }
                )
            )
            db.rollback()


@pytest.mark.asyncio
async def test_reobserve_after_rejection_without_automatic_base_refresh(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a, b, w = await fixture(c)

        def observed(messages):
            outputs = [
                json.loads(x["output"]) for x in messages if x.get("type") == "function_call_output"
            ]
            assert outputs[-2]["error_code"] == "selection_version_conflict"
            return {
                "collection_id": b["id"],
                "base_version": outputs[-1]["selection"]["version"],
                "selection_policy": "clear",
            }

        activate(
            monkeypatch,
            [
                (
                    "select_collection",
                    {"collection_id": b["id"], "base_version": 0, "selection_policy": "clear"},
                ),
                ("get_workspace_context", {}),
                ("select_collection", observed),
            ],
        )
        r = await c.post(
            f"/api/v1/conversations/{w['id']}/messages",
            json={"content": "switch", "client_request_id": str(uuid4())},
        )
        assert r.status_code == 202
        meta = r.json()["assistant_message"]["metadata"]["workbench_agent"]
        assert meta.get("error_code") is None
        assert len([x for x in meta["events"] if x["type"] == "tool_rejected"]) == 1
        assert len([x for x in meta["receipts"] if x["tool"] == "select_collection"]) == 1
        state = (await c.get(f"/api/v1/conversations/{w['id']}")).json()
        assert (
            state["collection_id"] == b["id"]
            and state["context"]["workbench_selection"]["version"] == 2
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["model_base", "final_cas", "after_selection", "none"])
async def test_selection_and_prior_run_invalidation_are_atomic(monkeypatch, fault):
    from casepilot_api import workbench_selection, workbench_turn_pause
    from casepilot_api.models import ConversationMessage
    from casepilot_api.workbench_continuation import create_run
    from casepilot_api.workbench_turn_pause import pause_prior_runs

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a, b, w = await fixture(c)
        activate(
            monkeypatch,
            [
                (
                    "select_collection",
                    {"collection_id": b["id"], "base_version": 1, "selection_policy": "clear"},
                )
            ],
        )
        r = await c.post(
            f"/api/v1/conversations/{w['id']}/messages",
            json={"content": "switch", "client_request_id": str(uuid4())},
        )
        assert r.status_code == 202
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(w["id"]))
            account_id = conv.account_id
            old = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == conv.id))
            old_id = old.id
        request_id = uuid4()
        pause_prior_runs(get_session_factory(), account_id, UUID(w["id"]), request_id)
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(w["id"]))
            acct = db.get(Account, account_id)
            message = ConversationMessage(
                conversation_id=conv.id,
                role="user",
                content="Synthetic switch",
                intent="KNOWLEDGE_QA",
                intent_confidence=1,
                status="completed",
                target_case_ids=[],
                citations=[],
                message_metadata={},
            )
            db.add(message)
            db.flush()
            current = create_run(db, acct, conv, message.id, request_id)
            bridge = WorkbenchTools(
                db,
                acct,
                conv,
                ConversationMessageCreate(content="switch", selection_version=2),
                durable_run=current,
                initial=True,
            )
            before = deepcopy(conv.context)
            old = db.get(WorkbenchRun, old_id)
            old_epoch = old.epoch
            assert old.status == "paused_question"
            if fault == "final_cas":
                original = workbench_selection.update_selection

                def raced(*args, **kw):
                    # Fault injection at the final service CAS, using its real locked checker.
                    update = args[3].model_copy(update={"base_version": 1})
                    return original(*args[:3], update, **kw)

                monkeypatch.setattr(workbench_selection, "update_selection", raced)
            if fault == "after_selection":
                original = workbench_turn_pause.resolve_question

                def failed(*args, **kw):
                    original(*args, **kw)
                    raise HTTPException(409, "workbench_run_binding_changed")

                monkeypatch.setattr(workbench_turn_pause, "resolve_question", failed)
            args = CollectionSelectionArguments(
                collection_id=a["id"],
                base_version=1 if fault == "model_base" else 2,
                selection_policy="clear",
            )
            if fault in {"final_cas", "after_selection"}:
                with pytest.raises(HTTPException):
                    bridge.select_collection(args)
            else:
                result = bridge.select_collection(args)
                if fault == "model_base":
                    assert result["error_code"] == "selection_version_conflict"
            db.flush()
            db.refresh(conv)
            db.refresh(old)
            if fault != "none":
                assert conv.context == before and str(conv.collection_id) == b["id"]
                assert old.status == "paused_question" and old.epoch == old_epoch
                assert bridge.payload.selection_version == 2 and not bridge.mutating_intent
            else:
                assert (
                    str(conv.collection_id) == a["id"]
                    and conv.context["workbench_selection"]["version"] == 3
                )
                assert (
                    old.status == "invalidated"
                    and old.epoch == old_epoch + 1
                    and bridge.mutating_intent
                )
            db.rollback()


@pytest.mark.asyncio
async def test_separate_committed_selection_between_observation_and_lock(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        a, b, workspace = await fixture(client)
        with get_session_factory()() as db:
            conv = db.get(Conversation, UUID(workspace["id"]))
            account = db.get(Account, conv.account_id)
            bridge = WorkbenchTools(db, account, conv, ConversationMessageCreate(content="switch"))
            original_refresh = db.refresh
            injected = False

            def before_lock(instance, *args, **kwargs):
                nonlocal injected
                if instance is conv and kwargs.get("with_for_update") and not injected:
                    injected = True
                    # A distinct committed transaction wins before the tool obtains its lock.
                    with get_session_factory()() as external:
                        other = external.get(Conversation, conv.id)
                        actor = external.get(Account, conv.account_id)
                        update_selection(
                            external,
                            actor,
                            other,
                            SelectionUpdate(
                                base_version=1, action="clear", active_collection_id=UUID(b["id"])
                            ),
                        )
                        external.commit()
                return original_refresh(instance, *args, **kwargs)

            monkeypatch.setattr(db, "refresh", before_lock)
            with pytest.raises(HTTPException) as error:
                bridge.select_collection(
                    CollectionSelectionArguments(
                        collection_id=a["id"], base_version=1, selection_policy="clear"
                    )
                )
            assert error.value.detail == "workbench_run_binding_changed"
            assert not bridge.mutating_intent
            db.rollback()
        with get_session_factory()() as db:
            current = db.get(Conversation, UUID(workspace["id"]))
            assert str(current.collection_id) == b["id"]
            assert current.context["workbench_selection"]["version"] == 2
