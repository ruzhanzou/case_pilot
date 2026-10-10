"""Draft updates preserve scope and require fresh confirmation after every change."""
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, ConversationOperation, GenerationJob, Space
from casepilot_api.rewrite_dialogue import RewriteReply


@pytest.fixture
async def draft(monkeypatch):
    dispatched = []
    monkeypatch.setattr(conversations.settings, "agent_provider", "mock")
    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **k: dispatched.append(a))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registration = await client.post("/api/v1/auth/register", json={
            "email": f"draft-{uuid4().hex}@casepilot.test", "display_name": "Draft test",
            "password": "CasePilot123!",
        })
        account_id = UUID(registration.json()["id"])
        space = registration.json()["spaces"][0]["id"]
        collection = (await client.get(f"/api/v1/spaces/{space}/collections")).json()[0]["id"]
        cases = []
        for title in ["登录成功", "取消登录"]:
            response = await client.post(f"/api/v1/collections/{collection}/test-cases", json={
                "title": title, "module": "登录", "steps": [{"action": "操作", "expected": "符合要求"}],
            })
            cases.append(response.json())
        workspace = (await client.put(f"/api/v1/collections/{collection}/workspace")).json()["id"]
        turn = await client.post(f"/api/v1/conversations/{workspace}/messages", json={
            "content": "改写登录模块用例，步骤更清晰，预期结果保持不变",
            "intent_override": "CASE_MODIFY", "target_case_ids": [c["id"] for c in cases],
        })
        assert turn.json()["assistant_message"]["metadata"]["modification_confirmation"]
        oid = turn.json()["operation_plan"]["operations"][0]["id"]
        try:
            yield client, workspace, oid, cases, dispatched
        finally:
            with get_session_factory()() as db:
                db.execute(delete(Space).where(Space.id == UUID(space)))
                db.execute(delete(Account).where(Account.id == account_id))
                db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("text,requirements", [
    ("简洁一点", "步骤简洁清晰，预期结果保持不变"),
    ("确认，但不要改标题", "步骤更清晰，标题和预期结果保持不变"),
    ("先别改标题，步骤拆开写", "步骤拆开写，标题和预期结果保持不变"),
    ("刚才说错了，改为P2", "优先级改为P2，步骤更清晰，预期结果保持不变"),
])
async def test_requirement_variants_keep_scope_and_do_not_execute(draft, monkeypatch, text, requirements):
    client, workspace, oid, cases, dispatched = draft
    interpreter = Mock(return_value=RewriteReply(action="update", requirements=requirements))
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", interpreter)
    selector = Mock(side_effect=AssertionError("unchanged scope must not be reselected"))
    monkeypatch.setattr(conversations, "_resolve_action_scope", selector)
    resume = f"/api/v1/conversation-operations/{oid}/resume"
    result = await client.post(resume, json={"content": text})
    assert result.status_code == 202, result.text
    assert not result.json()["action"].get("job_id")
    assert not dispatched
    assert set(result.json()["assistant_message"]["target_case_ids"]) == {c["id"] for c in cases}
    selector.assert_not_called()
    # Reload does not reconstruct scope by interpreting the accumulated messages.
    restored = (await client.get(f"/api/v1/conversations/{workspace}")).json()
    operation = next(o for o in restored["operation_plan"]["operations"] if o["id"] == oid)
    assert operation["payload"]["rewrite_draft"]["requirements"] == requirements
    assert "补充说明" not in operation["payload"]["instruction"]
    interpreter.return_value = RewriteReply(action="confirm")
    confirmed = await client.post(resume, json={"content": "没问题，就这样继续吧"})
    assert confirmed.json()["action"]["job_id"]
    assert len(dispatched) == 1
    with get_session_factory()() as db:
        job = db.get(GenerationJob, UUID(confirmed.json()["action"]["job_id"]))
        assert job.input_payload["prompt"] == requirements
        assert len(job.input_payload["case_context"]) == 2
    assert (await client.post(resume, json={"content": "确认"})).status_code == 409


@pytest.mark.asyncio
async def test_scope_update_replaces_previous_membership(draft, monkeypatch):
    client, _, oid, cases, dispatched = draft
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", lambda *a, **k: RewriteReply(
        action="update", scope_action="replace", scope_instruction=f"仅用例 {cases[1]['case_key']}",
    ))
    result = await client.post(f"/api/v1/conversation-operations/{oid}/resume", json={"content": "只改第二条"})
    assert result.json()["assistant_message"]["metadata"].get("modification_confirmation"), result.text
    assert result.json()["assistant_message"]["target_case_ids"] == [cases[1]["id"]]
    assert not dispatched
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        assert operation.payload["rewrite_draft"]["scope_resolved"]
        assert "步骤更清晰" in operation.payload["rewrite_draft"]["requirements"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    RewriteReply(action="clarify", clarification="要调整哪部分范围？"),
    RewriteReply(action="update", requirements="改为P0", confidence=0.4),
])
async def test_ambiguous_input_invalidates_confirmation(draft, monkeypatch, reply):
    client, _, oid, _, dispatched = draft
    interpreter = Mock(return_value=reply)
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", interpreter)
    resume = f"/api/v1/conversation-operations/{oid}/resume"
    result = await client.post(resume, json={"content": "不对，还有其他的"})
    assert result.status_code == 202
    assert not result.json()["assistant_message"]["metadata"].get("modification_confirmation")
    assert not dispatched
    assert (await client.post(resume, json={"confirm_modification": True})).status_code == 422
    interpreter.return_value = RewriteReply(action="confirm")
    followup = await client.post(resume, json={"content": "确认"})
    assert not followup.json()["action"].get("job_id")
    assert not dispatched


@pytest.mark.asyncio
async def test_negation_of_field_does_not_cancel_but_explicit_stop_does(draft, monkeypatch):
    client, _, oid, _, dispatched = draft
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", lambda *a, **k: RewriteReply(action="cancel"))
    result = await client.post(f"/api/v1/conversation-operations/{oid}/resume", json={"content": "这次不改了，结束任务"})
    assert result.json()["action"]["type"] == "cancelled"
    with get_session_factory()() as db:
        assert db.get(ConversationOperation, UUID(oid)).status == "cancelled"
    assert not dispatched


@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_acknowledgement_cannot_smuggle_an_update(action):
    with pytest.raises(ValueError):
        RewriteReply(action=action, requirements="确认，但改为P0")


@pytest.mark.asyncio
async def test_scope_question_is_resolved_from_catalog_before_asking_user(draft, monkeypatch):
    client, workspace, oid, cases, dispatched = draft
    from casepilot_api.models import Conversation, ConversationMessage
    from casepilot_api.schemas import ConversationMessageCreate
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    selector = Mock(side_effect=lambda db, c, payload, *a: (payload, None))
    monkeypatch.setattr(conversations, "_resolve_action_scope", selector)
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        operation.payload = {**operation.payload, "modification_confirmation": None, "plan": {
            "clarification_questions": ["请确认登录模块下需要改写的具体用例编号范围"],
            "reason_codes": [],
        }}
        conversation = db.get(Conversation, UUID(workspace))
        user = db.get(ConversationMessage, operation.message_id)
        account = db.get(Account, conversation.account_id)
        assistant, action, task = conversations._start_action(
            db, account, conversation, user,
            ConversationMessageCreate(content="改写登录模块全部用例，步骤更清晰",
                                      target_case_ids=[case["id"] for case in cases]),
            "CASE_MODIFY", 1, operation.id,
        )
        assert assistant.message_metadata["modification_confirmation"]
        assert not task
        selector.assert_called_once()
    assert not dispatched
