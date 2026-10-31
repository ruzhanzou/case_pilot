from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api import workbench_selection as selection
from casepilot_api.schemas import ConversationMessageCreate
from casepilot_api.workbench_plan import TaskContext
from casepilot_api.workbench_sources import bounded_rows, source_version, uploaded_row_identity


class DB:
    def __init__(self):
        self.operations = []
        self.flushed = False

    def scalar(self, query):
        return None

    def scalars(self, query):
        return self.operations

    def flush(self):
        self.flushed = True


@pytest.fixture
def workspace(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    conversation = SimpleNamespace(
        id=uuid4(), account_id=account.id, space_id=uuid4(), collection_id=None, context={}
    )
    versions = {"asset:" + str(uuid4()): "v1", "asset:" + str(uuid4()): "v2"}

    def resolve(db, account, conversation, sources):
        result = []
        for source in sources:
            source = source.model_dump() if hasattr(source, "model_dump") else source
            ref = source["ref"]
            if ref not in versions:
                raise HTTPException(404, "source_not_found")
            if source.get("version") and source["version"] != versions[ref]:
                raise HTTPException(409, "workbench_source_changed")
            result.append(
                {
                    "ref": ref,
                    "kind": "asset",
                    "version": versions[ref],
                    "case_id": ref[6:],
                    "label": ref,
                }
            )
        return result

    monkeypatch.setattr(selection, "authorize", lambda *args: None)
    monkeypatch.setattr(selection, "_resolve_sources", resolve)
    return DB(), account, conversation, versions


def change(workspace, action="replace", refs=None, base=None):
    db, account, conversation, versions = workspace
    state = selection.selection_state(conversation)
    return selection.update_selection(
        db,
        account,
        conversation,
        selection.SelectionUpdate(
            base_version=base if base is not None else state["version"] if state else 0,
            action=action,
            sources=[{"ref": ref, "version": versions[ref]} for ref in refs or []],
        ),
    )


def test_cas_replace_add_remove_clear(workspace):
    refs = list(workspace[3])
    assert change(workspace, refs=refs[:1])["version"] == 1
    assert len(change(workspace, "add", refs[1:])["items"]) == 2
    assert len(change(workspace, "remove", refs[:1])["items"]) == 1
    assert change(workspace, "clear")["items"] == []
    with pytest.raises(HTTPException) as error:
        change(workspace, refs=refs, base=1)
    assert error.value.status_code == 409


def test_explicit_old_target_without_version_never_replaced_by_current(workspace):
    db, account, conversation, versions = workspace
    refs = list(versions)
    change(workspace, refs=refs[1:])
    original = deepcopy(conversation.context)
    with pytest.raises(HTTPException) as error:
        selection.resolve_selection_payload(
            db,
            account,
            conversation,
            ConversationMessageCreate(content="rewrite this", target_case_ids=[refs[0][6:]]),
        )
    assert error.value.detail == "workbench_selection_target_conflict"
    assert conversation.context == original


def test_explicit_subset_never_broadened(workspace):
    db, account, conversation, versions = workspace
    refs = list(versions)
    change(workspace, refs=refs)
    result = selection.resolve_selection_payload(
        db,
        account,
        conversation,
        ConversationMessageCreate(content="rewrite this", target_case_ids=[refs[0][6:]]),
    )
    assert list(map(str, result.target_case_ids)) == [refs[0][6:]]


def test_empty_canonical_is_explicit_empty(workspace):
    db, account, conversation, _ = workspace
    change(workspace, "clear")
    result = selection.resolve_selection_payload(
        db, account, conversation, ConversationMessageCreate(content="rewrite")
    )
    assert result.target_scope == "selected"
    assert result.target_case_ids == []


def test_old_proposal_stale_after_selection_change(workspace):
    db, _, conversation, versions = workspace
    operation = SimpleNamespace(payload={})
    db.operations.append(operation)
    change(workspace, refs=list(versions)[:1])
    with pytest.raises(HTTPException):
        selection.assert_selection_binding(conversation, operation)


def test_own_apply_updates_only_changed_refs_and_producing_proposal(workspace):
    db, account, conversation, versions = workspace
    refs = list(versions)
    change(workspace, refs=refs)
    operation = SimpleNamespace(payload={})
    selection.stamp_operation_binding(conversation, operation)
    other = SimpleNamespace(payload=deepcopy(operation.payload))
    versions[refs[0]] = "new"
    versions[refs[1]] = "external"
    selection.refresh_selection_after_apply(db, account, conversation, operation, refs[:1])
    state = selection.selection_state(conversation)
    assert [item["version"] for item in state["items"]] == ["new", "v2"]
    selection.assert_selection_binding(conversation, operation)
    with pytest.raises(HTTPException):
        selection.assert_selection_binding(conversation, other)


def test_delete_refresh_removes_without_resolving_discarded(workspace):
    db, account, conversation, versions = workspace
    refs = list(versions)
    change(workspace, refs=refs)
    operation = SimpleNamespace(payload={})
    selection.stamp_operation_binding(conversation, operation)
    del versions[refs[0]]
    selection.refresh_selection_after_apply(db, account, conversation, operation, [], refs[:1])
    assert [item["ref"] for item in selection.selection_state(conversation)["items"]] == refs[1:]


def test_plan_catalog_projection_no_snapshot_copy_and_identity_version():
    conversation = SimpleNamespace(context={})
    context = TaskContext(conversation)
    context.remember_sources(
        [{"ref": "asset:a", "kind": "asset", "version": "1", "snapshot": {"title": "large"}}]
    )
    assert "snapshot" not in conversation.context["workbench_plan"]["source_catalog"]["asset:a"]
    assert uploaded_row_identity("doc", "sheet", 3) == uploaded_row_identity("doc", "sheet", 3)
    assert uploaded_row_identity("doc", "sheet", 3) != uploaded_row_identity("doc", "sheet", 4)
    assert source_version({"title": "one"}, {"row": 1}) != source_version(
        {"title": "two"}, {"row": 1}
    )


def test_discovery_summary_does_not_mutate_exact_source():
    rows = [{"ref": "asset:a", "snapshot": {"title": "x", "steps": ["x" * 20000]}}]
    result = bounded_rows(rows)
    assert result["cases"][0]["snapshot_truncated"]
    assert len(rows[0]["snapshot"]["steps"][0]) == 20000


def test_first_add_preserves_legacy_concrete_selection(workspace):
    _, _, conversation, versions = workspace
    refs = list(versions)
    conversation.context = {"selected_targets": [{"kind": "case", "case_ids": [refs[0][6:]]}]}
    state = change(workspace, "add", refs[1:])
    assert {item["ref"] for item in state["items"]} == set(refs)


def test_agent_selection_flush_preserves_same_turn_plan(workspace):
    db, account, conversation, versions = workspace
    TaskContext(conversation).remember_sources([{"ref": next(iter(versions)), "version": "v1"}])
    selection.update_selection(
        db,
        account,
        conversation,
        selection.SelectionUpdate(base_version=0, action="clear"),
        changed_by="agent",
    )
    assert db.flushed
    assert conversation.context["workbench_plan"]["source_catalog"]
