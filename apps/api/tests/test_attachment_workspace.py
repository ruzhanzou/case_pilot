from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from casepilot_api import conversations
from casepilot_api.schemas import ConversationMessageCreate


def test_empty_generation_collection_does_not_call_scope_model(monkeypatch):
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *_: [])
    monkeypatch.setattr(conversations, "select_case_scope", lambda *_args, **_kw: (
        (_ for _ in ()).throw(AssertionError("Unnecessary model call"))
    ))
    db = SimpleNamespace(scalars=lambda _: [])
    payload = ConversationMessageCreate(content="生成登录模块用例")
    result, error = conversations._resolve_model_scope(
        db, SimpleNamespace(id=uuid4()), payload, "CASE_GENERATE"
    )
    assert error is None
    assert result.content == payload.content
    assert result.target_case_ids == []


def test_legacy_attachment_links_restore_timeline_with_live_status():
    document = SimpleNamespace(
        id=uuid4(), original_name="登录.txt", size_bytes=1024, status="ready",
        created_at=datetime.now(UTC),
    )
    conversation = SimpleNamespace(
        space_id=uuid4(), context={"document_ids": [str(document.id)]},
    )
    db = SimpleNamespace(scalars=lambda _: [document])
    messages = conversations._messages_with_attachments(db, conversation, [])
    assert len(messages) == 1
    assert messages[0].id == document.id
    assert messages[0].metadata["attachments"][0]["name"] == "登录.txt"
    document.status = "failed"
    assert conversations._messages_with_attachments(
        db, conversation, []
    )[0].metadata["attachments"][0]["status"] == "failed"
