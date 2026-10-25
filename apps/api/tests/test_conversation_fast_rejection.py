"""Invalid requests must not wait for a model before receiving a response."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api import conversations
from casepilot_api.schemas import ConversationMessageCreate


def test_busy_conversation_rejects_before_model(monkeypatch):
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "_ensure_conversation", Mock(return_value=SimpleNamespace()))
    monkeypatch.setattr(conversations, "_require_idle_conversation",
                        Mock(side_effect=HTTPException(409, "conversation_busy")))
    model = Mock(side_effect=AssertionError("model must not run"))
    monkeypatch.setattr(conversations, "interpret_generation_choice", model)
    with pytest.raises(HTTPException) as error:
        conversations._send_message(
            uuid4(), ConversationMessageCreate(content="继续"), Mock(), Mock()
        )
    assert error.value.status_code == 409
    model.assert_not_called()


def test_new_conversation_skips_retry_model(monkeypatch):
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    db = Mock()
    db.scalars.return_value = []
    model = Mock(side_effect=AssertionError("no task exists to retry"))
    monkeypatch.setattr(conversations, "interpret_generation_choice", model)
    assert conversations._retry_generation_from_text(
        db, Mock(), SimpleNamespace(id=uuid4()),
        ConversationMessageCreate(content="生成登录用例"),
    ) is None
    model.assert_not_called()


@pytest.mark.parametrize('phase', ['idle', 'maintenance', 'candidate_review'])
def test_ordinary_live_turn_routes_without_generation_strategy(monkeypatch, phase):
    conversation = SimpleNamespace(id=uuid4(), context={'phase': phase})
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'openai_compatible')
    monkeypatch.setattr(conversations, '_ensure_conversation', lambda *args: conversation)
    monkeypatch.setattr(conversations, '_require_idle_conversation', lambda *args: None)
    monkeypatch.setattr(conversations, '_retry_generation_from_text', lambda *args: None)
    model = Mock(side_effect=AssertionError('unrelated generation interpretation'))
    monkeypatch.setattr(conversations, 'interpret_generation_choice', model)

    class ReachedAttachmentResolution(Exception):
        pass

    def stop_at_attachments(*args):
        raise ReachedAttachmentResolution

    monkeypatch.setattr(conversations, '_resolve_turn_attachments', stop_at_attachments)
    with pytest.raises(ReachedAttachmentResolution):
        conversations._send_message(uuid4(), ConversationMessageCreate(content='查询登录用例'),
                                    Mock(), Mock())
    model.assert_not_called()


def test_brief_review_keeps_pre_routing_generation_interpretation(monkeypatch):
    conversation = SimpleNamespace(id=uuid4(), context={'phase': 'brief_review'})
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'openai_compatible')
    monkeypatch.setattr(conversations, '_ensure_conversation', lambda *args: conversation)
    monkeypatch.setattr(conversations, '_require_idle_conversation', lambda *args: None)
    monkeypatch.setattr(conversations, '_retry_generation_from_text', lambda *args: None)
    model = Mock(return_value=SimpleNamespace(strategy='select_and_generate'))
    monkeypatch.setattr(conversations, 'interpret_generation_choice', model)
    stop = Mock(side_effect=HTTPException(409, 'test_boundary'))
    monkeypatch.setattr(conversations, '_resolve_turn_attachments', stop)
    with pytest.raises(HTTPException):
        conversations._send_message(uuid4(), ConversationMessageCreate(content='确认规划'),
                                    Mock(), Mock())
    model.assert_called_once()
    assert stop.call_args.args[2].generation_strategy == 'select_and_generate'


@pytest.mark.parametrize("failure", ["connection", "timeout", "rate_limit", "server"])
def test_collection_model_failure_is_retryable_without_scope_fallback(monkeypatch, failure):
    import httpx
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    request = httpx.Request("POST", "https://model.invalid/chat/completions")
    errors = {
        "connection": APIConnectionError(request=request),
        "timeout": APITimeoutError(request=request),
        "rate_limit": RateLimitError("limited", response=httpx.Response(429, request=request), body=None),
        "server": InternalServerError("failed", response=httpx.Response(500, request=request), body=None),
    }
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "interpret_generation_choice", Mock(side_effect=errors[failure]))
    db = Mock()
    db.execute.return_value = [(uuid4(), "当前集合")]
    with pytest.raises(HTTPException) as error:
        conversations._collection_candidates(db, SimpleNamespace(space_id=uuid4(), collection_id=None), "审阅当前集合")
    assert error.value.status_code == 503
    assert "未执行" in error.value.detail
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("status", ["completed", "awaiting_target", "awaiting_confirmation", "cancelled"])
@pytest.mark.parametrize("content", ["只改第一条，改成P2", "确认", "查询支付模块", "解释边界值"])
def test_healthy_task_continuation_skips_unrelated_retry_model(monkeypatch, status, content):
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    db = Mock()
    db.scalar.return_value = SimpleNamespace(intent="CASE_MODIFY", status=status)
    db.scalars.return_value = [SimpleNamespace(role="assistant", content="请确认修改范围")]
    model = Mock(side_effect=AssertionError("healthy task cannot retry"))
    monkeypatch.setattr(conversations, "interpret_generation_choice", model)
    assert conversations._retry_generation_from_text(
        db, Mock(), SimpleNamespace(id=uuid4()), ConversationMessageCreate(content=content)
    ) is None
    model.assert_not_called()


@pytest.mark.parametrize("intent,status", [("CASE_MODIFY", "failed"), ("CASE_QUERY", "queued"),
                                           ("CASE_GENERATE", "completed")])
def test_retry_eligible_states_keep_semantic_retry_interpretation(monkeypatch, intent, status):
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    db = Mock()
    db.scalar.return_value = SimpleNamespace(intent=intent, status=status)
    db.scalars.return_value = [SimpleNamespace(role="assistant", content="当前任务结果")]
    model = Mock(return_value=SimpleNamespace(retry_requested=False))
    monkeypatch.setattr(conversations, "interpret_generation_choice", model)
    assert conversations._retry_generation_from_text(
        db, Mock(), SimpleNamespace(id=uuid4()), ConversationMessageCreate(content="只修改标题")
    ) is None
    model.assert_called_once()


def test_explicit_retry_of_healthy_task_is_rejected_without_model(monkeypatch):
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    db = Mock()
    db.scalar.return_value = SimpleNamespace(intent="CASE_QUERY", status="completed")
    db.scalars.return_value = [SimpleNamespace(role="assistant", content="查询完成")]
    model = Mock(side_effect=AssertionError("no retryable task"))
    monkeypatch.setattr(conversations, "interpret_generation_choice", model)
    with pytest.raises(HTTPException) as error:
        conversations._retry_generation_from_text(db, Mock(), SimpleNamespace(id=uuid4()),
                                                  ConversationMessageCreate(content="重试"))
    assert error.value.detail == "message_not_retryable"
    model.assert_not_called()
