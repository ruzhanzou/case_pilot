from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from casepilot_api import conversations as c
from casepilot_api.schemas import ConversationMessageCreate


def setup():
    conversation = SimpleNamespace(id=uuid4())
    operation = SimpleNamespace(
        id=uuid4(), conversation_id=conversation.id, intent="CASE_MODIFY", status="awaiting_target"
    )
    db = SimpleNamespace(get=Mock(return_value=operation))
    draft = dict(intent="CASE_MODIFY", resume_operation_id=str(operation.id))
    return conversation, operation, db, draft


def test_model_selected_continuation_uses_existing_task(monkeypatch):
    conversation, operation, db, draft = setup()
    resume = Mock(return_value="resumed")
    monkeypatch.setattr(c, "resume_conversation_operation", resume)
    payload = ConversationMessageCreate(content="目标是账号登录模块")
    assert c._resume_model_selected_operation(db, None, conversation, payload, [draft]) == "resumed"
    assert resume.call_args.args[0] == operation.id
    assert resume.call_args.args[1].content == payload.content
    assert not resume.call_args.args[1].confirm_modification


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversation_id", uuid4()),
        ("status", "completed"),
        ("intent", "CASE_DELETE"),
    ],
)
def test_invalid_or_foreign_resume_reference_cannot_execute(monkeypatch, field, value):
    conversation, operation, db, draft = setup()
    setattr(operation, field, value)
    resume = Mock()
    monkeypatch.setattr(c, "resume_conversation_operation", resume)
    with pytest.raises(HTTPException) as error:
        c._resume_model_selected_operation(
            db, None, conversation, ConversationMessageCreate(content="继续"), [draft]
        )
    assert error.value.status_code == 422
    resume.assert_not_called()


def test_new_or_multi_intent_request_does_not_resume(monkeypatch):
    conversation, operation, db, draft = setup()
    resume = Mock()
    monkeypatch.setattr(c, "resume_conversation_operation", resume)
    payload = ConversationMessageCreate(content="查询用例，然后修改标题")
    for drafts in ([dict(intent="CASE_QUERY")], [draft, dict(intent="CASE_QUERY")]):
        assert c._resume_model_selected_operation(db, None, conversation, payload, drafts) is None
    resume.assert_not_called()
