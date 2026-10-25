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
@pytest.mark.parametrize("entry", ["resume", "message", "idempotent_message"])
async def test_explicit_stop_cancels_existing_draft_without_dispatch(draft, monkeypatch, entry):
    from casepilot_api.agent_router import IntentOperationDraft, IntentPlanDraft
    client, workspace, oid, cases, dispatched = draft
    content = "这次修改全部取消，不用继续了。"
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "_retry_generation_from_text", lambda *a: None)
    monkeypatch.setattr(conversations, "plan_intents", lambda *a, **k: IntentPlanDraft(operations=[
        IntentOperationDraft(intent="CASE_MODIFY", instruction=content, confidence=1,
                             speech_act="request", action_evidence=content, resume_operation_id=oid)]))
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", lambda *a, **k: RewriteReply(action="cancel"))
    payload = {"content": content}
    if entry == "idempotent_message":
        payload["client_request_id"] = str(uuid4())
    endpoint = (f"/api/v1/conversation-operations/{oid}/resume" if entry == "resume"
                else f"/api/v1/conversations/{workspace}/messages")
    result = await client.post(endpoint, json=payload)
    assert result.status_code == 202, result.text
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
            "clarification_kind": "scope",
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


def test_mixed_task_intent_cannot_be_accepted_as_rewrite_update():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RewriteReply(action='update', scope_action='replace', scope_instruction='排除某条',
                     additional_intents=['CASE_DELETE'])


def test_live_reply_context_omits_full_case_body_and_revision_metadata(monkeypatch):
    import json
    from types import SimpleNamespace
    from agents import Runner
    from casepilot_api.rewrite_dialogue import interpret_rewrite_reply
    runner = Mock(return_value=SimpleNamespace(final_output=RewriteReply(action='update', requirements='步骤更清晰')))
    monkeypatch.setattr(Runner, 'run_sync', runner)
    interpret_rewrite_reply('步骤更清晰', {
        'requirements': '标题保留', 'scope_cases': [{'ref': 'case-a', 'snapshot': {
            'case_key': 'TC-A', 'title': '登录', 'module': '登录', 'priority': 'P1',
            'steps': [{'action': '详细操作' * 10000, 'expected': '成功'}],
            'source_refs': [{'excerpt': '来源正文' * 10000}], 'current_revision_id': 'revision-a',
        }}],
    }, provider='openai_compatible', model_name='test-model', base_url='https://example.invalid/v1',
       api_key='test-key', timeout_seconds=10, tracing_enabled=False)
    prompt = runner.call_args.args[1]
    assert len(prompt) < 1000
    context = json.loads(prompt)['draft']
    assert context['requirements'] == '标题保留'
    assert context['scope_cases'][0]['case_key'] == 'TC-A'
    assert 'current_revision_id' not in prompt
    assert '详细操作' not in prompt


@pytest.mark.asyncio
async def test_missing_direction_is_resolved_by_followup_without_asking_again(draft, monkeypatch):
    client, workspace, oid, cases, dispatched = draft
    await client.post(f'/api/v1/conversation-operations/{oid}/cancel')
    started = await client.post(f'/api/v1/conversations/{workspace}/messages', json={
        'content': '改写登录模块用例', 'intent_override': 'CASE_MODIFY',
        'target_case_ids': [case['id'] for case in cases],
    })
    assert started.status_code == 202, started.text
    assert not started.json()['assistant_message']['metadata'].get('modification_confirmation')
    new_oid = started.json()['operation_plan']['operations'][0]['id']
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', lambda *a, **k: RewriteReply(
        action='update', requirements='步骤更清晰', requirements_ready=True,
    ))
    resumed = await client.post(f'/api/v1/conversation-operations/{new_oid}/resume', json={'content': '步骤更清晰'})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()['assistant_message']['metadata'].get('modification_confirmation'), resumed.text
    assert set(resumed.json()['assistant_message']['target_case_ids']) == {case['id'] for case in cases}
    assert not dispatched


