"""Retry a confirmed generation without losing its identity or reviving stale work."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from casepilot_api import conversations, generation
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    Conversation,
    ConversationMessage,
    GenerationJob,
    Space,
    WorkspaceTestBrief,
)


@pytest.mark.parametrize("entry", ["button", "text", "confirmation"])
@pytest.mark.parametrize("operation", ["generate", "draft_brief"])
@pytest.mark.asyncio
async def test_retry_restores_failed_context_and_rejects_duplicate_or_changed_brief(
    monkeypatch, operation, entry,
):
    enqueued = []
    monkeypatch.setattr(generation, "enqueue_task", lambda *args, **kwargs: enqueued.append(args))
    def unexpected_routing(*args, **kwargs):
        raise AssertionError("Retry must not reclassify or create a new task")

    monkeypatch.setattr(conversations, "plan_intents", unexpected_routing)
    account_id = space_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registration = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"retry-{uuid4().hex}@casepilot.test",
                    "display_name": "Retry acceptance",
                    "password": "CasePilot123!",
                },
            )
            assert registration.status_code == 201
            account_id = UUID(registration.json()["id"])
            space_id = UUID(registration.json()["spaces"][0]["id"])
            collection = (await client.get(f"/api/v1/spaces/{space_id}/collections")).json()[0]
            workspace = (
                await client.put(f"/api/v1/collections/{collection['id']}/workspace")
            ).json()
            cid = UUID(workspace["id"])
            with get_session_factory()() as db:
                conversation = db.get(Conversation, cid)
                conversation.context = {
                    **conversation.context,
                    "phase": "brief_review",
                    "active_job_id": None,
                    "active_operation_id": None,
                    "confirmed_brief_version": 1,
                }
                job = GenerationJob(
                    space_id=space_id,
                    account_id=account_id,
                    collection_id=UUID(collection["id"]),
                    operation=operation,
                    status="failed",
                    stage="failed",
                    input_payload={"conversation_id": str(cid), "confirmed_test_brief_version": 1},
                    output_payload={},
                    error_code="RateLimitError",
                )
                db.add(job)
                db.flush()
                failed = ConversationMessage(
                    conversation_id=cid, role="assistant", content="生成失败，请重试",
                    status="failed", related_job_id=job.id,
                    target_case_ids=[], citations=[], message_metadata={},
                )
                db.add(failed)
                db.flush()
                if entry == "confirmation":
                    for offset, (role, content) in enumerate([
                        ("user", "重试"), ("assistant", "是否要重试刚才的任务？"),
                    ], 1):
                        db.add(ConversationMessage(
                            conversation_id=cid, role=role, content=content, status="completed",
                            created_at=datetime.now(UTC) + timedelta(seconds=offset),
                            target_case_ids=[], citations=[], message_metadata={},
                        ))
                db.commit()
                job_id = job.id
                original_payload = dict(job.input_payload)
            async def retry():
                if entry == "button":
                    return await client.post(f"/api/v1/generation-jobs/{job_id}/retry")
                return await client.post(f"/api/v1/conversations/{cid}/messages", json={
                    "content": "确认" if entry == "confirmation" else "重试刚才失败的生成任务",
                })

            response = await retry()
            assert response.status_code == 202, response.text
            assert len(enqueued) == 1
            with get_session_factory()() as db:
                conversation = db.get(Conversation, cid)
                assert conversation.context["phase"] == (
                    "brief_drafting" if operation == "draft_brief" else "generating"
                )
                assert enqueued[0][1] == (
                    "casepilot.agent.draft_brief" if operation == "draft_brief"
                    else "casepilot.agent.generate"
                )
                assert conversation.context["active_job_id"] == str(job_id)
                assert db.get(GenerationJob, job_id).input_payload == original_payload
                assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                    GenerationJob.input_payload["conversation_id"].astext == str(cid),
                )) == 1
                assert db.get(ConversationMessage, failed.id).status == "running"
                if entry != "button":
                    assert response.json()["action"]["job_id"] == str(job_id)
            response = await retry()
            assert response.status_code == 409
            assert len(enqueued) == 1
            with get_session_factory()() as db:
                job = db.get(GenerationJob, job_id)
                job.status = "failed"
                conversation = db.get(Conversation, cid)
                conversation.context = {
                    **conversation.context,
                    "active_job_id": None,
                    "confirmed_brief_version": 2,
                }
                if operation == "draft_brief":
                    db.add(WorkspaceTestBrief(conversation_id=cid, version=1, content={}))
                db.commit()
            response = await client.post(
                f"/api/v1/generation-jobs/{job_id}/retry"
            ) if entry == "button" else await client.post(
                f"/api/v1/conversations/{cid}/messages", json={"content": "重试"},
            )
            assert response.status_code == 409
            assert response.json()["detail"] == "retry_context_mismatch"
            assert len(enqueued) == 1
            # A completed newer generation must not revive this old failure.
            with get_session_factory()() as db:
                db.add(GenerationJob(
                    space_id=space_id, account_id=account_id,
                    collection_id=UUID(collection["id"]), operation="generate",
                    status="completed", stage="completed",
                    input_payload={"conversation_id": str(cid)}, output_payload={},
                ))
                db.commit()
            response = await client.post(
                f"/api/v1/conversations/{cid}/messages", json={"content": "重试"},
            )
            assert response.status_code == 409
            assert response.json()["detail"] == "message_not_retryable"
            assert len(enqueued) == 1
    finally:
        if space_id and account_id:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == space_id))
                db.execute(delete(Account).where(Account.id == account_id))
                db.commit()


@pytest.mark.parametrize(
    "content", ["重试", "请重试一下", "确认重试", "再试一次", "retry", "try again"],
)
def test_explicit_retry_commands(content):
    assert conversations._is_generation_retry(content)


@pytest.mark.parametrize("content", [
    "不要重试", "重试失败怎么办", "生成失败重试的测试用例", "重试并删除旧用例", "确认", "好的",
])
def test_retry_does_not_capture_requirements_or_unbound_confirmations(content):
    assert not conversations._is_generation_retry(content)


@pytest.mark.parametrize("history", [[], [
    ("assistant", "确认测试说明后开始生成？"), ("user", "为登录生成用例"),
], [
    ("assistant", "是否要重试？"), ("user", "如何测试重试功能？"),
]])
def test_bare_confirmation_does_not_retry_unrelated_failure(history):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from casepilot_api.schemas import ConversationMessageCreate

    db = Mock()
    db.scalars.return_value = [
        SimpleNamespace(role=role, content=content) for role, content in history
    ]
    assert conversations._retry_generation_from_text(
        db, Mock(), SimpleNamespace(id=uuid4()), ConversationMessageCreate(content="确认"),
    ) is None
    db.scalar.assert_not_called()
