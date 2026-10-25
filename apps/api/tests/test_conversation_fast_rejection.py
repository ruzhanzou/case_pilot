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