@pytest.mark.asyncio
async def test_explicit_modify_override_wins_over_reference_strategy(draft):
    client, workspace, oid, cases, _ = draft
    assert (await client.post(f"/api/v1/conversation-operations/{oid}/cancel")).status_code == 200
    started = await client.post(
        f"/api/v1/conversations/{workspace}/messages",
        json={
            "content": "不要改标题，参考已有资产修改步骤",
            "intent_override": "CASE_MODIFY",
            "target_case_ids": [cases[0]["id"]],
        },
    )
    assert started.status_code == 202, started.text
    body = started.json()
    assert body["intent"] == "CASE_MODIFY"
    assert body["user_message"]["metadata"]["request"]["intent_override"] == "CASE_MODIFY"
    assert body["user_message"]["metadata"]["request"]["generation_strategy"] == "select_and_generate"


@pytest.mark.asyncio
async def test_direction_question_persists_inferred_scope_before_short_reply(draft, monkeypatch):
    client, workspace, oid, cases, dispatched = draft
    from casepilot_api.models import Conversation, ConversationMessage
    from casepilot_api.schemas import ConversationMessageCreate
    selector = Mock(side_effect=lambda db, c, payload, *a: (
        payload.model_copy(update={'target_case_ids': [UUID(cases[0]['id'])]}), None))
    monkeypatch.setattr(conversations, '_resolve_action_scope', selector)
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        operation.target = {'resolved': False, 'case_ids': [], 'candidate_refs': []}
        operation.payload = {**operation.payload, 'instruction': '步骤太简单，丰富以下',
            'modification_confirmation': None, 'plan': {
                'clarification_questions': ['希望重点补充哪些内容：操作细节还是预期结果？'],
            }}
        conversation = db.get(Conversation, UUID(workspace))
        user = db.get(ConversationMessage, operation.message_id)
        assistant, _, task = conversations._start_action(db, db.get(Account, conversation.account_id),
            conversation, user, ConversationMessageCreate(content='步骤太简单，丰富以下'),
            'CASE_MODIFY', 1, operation.id)
        assert not task
        assert assistant.target_case_ids == [cases[0]['id']]
        assert operation.target['resolved']
        assert not operation.payload['rewrite_draft']['requirements_ready']
        db.commit()
    selector.assert_called_once()
    restored = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    assert restored['context']['selected_targets'][0]['target']['case_ids'] == [cases[0]['id']]
    selector.side_effect = AssertionError('A direction-only reply must retain resolved scope')
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', lambda *a, **k: RewriteReply(
        action='update', requirements='丰富操作细节，保留原预期结果'))
    result = await client.post(f'/api/v1/conversation-operations/{oid}/resume', json={'content': '操作细节'})
    assert result.status_code == 202, result.text
    assert result.json()['assistant_message']['target_case_ids'] == [cases[0]['id']]
    assert result.json()['assistant_message']['metadata']['modification_confirmation']
    assert not dispatched
    confirmed = await client.post(f'/api/v1/conversation-operations/{oid}/resume', json={'content': '确认'})
    assert confirmed.json()['action']['job_id']
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_selection_is_saved_while_waiting_for_direction(draft, monkeypatch):
    client, _, oid, cases, dispatched = draft
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        operation.target = {'resolved': False, 'case_ids': [], 'candidate_refs': []}
        operation.payload = {**operation.payload, 'modification_confirmation': None,
            'rewrite_draft': {'version': 1, 'scope_instruction': '重写用例',
                'requirements': '重写用例', 'requirements_ready': False, 'scope_resolved': False}}
        db.commit()
    resume = f'/api/v1/conversation-operations/{oid}/resume'
    selected = await client.post(resume, json={'targets': [{'kind': 'case', 'case_ids': [cases[1]['id']]}]})
    assert selected.status_code == 202, selected.text
    assert selected.json()['assistant_message']['target_case_ids'] == [cases[1]['id']]
    assert not selected.json()['assistant_message']['metadata'].get('modification_confirmation')
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', lambda *a, **k: RewriteReply(
        action='update', requirements='丰富操作细节'))
    result = await client.post(resume, json={'content': '操作细节'})
    assert result.json()['assistant_message']['target_case_ids'] == [cases[1]['id']]
    assert result.json()['assistant_message']['metadata']['modification_confirmation']
    assert not dispatched


