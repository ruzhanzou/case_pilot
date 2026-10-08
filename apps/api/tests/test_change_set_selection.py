from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api import conversations
from casepilot_api.models import ConversationMessage, TestCaseRevision as Revision
from casepilot_api.schemas import ChangeSetApplyRequest


def test_conflicting_proposal_stops_waiting_for_confirmation():
    db = Mock()
    operation = SimpleNamespace(status="awaiting_confirmation", result={"kept": True})
    db.scalar.return_value = operation
    proposal = SimpleNamespace(id=uuid4(), status="ready")
    conversations._mark_change_set_conflict(db, proposal)
    assert proposal.status == "conflict"
    assert operation.status == "failed"
    assert operation.result == {"kept": True, "change_set_status": "conflict"}
    assert operation.completed_at <= datetime.now(UTC)
    db.commit.assert_called_once()


@pytest.mark.parametrize("operation,fields", [("modify", []), ("modify", ["unknown"]), ("delete", [])])
def test_unselected_case_does_not_write_revision_or_delete(monkeypatch, operation, fields):
    case_id, revision_id = uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, current_revision_id=revision_id, deleted_at=None)
    item = {"ref": str(case_id), "test_case_id": str(case_id), "target_type": "formal",
            "base_revision_id": str(revision_id), "operation": operation,
            "field_diff": [{"field": "delete" if operation == "delete" else "title", "before": "Old", "after": "New"}]}
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction="Selected changes", scope="current", status="ready", items=[item],
        created_at=datetime.now(UTC), applied_at=None)
    db = Mock()
    db.scalar.side_effect = [case, None]
    monkeypatch.setattr(conversations, "_ensure_change_set", lambda *args: change)
    result = conversations.apply_change_set(change.id,
        ChangeSetApplyRequest(accepted_fields={str(case_id): fields}), SimpleNamespace(id=uuid4()), db)
    assert case.current_revision_id == revision_id
    assert case.deleted_at is None
    assert result.change_set.items[0]["status"] == "rejected"
    assert not any(isinstance(call.args[0], Revision) for call in db.add.call_args_list)
    messages = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], ConversationMessage)]
    assert "0 条" in messages[0].content


def test_previous_generation_uses_committed_formal_cases():
    from casepilot_api.schemas import ConversationMessageCreate, ConversationTarget
    conversation_id, formal_id, candidate_id, operation_id = (uuid4() for _ in range(4))
    db = Mock()
    db.get.return_value = SimpleNamespace(conversation_id=conversation_id,
        result={"candidate_ids": [str(candidate_id)], "test_case_ids": [str(formal_id)]})
    db.scalars.return_value = [formal_id]
    result = conversations._expand_conversation_targets(db,
        SimpleNamespace(id=conversation_id, collection_id=uuid4(), context={"phase": "maintenance"}),
        ConversationMessageCreate(content="评审刚才生成的用例", targets=[
            ConversationTarget(kind="previous_result", source_operation_id=operation_id)]))
    assert result.target_case_ids == [formal_id]
    assert result.target_candidate_snapshots == []
    db.scalars.assert_called_once()  # collection membership is still checked


def test_single_discard_keeps_other_items_pending_and_retry_is_idempotent(monkeypatch):
    refs = [str(uuid4()), str(uuid4())]
    items = [{'ref': ref, 'target_type': 'formal', 'status': 'ready', 'operation': 'modify',
              'field_diff': [{'field': 'title'}]} for ref in refs]
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction='Review', scope='current', status='ready', items=items,
        created_at=datetime.now(UTC), applied_at=None)
    operation = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', status='awaiting_confirmation', result={})
    db = Mock(); db.scalar.return_value = operation
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    account = SimpleNamespace(id=uuid4())
    request = ChangeSetApplyRequest(accepted_fields={refs[0]: []}, review_refs=[refs[0]])
    conversations.apply_change_set(change.id, request, account, db)
    assert change.status == 'ready'
    assert [item['status'] for item in change.items] == ['rejected', 'ready']
    assert operation.status == 'awaiting_confirmation'
    assert operation.completed_at is None
    calls = db.add.call_count
    conversations.apply_change_set(change.id, request, account, db)
    assert db.add.call_count == calls
    conversations.apply_change_set(change.id, ChangeSetApplyRequest(accepted_fields={refs[1]: []}, review_refs=[refs[1]]), account, db)
    assert operation.status == 'completed'
    assert all(item['status'] == 'rejected' for item in change.items)


def test_single_review_rejects_unknown_refs(monkeypatch):
    from fastapi import HTTPException
    change = SimpleNamespace(status='ready', items=[{'ref':'known'}])
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    with pytest.raises(HTTPException) as error:
        conversations.apply_change_set(uuid4(), ChangeSetApplyRequest(review_refs=['other']), SimpleNamespace(id=uuid4()), Mock())
    assert error.value.status_code == 422


def test_discard_remaining_preserves_already_accepted_items(monkeypatch):
    accepted, pending = str(uuid4()), str(uuid4())
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction='Review', scope='current', status='ready', created_at=datetime.now(UTC), applied_at=None,
        items=[{'ref':accepted,'status':'applied','target_type':'formal','field_diff':[]},
               {'ref':pending,'status':'ready','target_type':'formal','field_diff':[{'field':'title'}]}])
    operation = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', status='awaiting_confirmation', result={})
    db = Mock(); db.scalar.return_value = operation
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    result = conversations.reject_change_set(change.id, SimpleNamespace(id=uuid4()), db)
    assert result.status == 'applied'
    assert [item['status'] for item in result.items] == ['applied','rejected']
    assert operation.status == 'completed'
    message = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], ConversationMessage))
    assert '已采纳 1 条' in message.content and '已丢弃 1 条' in message.content


@pytest.mark.parametrize('followers', [0, 1])
def test_reject_middle_change_stops_only_queued_followers(monkeypatch, followers):
    change = SimpleNamespace(id=uuid4(), conversation_id=uuid4(), generation_job_id=None,
        instruction='Review', scope='current', status='ready', items=[],
        created_at=datetime.now(UTC), applied_at=None)
    operation = SimpleNamespace(id=uuid4(), message_id=uuid4(), sequence=1,
        intent='CASE_MODIFY', status='awaiting_confirmation')
    db = Mock(); db.scalar.return_value = operation
    db.execute.return_value.rowcount = followers
    monkeypatch.setattr(conversations, '_ensure_change_set', lambda *args: change)
    conversations.reject_change_set(change.id, SimpleNamespace(id=uuid4()), db)
    assert operation.status == 'cancelled'
    statement = db.execute.call_args.args[0]
    parameters = statement.compile().params
    assert operation.message_id in parameters.values()
    assert operation.sequence in parameters.values()
    assert 'queued' in parameters.values()
    assert 'cancelled' in parameters.values()
    messages = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], ConversationMessage)]
    assert ('后续任务已停止' in messages[0].content) == bool(followers)
