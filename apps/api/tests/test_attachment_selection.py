from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from casepilot_api.conversations import _resolve_turn_attachments
from casepilot_api.schemas import ConversationMessageCreate


def test_failed_historical_document_does_not_poison_new_upload():
    old, new, old_source, new_source = [uuid4() for _ in range(4)]
    conversation = SimpleNamespace(
        space_id=uuid4(),
        context={"document_ids": [str(old)], "knowledge_source_ids": [str(old_source)]},
    )
    db = Mock()
    db.scalars.side_effect = [
        [SimpleNamespace(id=new, source_id=new_source)],
        [SimpleNamespace(id=new_source)],
        [old_source],
    ]
    result = _resolve_turn_attachments(
        db,
        conversation,
        ConversationMessageCreate(
            content="按新附件生成", document_ids=[new], knowledge_source_ids=[new_source]
        ),
    )
    assert result.document_ids == [new]
    assert result.knowledge_source_ids == [new_source]
    query = str(db.scalars.call_args_list[0].args[0])
    assert "expires_at" in query and "deleted_at" in query and "status" in query


def test_explicit_missing_document_is_not_silently_skipped():
    db = Mock()
    db.scalars.return_value = []
    with pytest.raises(HTTPException) as error:
        _resolve_turn_attachments(
            db,
            SimpleNamespace(space_id=uuid4(), context={}),
            ConversationMessageCreate(content="使用附件", document_ids=[uuid4()]),
        )
    assert error.value.status_code == 422
    assert error.value.detail == "attachment_not_ready_or_expired"


def test_task_can_explicitly_opt_out_of_all_historical_attachments():
    db = Mock()
    conversation = SimpleNamespace(
        space_id=uuid4(),
        context={"document_ids": [str(uuid4())], "knowledge_source_ids": [str(uuid4())]},
    )
    result = _resolve_turn_attachments(
        db,
        conversation,
        ConversationMessageCreate(content="仅使用本次输入", inherit_attachments=False),
    )
    assert not result.document_ids and not result.knowledge_source_ids
    db.scalars.assert_not_called()


def test_resume_does_not_reattach_a_file_removed_after_task_was_paused():
    doc_id, source_id = uuid4(), uuid4()
    conversation = SimpleNamespace(
        space_id=uuid4(),
        context={
            "excluded_document_ids": [str(doc_id)],
            "excluded_source_ids": [str(source_id)],
        },
    )
    db = Mock()
    request = ConversationMessageCreate(
        content="继续", document_ids=[doc_id], knowledge_source_ids=[source_id]
    )
    result = _resolve_turn_attachments(db, conversation, request, resuming=True)
    assert result.document_ids == [] and result.knowledge_source_ids == []
    db.scalars.assert_not_called()


@pytest.mark.parametrize("keep_sibling", [False, True])
def test_detaching_file_excludes_whole_source_but_keeps_selected_siblings(
    monkeypatch, keep_sibling
):
    from casepilot_api import conversations

    doc_id, source_id, space_id = uuid4(), uuid4(), uuid4()
    sibling_ids = [str(uuid4())] if keep_sibling else []
    conversation = SimpleNamespace(
        space_id=space_id,
        context={
            "document_ids": [str(doc_id), *sibling_ids],
            "knowledge_source_ids": [str(source_id)],
        },
    )
    monkeypatch.setattr(conversations, "_ensure_conversation", lambda *_: conversation)
    monkeypatch.setattr(conversations, "_require_idle_conversation", lambda *_: None)
    monkeypatch.setattr(conversations, "_conversation_view", lambda *_: conversation)
    db = Mock()
    db.get.return_value = SimpleNamespace(space_id=space_id, source_id=source_id)
    conversations.detach_conversation_attachment(uuid4(), doc_id, SimpleNamespace(id=uuid4()), db)
    assert conversation.context["document_ids"] == sibling_ids
    assert conversation.context["knowledge_source_ids"] == []
    assert conversation.context["excluded_document_ids"] == [str(doc_id)]
    assert conversation.context["excluded_source_ids"] == [str(source_id)]
    db.delete.assert_not_called()
