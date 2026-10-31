"""Strict legacy selection migration and approved delete preserve unrelated scopes."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import setup
from test_workbench_collection_delete import approval_url, proposal
from test_workbench_collection_selection import post, seed

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    CaseCollection,
    Conversation,
    SpaceMembership,
    WorkspaceCandidate,
)
from casepilot_api.models import TestCase as CaseRecord
from casepilot_api.schemas import ConversationMessageCreate
from casepilot_api.workbench_selection import effective_selection, legacy_selection_sources
from casepilot_api.workbench_tools import CollectionSelectionArguments, WorkbenchTools


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        [None],
        [{"target": None}],
        [{"kind": "case", "unknown": "scope"}],
        [{"label": "bad", "target": {"kind": "module", "module": "Auth"}}],
        [{"target": {"kind": "case", "case_ids": ["not-a-uuid"]}}],
        [{"target": {"kind": "case"}, "unknown": True}],
    ],
)
def test_strict_legacy_decode_never_drops_unknown_or_expands_scope(raw):
    with pytest.raises(HTTPException) as error:
        legacy_selection_sources({"selected_targets": raw})
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_wrapped_and_bare_legacy_preserve_exact_assets_candidates_and_reject_foreign():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user, original, workspace = await setup(client)
        space = user["spaces"][0]["id"]
        destination = await post(client, f"/spaces/{space}/collections", {"name": "B"})
        case = await seed(client, original["id"], "Selected asset")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as outsider:
            _, foreign, _ = await setup(outsider)
            foreign_case = await seed(outsider, foreign["id"], "Foreign")
        with get_session_factory()() as db:
            conversation = db.get(Conversation, UUID(workspace["id"]))
            account = db.get(Account, conversation.account_id)
            db.add(
                WorkspaceCandidate(
                    conversation_id=conversation.id,
                    ref="draft",
                    version=3,
                    snapshot={"title": "Selected draft"},
                    status="candidate",
                    position=0,
                    included=False,
                    created_by=account.id,
                )
            )
            db.flush()
            conversation.context = {
                "selected_targets": [
                    {"label": "Asset", "target": {"kind": "case", "case_ids": [case["id"]]}},
                    {"kind": "case", "candidate_refs": ["draft"]},
                ]
            }
            before = deepcopy(conversation.context)
            observed = effective_selection(db, account, conversation)
            assert conversation.context == before
            assert observed["version"] == 0
            assert observed["active_collection_id"] == original["id"]
            assert {i["ref"]: i["version"] for i in observed["items"]} == {
                f"asset:{case['id']}": case["current_revision_id"],
                "candidate:draft": "3",
            }
            bridge = WorkbenchTools(
                db, account, conversation, ConversationMessageCreate(content="保留选择切B")
            )
            result = bridge.select_collection(
                CollectionSelectionArguments(
                    collection_id=destination["id"], base_version=0, selection_policy="preserve"
                )
            )
            assert result["selection"]["items"] == observed["items"]
            assert result["selection"]["version"] == 1
            assert str(conversation.collection_id) == destination["id"]
            # Explicit observed versions are never silently rebound on canonical state.
            db.add(
                WorkspaceCandidate(
                    conversation_id=conversation.id,
                    ref="draft",
                    version=4,
                    snapshot={"title": "Discarded newer"},
                    status="discarded",
                    position=0,
                    included=False,
                    created_by=account.id,
                )
            )
            db.flush()
            with pytest.raises(HTTPException) as error:
                effective_selection(db, account, conversation)
            assert error.value.status_code == 409
            conversation.context = {
                "selected_targets": [{"target": {"kind": "case", "case_ids": [foreign_case["id"]]}}]
            }
            unchanged = deepcopy(conversation.context)
            with pytest.raises(HTTPException) as error:
                bridge.select_collection(
                    CollectionSelectionArguments(
                        collection_id=original["id"], base_version=0, selection_policy="preserve"
                    )
                )
            assert error.value.status_code == 404
            assert conversation.context == unchanged
            assert str(conversation.collection_id) == destination["id"]
            db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_after_review", [None, "selection", "candidate_version"])
async def test_legacy_B_deleting_A_preserves_B_and_crossowner_sources_or_rejects_change(
    monkeypatch,
    change_after_review,
):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user, delete_a, _ = await setup(client)
        space = user["spaces"][0]["id"]
        keep_b = await post(client, f"/spaces/{space}/collections", {"name": "Keep B"})
        a_case = await seed(client, delete_a["id"], "A only")
        b_case = await seed(client, keep_b["id"], "Keep B asset")
        requester = await post(client, "/conversations", {"collection_id": keep_b["id"]})
        private = await post(client, "/conversations", {"collection_id": keep_b["id"]})
        unrelated = await post(client, "/conversations", {"collection_id": keep_b["id"]})
        stale = await post(client, "/conversations", {"collection_id": keep_b["id"]})
        with get_session_factory()() as db:
            unrelated_row = db.get(Conversation, UUID(unrelated["id"]))
            unrelated_row.context = {
                "selected_targets": [
                    {"label": "Module B", "target": {"kind": "module", "module": "Auth"}},
                    {"kind": "condition", "condition": "P1", "collection_id": keep_b["id"]},
                ]
            }
            stale_row = db.get(Conversation, UUID(stale["id"]))
            stale_row.context = {
                "workbench_selection": {
                    "version": 1,
                    "active_collection_id": keep_b["id"],
                    "items": [
                        {"ref": "candidate:old-unrelated", "kind": "candidate", "version": "1"}
                    ],
                }
            }
            db.add(
                WorkspaceCandidate(
                    conversation_id=stale_row.id,
                    ref="old-unrelated",
                    version=2,
                    snapshot={"title": "Unrelated stale draft"},
                    status="discarded",
                    position=0,
                    included=False,
                    created_by=stale_row.account_id,
                )
            )
            unrelated_before, stale_before = (
                deepcopy(unrelated_row.context),
                deepcopy(stale_row.context),
            )

            owner = Account(
                email=f"legacy-private-{uuid4().hex}@test",
                display_name="Private",
                password_hash="x",
            )
            db.add(owner)
            db.flush()
            db.add(SpaceMembership(space_id=UUID(space), account_id=owner.id, role="member"))
            for workspace, asset, account_id in [
                (requester, b_case, UUID(user["id"])),
                (private, a_case, owner.id),
            ]:
                conversation = db.get(Conversation, UUID(workspace["id"]))
                conversation.account_id = account_id
                conversation.context = {
                    "phase": "maintenance",
                    "selected_targets": [
                        {
                            "label": "Private selection",
                            "target": {
                                "kind": "case",
                                "case_ids": [asset["id"]],
                                "candidate_refs": ["keep-draft"],
                            },
                        }
                    ],
                }
                db.add(
                    WorkspaceCandidate(
                        conversation_id=conversation.id,
                        ref="keep-draft",
                        version=3,
                        snapshot={"title": "Private draft"},
                        status="candidate",
                        position=0,
                        included=False,
                        created_by=account_id,
                    )
                )
            db.commit()
        proposed = await proposal(client, monkeypatch, requester["id"], delete_a["id"])
        assert private["id"] not in str(proposed)
        assert "Private draft" not in str(proposed)
        with get_session_factory()() as db:
            row = db.get(Conversation, UUID(requester["id"]))
            assert "workbench_selection" not in row.context  # Preview has no migration effect.
            if change_after_review == "selection":
                row.context = {**row.context, "selected_targets": []}
            elif change_after_review == "candidate_version":
                db.add(
                    WorkspaceCandidate(
                        conversation_id=row.id,
                        ref="keep-draft",
                        version=4,
                        snapshot={"title": "New draft"},
                        status="candidate",
                        position=0,
                        included=False,
                        created_by=row.account_id,
                    )
                )
            db.commit()
        response = await client.post(
            approval_url(requester["id"], proposed),
            json={"name": proposed["name"], "collection_id": delete_a["id"]},
        )
        if change_after_review:
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == "collection_impact_changed"
        else:
            assert response.status_code == 200, response.text
        with get_session_factory()() as db:
            assert db.get(Conversation, UUID(unrelated["id"])).context == unrelated_before
            assert db.get(Conversation, UUID(stale["id"])).context == stale_before
            assert (db.get(CaseCollection, UUID(delete_a["id"])).deleted_at is not None) == (
                change_after_review is None
            )
            for workspace, asset in [(requester, b_case), (private, a_case)]:
                conversation = db.get(Conversation, UUID(workspace["id"]))
                assert str(conversation.collection_id) == keep_b["id"]
                if not change_after_review:
                    state = conversation.context["workbench_selection"]
                    assert state["active_collection_id"] == keep_b["id"]
                    expected = {"candidate:keep-draft": "3"}
                    if workspace == requester:
                        expected[f"asset:{b_case['id']}"] = b_case["current_revision_id"]
                    assert {item["ref"]: item["version"] for item in state["items"]} == expected
                assert (
                    str(db.get(CaseRecord, UUID(asset["id"])).current_revision_id)
                    == (asset["current_revision_id"])
                )


@pytest.mark.parametrize(
    "state",
    [
        {"version": 1, "items": [{"ref": "asset:missing-version"}]},
        {"version": 1, "items": [{"ref": "candidate:x", "version": ""}]},
        {"version": True, "items": []},
        {"version": 1, "items": None},
    ],
)
def test_effective_canonical_never_silently_rebinds_missing_versions(monkeypatch, state):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from casepilot_api import workbench_selection as selection

    conversation = SimpleNamespace(collection_id=None, context={"workbench_selection": state})
    monkeypatch.setattr(selection, "authorize", lambda *a: None)
    resolver = Mock(side_effect=AssertionError("Invalid canonical state must not be resolved"))
    monkeypatch.setattr(selection, "_resolve_sources", resolver)
    with pytest.raises(HTTPException) as error:
        effective_selection(None, None, conversation)
    assert error.value.status_code == 409
    assert error.value.detail == "invalid_workbench_selection"
    resolver.assert_not_called()


def test_canonical_scope_wrapper_never_promotes_legacy_to_cross_collection_scope(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from casepilot_api import workbench_selection as selection

    conversation = SimpleNamespace(
        context={
            "selected_targets": [
                {"label": "Legacy", "target": {"kind": "case", "case_ids": [str(uuid4())]}}
            ]
        }
    )
    authorization = Mock()
    monkeypatch.setattr(selection, "authorize", authorization)
    resolver = Mock(side_effect=AssertionError("Legacy fallback must not reach scope resolver"))
    monkeypatch.setattr(selection, "resolve_selection_payload", resolver)
    with pytest.raises(HTTPException) as error:
        selection.canonical_scope_payload(None, None, conversation, None)
    assert error.value.detail == "workbench_selection_missing"
    authorization.assert_called_once()
    resolver.assert_not_called()


def test_unknown_cross_collection_legacy_impact_is_not_silently_ignored():
    from types import SimpleNamespace

    from casepilot_api.workbench_collection_delete import _selection_references_collection

    conversation = SimpleNamespace(
        collection_id=uuid4(),
        context={
            "selected_targets": [{"kind": "previous_result", "source_operation_id": str(uuid4())}]
        },
    )
    with pytest.raises(HTTPException) as error:
        _selection_references_collection(conversation, str(uuid4()), set())
    assert error.value.status_code == 409
    assert error.value.detail == "collection_impact_unresolved"


def test_canonical_effective_state_rejects_inconsistent_destination(monkeypatch):
    from types import SimpleNamespace

    from casepilot_api import workbench_selection as selection

    conversation = SimpleNamespace(
        collection_id=uuid4(),
        context={"workbench_selection": {"version": 1, "items": [], "active_collection_id": None}},
    )
    monkeypatch.setattr(selection, "authorize", lambda *a: None)
    with pytest.raises(HTTPException) as error:
        effective_selection(None, None, conversation)
    assert error.value.detail == "workbench_destination_changed"
