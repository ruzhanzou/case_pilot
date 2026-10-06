from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api import conversations
from casepilot_api.models import ConversationMessage, TestCaseRevision as Revision
from casepilot_api.schemas import ChangeSetApplyRequest


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