@pytest.mark.asyncio
async def test_unresolved_scope_never_dispatches_and_retains_answered_direction(draft, monkeypatch):
    client, _, oid, _, dispatched = draft
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        operation.target = {'resolved': False, 'case_ids': [], 'candidate_refs': []}
        operation.payload = {**operation.payload, 'modification_confirmation': None,
            'rewrite_draft': {'version': 1, 'scope_instruction': '步骤太简单，丰富以下',
                'requirements': '丰富步骤', 'requirements_ready': False, 'scope_resolved': False}}
        db.commit()
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', lambda *a, **k: RewriteReply(
        action='update', requirements='丰富操作细节'))
    monkeypatch.setattr(conversations, '_resolve_action_scope', lambda db, c, p, *a: (p, '请选择要修改的用例。'))
    resume = f'/api/v1/conversation-operations/{oid}/resume'
    result = await client.post(resume, json={'content': '操作细节'})
    assert result.json()['assistant_message']['content'] == '请选择要修改的用例。'
    operation = result.json()['operation_plan']['operations'][0]
    assert operation['payload']['rewrite_draft']['requirements'] == '丰富操作细节'
    assert operation['payload']['rewrite_draft']['requirements_ready']
    assert not operation['target']['resolved']
    assert (await client.post(resume, json={'confirm_modification': True})).status_code == 422
    assert not dispatched


@pytest.mark.asyncio
async def test_legacy_pending_task_recovers_original_explicit_targets(draft, monkeypatch):
    client, _, oid, cases, dispatched = draft
    from casepilot_api.models import ConversationMessage
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        operation.target = {'resolved': False, 'case_ids': [], 'candidate_refs': []}
        operation.payload = {**operation.payload, 'instruction': '步骤太简单，丰富以下',
            'modification_confirmation': None, 'rewrite_draft': None, 'plan': {}}
        message = db.get(ConversationMessage, operation.message_id)
        message.message_metadata = {**message.message_metadata, 'request': {
            **message.message_metadata['request'], 'content': '步骤太简单，丰富以下',
            'target_case_ids': [cases[1]['id']], 'targets': [],
        }}
        db.commit()
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', lambda *a, **k: RewriteReply(
        action='update', requirements='丰富操作细节'))
    result = await client.post(f'/api/v1/conversation-operations/{oid}/resume', json={'content': '操作细节'})
    assert result.status_code == 202, result.text
    assert result.json()['assistant_message']['target_case_ids'] == [cases[1]['id']]
    assert result.json()['assistant_message']['metadata']['modification_confirmation']
    assert not dispatched


@pytest.mark.asyncio
async def test_failed_scope_persists_clarification_and_blocks_confirmation(draft, monkeypatch):
    client, workspace, oid, cases, dispatched = draft
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', lambda *a, **k: RewriteReply(
        action='update', scope_action='replace', scope_instruction='只改三条'))
    monkeypatch.setattr(conversations, '_resolve_action_scope',
                        lambda db, conv, payload, *a, **k: (payload, '数量不一致'))
    endpoint = f'/api/v1/conversation-operations/{oid}/resume'
    response = await client.post(endpoint, json={'content': '只改三条'})
    assert response.status_code == 202
    restored = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    operation = next(o for o in restored['operation_plan']['operations'] if o['id'] == oid)
    state = operation['payload']['rewrite_draft']
    assert state['phase'] == 'clarifying'
    assert state['clarification'] == '数量不一致'
    assert not operation['payload']['modification_confirmation']
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply',
                        lambda *a, **k: RewriteReply(action='confirm'))
    response = await client.post(endpoint, json={'content': '确认'})
    assert response.status_code == 202
    assert not response.json()['action'].get('job_id')
    assert not dispatched


@pytest.mark.asyncio
async def test_stale_preview_cannot_restore_missing_requirements(draft):
    client, _, oid, _, dispatched = draft
    with get_session_factory()() as db:
        operation = db.get(ConversationOperation, UUID(oid))
        operation.payload = {**operation.payload, 'rewrite_draft': {
            **operation.payload['rewrite_draft'], 'requirements_ready': False}}
        db.commit()
    response = await client.post(f'/api/v1/conversation-operations/{oid}/resume',
                                 json={'confirm_modification': True})
    assert response.status_code == 202
    assert not response.json()['action'].get('job_id')
    assert not dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize("idempotent", [False, True])
