"""Retry resolves an operation, not the multi-action message that created it."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api import conversations
from casepilot_api.schemas import ConversationMessageCreate


@pytest.mark.parametrize('intent', ['CASE_MODIFY', 'CASE_DELETE', 'CASE_QUERY', 'CASE_REVIEW'])
def test_text_retry_uses_latest_failed_operation_and_ignores_ui_selection(monkeypatch, intent):
    db = Mock()
    conversation = SimpleNamespace(id=uuid4())
    operation = SimpleNamespace(id=uuid4(), intent=intent, status='failed')
    db.scalar.return_value = operation
    resume = Mock(return_value=Mock())
    monkeypatch.setattr(conversations, 'resume_conversation_operation', resume)
    monkeypatch.setattr(conversations, '_message_view', lambda message: message)
    conversations._retry_generation_from_text(db, Mock(), conversation,
        ConversationMessageCreate(content='重试', target_case_ids=[uuid4()]))
    assert resume.call_args.args[0] == operation.id
    assert not resume.call_args.args[1].target_case_ids
    assert db.add.call_args.args[0].message_metadata['retry_operation_id'] == str(operation.id)


@pytest.mark.parametrize('status', ['completed', 'running', 'awaiting_confirmation', 'cancelled'])
def test_text_retry_does_not_revive_older_failure(monkeypatch, status):
    db = Mock()
    db.scalar.return_value = SimpleNamespace(intent='CASE_QUERY', status=status)
    resume = Mock()
    monkeypatch.setattr(conversations, 'resume_conversation_operation', resume)
    with pytest.raises(HTTPException) as error:
        conversations._retry_generation_from_text(db, Mock(), SimpleNamespace(id=uuid4()),
            ConversationMessageCreate(content='重试'))
    assert error.value.detail == 'message_not_retryable'
    resume.assert_not_called()


@pytest.mark.parametrize('stale', [False, True])
def test_message_retry_resumes_only_current_failed_operation(monkeypatch, stale):
    cid, job_id, op_id = uuid4(), uuid4(), uuid4()
    failed = SimpleNamespace(role='assistant', status='failed', related_job_id=job_id,
                             conversation_id=cid)
    job = SimpleNamespace(id=job_id, status='failed', operation='rewrite',
                          input_payload={'conversation_operation_id': str(op_id)})
    operation = SimpleNamespace(id=op_id, conversation_id=cid, status='failed',
                                related_job_id=uuid4() if stale else job_id)
    db = Mock()
    db.get.side_effect = [failed, job, operation]
    monkeypatch.setattr(conversations, '_ensure_conversation', lambda *args: SimpleNamespace(id=cid))
    monkeypatch.setattr(conversations, '_require_idle_conversation', lambda *args: None)
    resume = Mock(return_value='resumed')
    monkeypatch.setattr(conversations, 'resume_conversation_operation', resume)
    if stale:
        with pytest.raises(HTTPException) as error:
            conversations.retry_conversation_message(uuid4(), SimpleNamespace(id=uuid4()), db)
        assert error.value.detail == 'retry_context_mismatch'
        resume.assert_not_called()
    else:
        assert conversations.retry_conversation_message(uuid4(), SimpleNamespace(id=uuid4()), db) == 'resumed'
        assert resume.call_args.args[0] == op_id


@pytest.mark.parametrize('content', ['重试修改任务', '请重试刚才失败的查询', '重试删除请求', '重试评审'])
def test_named_operation_retry_commands(content):
    assert conversations._is_generation_retry(content)


def test_named_retry_does_not_resume_different_operation(monkeypatch):
    db = Mock()
    db.scalar.return_value = SimpleNamespace(intent='CASE_MODIFY', status='failed')
    resume = Mock()
    monkeypatch.setattr(conversations, 'resume_conversation_operation', resume)
    with pytest.raises(HTTPException) as error:
        conversations._retry_generation_from_text(db, Mock(), SimpleNamespace(id=uuid4()),
            ConversationMessageCreate(content='重试查询任务'))
    assert error.value.detail == 'retry_context_mismatch'
    resume.assert_not_called()


def test_retry_compound_request_resumes_failed_predecessor(monkeypatch):
    db = Mock()
    queued = SimpleNamespace(status='queued', message_id=uuid4(), sequence=2)
    failed = SimpleNamespace(id=uuid4(), status='failed', intent='CASE_QUERY')
    db.scalar.side_effect = [queued, failed]
    resume = Mock(return_value=Mock())
    monkeypatch.setattr(conversations, 'resume_conversation_operation', resume)
    monkeypatch.setattr(conversations, '_message_view', lambda message: message)
    conversations._retry_generation_from_text(db, Mock(), SimpleNamespace(id=uuid4()),
        ConversationMessageCreate(content='重试'))
    assert resume.call_args.args[0] == failed.id


def test_natural_retry_forwards_explicit_attachments(monkeypatch):
    document, source = uuid4(), uuid4()
    db = Mock()
    db.scalar.return_value = SimpleNamespace(id=uuid4(), intent='CASE_MODIFY', status='failed')
    resume = Mock(return_value=Mock())
    monkeypatch.setattr(conversations, 'resume_conversation_operation', resume)
    monkeypatch.setattr(conversations, '_message_view', lambda message: message)
    conversations._retry_generation_from_text(db, Mock(), SimpleNamespace(id=uuid4()),
        ConversationMessageCreate(content='重试修改任务', document_ids=[document], knowledge_source_ids=[source]))
    supplement = resume.call_args.args[1]
    assert supplement.document_ids == [document]
    assert supplement.knowledge_source_ids == [source]
