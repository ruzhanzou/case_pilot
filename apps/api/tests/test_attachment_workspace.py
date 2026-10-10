from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from casepilot_api import conversations
from casepilot_api.schemas import ConversationMessageCreate


def test_empty_generation_collection_does_not_call_scope_model(monkeypatch):
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *_: [])
    monkeypatch.setattr(
        conversations,
        "select_case_scope",
        lambda *_args, **_kw: (_ for _ in ()).throw(AssertionError("Unnecessary model call")),
    )
    db = SimpleNamespace(scalars=lambda _: [])
    payload = ConversationMessageCreate(content="生成登录模块用例")
    result, error = conversations._resolve_model_scope(
        db, SimpleNamespace(id=uuid4()), payload, "CASE_GENERATE"
    )
    assert error is None
    assert result.content == payload.content
    assert result.target_case_ids == []


def test_upload_stays_pending_until_a_later_user_message_is_sent():
    now = datetime.now(UTC)
    document = SimpleNamespace(
        id=uuid4(),
        original_name="登录.txt",
        size_bytes=1024,
        status="ready",
        created_at=now,
    )
    conversation = SimpleNamespace(space_id=uuid4(), context={"document_ids": [str(document.id)]})
    db = SimpleNamespace(scalars=lambda _: [document])
    pending = []
    assert conversations._messages_with_attachments(db, conversation, [], pending) == []
    assert pending[0]["name"] == "登录.txt"

    def message(role, created_at):
        return SimpleNamespace(
            id=uuid4(),
            role=role,
            content="消息",
            intent=None,
            intent_confidence=None,
            status="completed",
            target_case_ids=[],
            related_job_id=None,
            citations=[],
            message_metadata={},
            created_at=created_at,
        )

    old = message("user", now - timedelta(seconds=1))
    assistant = message("assistant", now + timedelta(seconds=1))
    sent = message("user", now + timedelta(seconds=2))
    later = message("user", now + timedelta(seconds=3))
    pending = []
    views = conversations._messages_with_attachments(db, conversation, [old, assistant], pending)
    assert len(pending) == 1
    assert all(not view.metadata.get("attachments") for view in views)
    pending = []
    views = conversations._messages_with_attachments(
        db, conversation, [old, assistant, sent, later], pending
    )
    assert pending == []
    assert len(views) == 4
    assert views[2].metadata["attachments"][0]["id"] == str(document.id)
    assert not views[3].metadata.get("attachments")
    assert sent.message_metadata == {}  # A read does not mutate the stored message.
    document.status = "failed"
    assert (
        conversations._messages_with_attachments(db, conversation, [sent])[0].metadata[
            "attachments"
        ][0]["status"]
        == "failed"
    )