@pytest.mark.parametrize("failure", ["unavailable_plan", "connection"])
async def test_routing_outage_preserves_draft_and_retries_without_new_task(draft, monkeypatch, idempotent, failure):
    from casepilot_api.agent_router import IntentOperationDraft, IntentPlanDraft

    client, workspace, oid, cases, dispatched = draft
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "_retry_generation_from_text", lambda *a: None)
    content = "优先级改成P2，其他字段不变"
    planner = Mock(return_value=IntentPlanDraft(operations=[IntentOperationDraft(
        intent="UNRESOLVED", instruction=content, confidence=0,
        reason_codes=["MODEL_FAILED", "SEMANTIC_ROUTING_UNAVAILABLE"],
        requires_confirmation=True,
    )]))
    monkeypatch.setattr(conversations, "plan_intents", planner)
    if failure == "connection":
        import httpx
        from openai import APIConnectionError

        monkeypatch.setattr(conversations, "_retry_generation_from_text", Mock(side_effect=
            APIConnectionError(request=httpx.Request("POST", "https://model.invalid"))))
    before = (await client.get(f"/api/v1/conversations/{workspace}")).json()
    payload = {"content": content}
    if idempotent:
        payload["client_request_id"] = str(uuid4())
    response = await client.post(f"/api/v1/conversations/{workspace}/messages", json=payload)
    assert response.status_code == 503
    assert "未执行" in response.json()["detail"]
    after = (await client.get(f"/api/v1/conversations/{workspace}")).json()
    assert after["operation_plan"] == before["operation_plan"]
    assert after["messages"] == before["messages"]
    assert not dispatched

    monkeypatch.setattr(conversations, "_retry_generation_from_text", lambda *a: None)
    planner.return_value = IntentPlanDraft(operations=[IntentOperationDraft(
        intent="CASE_MODIFY", instruction=content, confidence=1,
        resume_operation_id=oid, uses_selected_targets=False,
    )])
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", lambda *a, **k: RewriteReply(
        action="update", requirements=content,
    ))
    response = await client.post(f"/api/v1/conversations/{workspace}/messages", json=payload)
    assert response.status_code == 202, response.text
    assert response.json()["assistant_message"]["metadata"]["operation_id"] == oid
    final = (await client.get(f"/api/v1/conversations/{workspace}")).json()
    assert len(final["operation_plan"]["operations"]) == len(before["operation_plan"]["operations"])
    assert sum(m["role"] == "user" and m["content"] == content for m in final["messages"]) == 1
    assert not dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", [{"content": "确认"}, {"confirm_modification": True}])
