"""API dialogue calls must honor the generation task's AI configuration."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api import conversations
from casepilot_api.config import Settings
from casepilot_api.rewrite_dialogue import RewriteReply


@pytest.fixture
def ai_settings(monkeypatch):
    monkeypatch.setenv("CASEPILOT_ENV", "development")
    monkeypatch.setenv("CASEPILOT_AI_MODE", "mock")
    monkeypatch.setenv("CASEPILOT_AGENT_PROVIDER", "mock")
    return Settings(
        _env_file=None,
        CASEPILOT_AGENT_MODEL="default-model",
        CASEPILOT_AGENT_PRO_MODEL="quality-model",
        CASEPILOT_AGENT_LOCAL_MODEL="local-model",
        CASEPILOT_AGENT_MODELS="default-model,quality-model,local-model,custom-model",
    )


@pytest.mark.parametrize("model_id,expected", [
    ("auto", "default-model"),
    ("pro", "quality-model"),
    ("test-design-pro", "quality-model"),
    ("local", "local-model"),
    ("custom-model", "custom-model"),
    ("unconfigured", "default-model"),
])
def test_rewrite_reply_uses_original_task_model(monkeypatch, ai_settings, model_id, expected):
    monkeypatch.setattr(conversations, "settings", ai_settings)
    interpreter = Mock(return_value=RewriteReply(action="clarify", clarification="请补充要求"))
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", interpreter)
    monkeypatch.setattr(conversations, "_same_confirmation_targets", lambda *args: True)
    monkeypatch.setattr(conversations, "_rewrite_reply_turn", lambda *args: None)
    operation = SimpleNamespace(
        id=uuid4(), intent="CASE_MODIFY", confidence=1.0, target={},
        payload={"instruction": "修改步骤", "rewrite_draft": {
            "scope_resolved": True, "requirements_ready": True,
        }},
    )
    message = SimpleNamespace(content="修改步骤", message_metadata={"request": {"model_id": model_id}})
    supplement = SimpleNamespace(confirm_modification=False, content="再详细一些")
    conversations._resume_rewrite_draft(
        Mock(), None, SimpleNamespace(id=uuid4()), operation, message, supplement,
    )
    assert interpreter.call_args.kwargs["model_name"] == expected


def test_api_accepts_worker_fallback_key(monkeypatch, ai_settings):
    monkeypatch.delenv("CASEPILOT_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fallback-test-key")
    assert Settings(_env_file=None).agent_api_key == "fallback-test-key"
    monkeypatch.setenv("CASEPILOT_AGENT_API_KEY", "primary-test-key")
    assert Settings(_env_file=None).agent_api_key == "primary-test-key"
