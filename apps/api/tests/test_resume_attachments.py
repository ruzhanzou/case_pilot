from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api import conversations
from casepilot_api.schemas import ConversationOperationResumeRequest


@pytest.mark.parametrize('available', [False, True])
def test_resume_validates_new_evidence_before_planning_and_invalidates_old_confirmation(monkeypatch, available):
    old_doc, new_doc, new_source = map(lambda _: uuid4(), range(3))
    conversation = SimpleNamespace(id=uuid4(), space_id=uuid4(), context={})
    operation = SimpleNamespace(id=uuid4(), conversation_id=conversation.id,
        message_id=uuid4(), sequence=0, intent='CASE_MODIFY', status='failed',
        payload={'last_confirmed_modification': {'old': 'approval'},
                 'modification_confirmation': {'old': 'approval'}, 'rewrite_draft': {} })
    message = SimpleNamespace(id=operation.message_id, content='按附件修改步骤',
        message_metadata={'request': {'content': '按附件修改步骤', 'document_ids': [str(old_doc)]}})
    db = Mock(); db.scalar.return_value = operation; db.scalars.return_value = []; db.get.return_value = message
    monkeypatch.setattr(conversations, '_ensure_conversation', lambda *_: conversation)
    monkeypatch.setattr(conversations, '_require_idle_conversation', lambda *_: None)
    resolve = Mock(side_effect=(lambda db, conv, request, **kw: request) if available else
                   HTTPException(422, 'attachment_not_ready_or_expired'))
    monkeypatch.setattr(conversations, '_resolve_turn_attachments', resolve)
    rewrite = Mock(return_value='continued')
    monkeypatch.setattr(conversations, '_resume_rewrite_draft', rewrite)
    supplement = ConversationOperationResumeRequest(content='按新附件补充', document_ids=[new_doc], knowledge_source_ids=[new_source])
    if not available:
        with pytest.raises(HTTPException) as error:
            conversations.resume_conversation_operation(operation.id, supplement, Mock(), db)
        assert error.value.status_code == 422
        rewrite.assert_not_called()
        assert operation.payload['modification_confirmation'] == {'old': 'approval'}
    else:
        assert conversations.resume_conversation_operation(operation.id, supplement, Mock(), db) == 'continued'
        assert operation.payload['attachment_context'] == {'document_ids': [str(old_doc), str(new_doc)], 'knowledge_source_ids': [str(new_source)]}
        assert operation.payload['modification_confirmation'] is None
        assert operation.payload['last_confirmed_modification'] is None
        assert not rewrite.call_args.args[-1].confirm_modification
    request = resolve.call_args.args[2]
    assert request.document_ids == [old_doc, new_doc]
    assert request.knowledge_source_ids == [new_source]
    assert message.message_metadata['request']['document_ids'] == [str(old_doc)]