async def test_confirmed_rewrite_does_not_repeat_collection_or_generation_models(draft, monkeypatch, confirmation):
    client, workspace, oid, cases, dispatched = draft
    infer = Mock(side_effect=AssertionError("rewrite must not infer a generation test object"))
    monkeypatch.setattr(conversations, "_test_object_from_memory", infer)
    collection = Mock(side_effect=AssertionError("confirmed scope must not be reinterpreted"))
    monkeypatch.setattr(conversations, "_collection_candidates", collection)
    monkeypatch.setattr(conversations, "interpret_rewrite_reply", lambda *a, **k: RewriteReply(action="confirm"))
    response = await client.post(f"/api/v1/conversation-operations/{oid}/resume", json=confirmation)
    assert response.status_code == 202, response.text
    assert response.json()["action"]["job_id"]
    assert len(dispatched) == 1
    infer.assert_not_called()
    collection.assert_not_called()
    with get_session_factory()() as db:
        job = db.get(GenerationJob, UUID(response.json()["action"]["job_id"]))
        assert {item["ref"] for item in job.input_payload["case_context"]} == {c["id"] for c in cases}
        assert "预期结果保持不变" in job.input_payload["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['message', 'idempotent_message', 'resume'])
@pytest.mark.parametrize('stage', ['reply', 'scope'])
@pytest.mark.parametrize('failure', ['connection', 'invalid_output'])
async def test_interpretation_outage_keeps_preview_and_retry_updates_same_draft(
        draft, monkeypatch, entry, stage, failure):
    import httpx
    from agents import ModelBehaviorError
    from openai import APIConnectionError
    from casepilot_api.agent_router import CaseScopeDecision, IntentOperationDraft, IntentPlanDraft

    client, workspace, oid, cases, dispatched = draft
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'openai_compatible')
    monkeypatch.setattr(conversations, '_retry_generation_from_text', lambda *a: None)
    content = '只改第一条，优先级改为P2，其他字段不变'
    monkeypatch.setattr(conversations, 'plan_intents', lambda *a, **k: IntentPlanDraft(operations=[
        IntentOperationDraft(intent='CASE_MODIFY', instruction=content, confidence=1,
                             resume_operation_id=oid)]))
    reply = Mock(return_value=RewriteReply(action='update', scope_action='replace',
        scope_instruction='登录模块第一条', requirements='优先级P2，其他字段不变'))
    selector = Mock(return_value=CaseScopeDecision(ids=[cases[0]['id']], ambiguous=False,
        clarification='', reference='none', referenced_case_keys=[], requested_count=1))
    monkeypatch.setattr(conversations, 'interpret_rewrite_reply', reply)
    monkeypatch.setattr(conversations, 'select_case_scope', selector)
    broken = reply if stage == 'reply' else selector
    broken.side_effect = (APIConnectionError(request=httpx.Request('POST', 'https://model.invalid'))
                          if failure == 'connection' else ModelBehaviorError('invalid model output'))
    endpoint = (f'/api/v1/conversation-operations/{oid}/resume' if entry == 'resume'
                else f'/api/v1/conversations/{workspace}/messages')
    payload = {'content': content}
    if entry == 'idempotent_message':
        payload['client_request_id'] = str(uuid4())
    before = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    response = await client.post(endpoint, json=payload)
    assert response.status_code == 503, response.text
    after = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    assert after['operation_plan'] == before['operation_plan']
    assert after['messages'] == before['messages']
    assert not dispatched
    broken.side_effect = None
    retried = await client.post(endpoint, json=payload)
    assert retried.status_code == 202, retried.text
    assert retried.json()['assistant_message']['metadata']['operation_id'] == oid
    assert retried.json()['assistant_message']['metadata']['modification_confirmation']
    assert retried.json()['assistant_message']['target_case_ids'] == [cases[0]['id']]
    final = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    assert sum(m['role'] == 'user' and m['content'] == content for m in final['messages']) == 1
    assert not dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize('idempotent', [False, True])
async def test_new_query_scope_outage_does_not_persist_a_spurious_task(draft, monkeypatch, idempotent):
    from casepilot_api.agent_router import CaseScopeDecision, IntentOperationDraft, IntentPlanDraft

    client, workspace, oid, cases, dispatched = draft
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'openai_compatible')
    monkeypatch.setattr(conversations, '_retry_generation_from_text', lambda *a: None)
    content = '先查询登录模块，原修改不要执行'
    monkeypatch.setattr(conversations, 'plan_intents', lambda *a, **k: IntentPlanDraft(operations=[
        IntentOperationDraft(intent='CASE_QUERY', instruction=content, confidence=1)]))
    selector = Mock(side_effect=TimeoutError('scope unavailable'))
    monkeypatch.setattr(conversations, 'select_case_scope', selector)
    endpoint = f'/api/v1/conversations/{workspace}/messages'
    payload = {'content': content}
    if idempotent:
        payload['client_request_id'] = str(uuid4())
    before = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    response = await client.post(endpoint, json=payload)
    assert response.status_code == 503, response.text
    after = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    assert after['operation_plan'] == before['operation_plan']
    assert after['messages'] == before['messages']
    selector.side_effect = None
    selector.return_value = CaseScopeDecision(ids=[c['id'] for c in cases], ambiguous=False,
        clarification='', reference='none', referenced_case_keys=[], requested_count=None)
    retried = await client.post(endpoint, json=payload)
    assert retried.status_code == 202, retried.text
    assert retried.json()['action']['type'] == 'case_query'
    assert set(retried.json()['assistant_message']['target_case_ids']) == {c['id'] for c in cases}
    final = (await client.get(f'/api/v1/conversations/{workspace}')).json()
    assert sum(m['role'] == 'user' and m['content'] == content for m in final['messages']) == 1
    assert not dispatched
