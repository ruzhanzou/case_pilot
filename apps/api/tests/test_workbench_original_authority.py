"""Controlled segments reuse real user authority without text approval routing."""
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import setup

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Conversation, ConversationMessage, ConversationOperation
from casepilot_api.schemas import ConversationMessageCreate


@pytest.mark.asyncio
async def test_preparation_reuses_original_user_and_allocates_operation_sequence(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A controlled segment must not interpret user approval or retry text")

    for name in ("_retry_generation_from_text", "_resume_model_selected_operation",
                 "confirm_test_brief", "confirm_generation_assets", "interpret_generation_choice"):
        monkeypatch.setattr(conversations, name, forbidden)

    def prepare(db, account, conversation, user_message, payload, intent, confidence,
                operation_id, **kwargs):
        assistant = conversations._new_assistant_message(
            conversation.id, content="Observed", intent=intent, confidence=confidence,
            status="completed", target_case_ids=[], metadata={},
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "read"}, None

    monkeypatch.setattr(conversations, "_start_action", prepare)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
    with get_session_factory()() as db:
        conversation = db.get(Conversation, UUID(workspace["id"]))
        account = db.get(Account, conversation.account_id)
        conversation.context = {**dict(conversation.context), "phase": "brief_review"}
        root = ConversationMessage(
            conversation_id=conversation.id, role="user", content="确认", intent="KNOWLEDGE_QA",
            intent_confidence=1.0, status="completed", target_case_ids=[], citations=[],
            message_metadata={"request": {"content": "确认"}},
        )
        db.add(root)
        db.commit()
        original = dict(root.message_metadata)
        payload = ConversationMessageCreate(content="确认", intent_override="KNOWLEDGE_QA")
        first = conversations.prepare_workbench_action(db, account, conversation, payload, root.id)
        second = conversations.prepare_workbench_action(db, account, conversation, payload, root.id)
        assert first.user_message.id == second.user_message.id == root.id
        assert db.scalar(select(func.count()).select_from(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.role == "user",
        )) == 1
        assert list(db.scalars(select(ConversationOperation.sequence).where(
            ConversationOperation.message_id == root.id,
        ).order_by(ConversationOperation.sequence))) == [0, 1]
        assert root.message_metadata == original


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["role", "conversation", "content", "missing"])
async def test_preparation_rejects_invalid_original_authority(monkeypatch, invalid):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
    with get_session_factory()() as db:
        conversation = db.get(Conversation, UUID(workspace["id"]))
        account = db.get(Account, conversation.account_id)
        root = ConversationMessage(
            conversation_id=conversation.id, role="assistant" if invalid == "role" else "user",
            content="original", intent="KNOWLEDGE_QA", intent_confidence=1.0,
            status="completed", target_case_ids=[], citations=[], message_metadata={},
        )
        db.add(root)
        db.flush()
        # Keep an invalid row local to this transaction; never violate the FK.
        if invalid == "conversation":
            root.conversation_id = uuid4()
        payload = ConversationMessageCreate(
            content="replacement" if invalid == "content" else "original",
            intent_override="KNOWLEDGE_QA",
        )
        with pytest.raises(HTTPException) as failure:
            conversations.prepare_workbench_action(
                db, account, conversation, payload, uuid4() if invalid == "missing" else root.id,
            )
        assert failure.value.detail == "workbench_original_authority_mismatch"
        db.rollback()
