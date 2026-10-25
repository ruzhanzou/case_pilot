from unittest.mock import Mock

import pytest

from casepilot_api import agent_router as router


@pytest.mark.parametrize("intent", list(router.DEFAULT_ACTIONS))
def test_all_intents_use_model_without_rule_override(monkeypatch, intent):
    content = "请按当前说明处理这些内容"
    operation = router.IntentOperationDraft(
        intent=intent,
        instruction=content,
        action_evidence=content,
        target_kind="previous_result",
        confidence=0.99,
    )
    semantic = Mock(return_value=router.IntentPlanDraft(operations=[operation]))
    monkeypatch.setattr(router, "sdk_plan", semantic)
    classify = Mock(side_effect=AssertionError("Production must not call rule classifier"))
    result = router.plan_intents(
        content,
        classify,
        has_targets=True,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="fixture",
        base_url="https://example.test",
        api_key="fixture",
        timeout_seconds=1,
        tracing_enabled=False,
    )
    assert result.operations[0].intent == intent
    assert result.operations[0].routing_source == "semantic"
    assert result.operations[0].action == router.DEFAULT_ACTIONS[intent]
    if intent in {"CASE_MODIFY", "CASE_DELETE", "UNRESOLVED"}:
        assert result.operations[0].requires_confirmation
    semantic.assert_called_once()
    classify.assert_not_called()


def test_unavailable_model_cannot_trigger_rule_action(monkeypatch):
    monkeypatch.setattr(router, "sdk_plan", Mock(side_effect=TimeoutError()))
    classify = Mock(side_effect=AssertionError("No semantic fallback"))
    result = router.plan_intents(
        "删除刚才查询到的三条用例",
        classify,
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="fixture",
        base_url="https://example.test",
        api_key="fixture",
        timeout_seconds=1,
        tracing_enabled=False,
    )
    assert result.operations[0].intent == "UNRESOLVED"
    classify.assert_not_called()


@pytest.mark.parametrize("corrected", [True, False])
def test_invalid_action_evidence_gets_one_model_repair(monkeypatch, corrected):
    content = "分析当前集合的测试覆盖缺口"

    def response(evidence):
        return router.IntentPlanDraft(
            operations=[
                router.IntentOperationDraft(
                    intent="COVERAGE_ANALYZE",
                    instruction=content,
                    action_evidence=evidence,
                    confidence=1,
                )
            ]
        )

    model = Mock(
        side_effect=[
            response("分析测试覆盖缺口"),
            response(content if corrected else "分析覆盖情况"),
        ]
    )
    monkeypatch.setattr(router, "sdk_plan", model)
    plan = router.plan_intents(
        content,
        Mock(side_effect=AssertionError("No rules")),
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="fixture",
        base_url="https://example.test",
        api_key="fixture",
        timeout_seconds=1,
        tracing_enabled=False,
    )
    assert model.call_count == 2
    assert model.call_args.kwargs["validation_feedback"]
    assert plan.operations[0].intent == ("COVERAGE_ANALYZE" if corrected else "UNRESOLVED")


@pytest.mark.parametrize("act", ["negation", "quotation", "question"])
def test_model_speech_act_cannot_dispatch_a_write(act):
    content = "不要修改用例标题"
    result = router._validate_model_plan(
        content,
        router.IntentPlanDraft(
            operations=[
                router.IntentOperationDraft(
                    intent="CASE_MODIFY",
                    instruction=content,
                    action_evidence=content,
                    speech_act=act,
                    confidence=1,
                ),
            ]
        ),
        has_targets=True,
        phase="idle",
    )
    assert result.operations[0].intent == "KNOWLEDGE_QA"
    assert result.operations[0].action == "ANSWER_QUESTION"
    assert not result.operations[0].requires_confirmation


def test_unclear_speech_act_never_authorizes_write():
    from casepilot_api.agent_router import (
        IntentOperationDraft,
        IntentPlanDraft,
        _validate_model_plan,
    )

    plan = IntentPlanDraft(
        operations=[
            IntentOperationDraft(
                intent="CASE_DELETE",
                instruction="处理这些",
                confidence=1,
                speech_act="unclear",
                action_evidence="处理",
                resume_operation_id="old-task",
            )
        ]
    )
    result = _validate_model_plan("处理这些", plan, has_targets=True, phase="maintenance")
    assert result.operations[0].intent == "UNRESOLVED"
    assert result.operations[0].resume_operation_id is None


def test_collection_reference_uses_model_instead_of_name_matching(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from uuid import uuid4
    from casepilot_api import conversations

    collection = SimpleNamespace(id=uuid4(), name="订单")
    db = Mock()
    db.scalars.return_value = [collection]
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    interpreter = Mock(return_value=SimpleNamespace(target_collection_id=None))
    monkeypatch.setattr(conversations, "interpret_generation_choice", interpreter)
    matcher = Mock(side_effect=AssertionError("No local semantic collection matching"))
    monkeypatch.setattr(conversations, "_explicit_collection_mention", matcher)
    candidates, chosen = conversations._collection_candidates(
        db, SimpleNamespace(space_id=uuid4()), "不要切换到订单集合", explicit_only=True
    )
    assert chosen is None
    assert interpreter.call_args.kwargs["collection_catalog"] == candidates
    assert interpreter.call_args.kwargs["explicit_collection_only"] is True
    matcher.assert_not_called()


def test_asset_strategy_does_not_cancel_an_active_real_task(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from uuid import uuid4
    from fastapi import HTTPException
    from casepilot_api import conversations, generation
    from casepilot_api.schemas import ConversationMessageCreate

    cid, jid = uuid4(), uuid4()
    conversation = SimpleNamespace(id=cid, context={"active_job_id": str(jid)})
    db = Mock()
    db.get.return_value = SimpleNamespace(id=jid, status="running")
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(conversations, "_ensure_conversation", lambda *a: conversation)
    monkeypatch.setattr(
        conversations, "interpret_generation_choice", lambda *a: SimpleNamespace(strategy="select")
    )
    monkeypatch.setattr(
        conversations,
        "_require_idle_conversation",
        Mock(side_effect=HTTPException(409, "conversation_task_running")),
    )
    cancel = Mock()
    monkeypatch.setattr(generation, "cancel_generation", cancel)
    with pytest.raises(HTTPException) as error:
        conversations._send_message(
            cid, ConversationMessageCreate(content="查询全部用例"), SimpleNamespace(id=uuid4()), db
        )
    assert error.value.status_code == 409
    cancel.assert_not_called()


@pytest.mark.parametrize("recovered", [True, False])
def test_invalid_model_json_gets_only_one_model_repair(monkeypatch, recovered):
    from agents.exceptions import ModelBehaviorError
    content = "将删除全部用例翻译成英文"
    valid = router.IntentPlanDraft(operations=[router.IntentOperationDraft(
        intent="KNOWLEDGE_QA", instruction=content, confidence=1, speech_act="quotation")])
    model = Mock(side_effect=[ModelBehaviorError("invalid JSON"),
                              valid if recovered else ModelBehaviorError("invalid JSON again")])
    monkeypatch.setattr(router, "sdk_plan", model)
    plan = router.plan_intents(content, Mock(side_effect=AssertionError("No regex fallback")),
        has_targets=False, phase="idle", target_context=[], provider="openai_compatible",
        model_name="fixture", base_url="https://example.test", api_key="fixture",
        timeout_seconds=10, tracing_enabled=False)
    assert model.call_count == 2
    assert model.call_args.kwargs["validation_feedback"]
    assert plan.operations[0].intent == ("KNOWLEDGE_QA" if recovered else "UNRESOLVED")


@pytest.mark.parametrize('recovered', [True, False])
@pytest.mark.parametrize('status', ['completed', 'awaiting_confirmation', 'missing'])
def test_invalid_resume_is_repaired_by_model_not_executed(monkeypatch, recovered, status):
    content = '在已有规划中增加一个退出登录测试点，保留其他测试点'
    invalid = router.IntentPlanDraft(operations=[router.IntentOperationDraft(
        intent='CASE_GENERATE', instruction=content, confidence=1,
        action_evidence=content, resume_operation_id='old-task')])
    valid = invalid.model_copy(deep=True)
    valid.operations[0].resume_operation_id = None
    model = Mock(side_effect=[invalid, valid if recovered else invalid])
    monkeypatch.setattr(router, 'sdk_plan', model)
    plan = router.plan_intents(content, Mock(side_effect=AssertionError('No regex fallback')),
        has_targets=False, phase='brief_review', target_context=[], provider='openai_compatible',
        active_operations=[] if status == 'missing' else [
            {'id': 'old-task', 'intent': 'CASE_GENERATE', 'status': status}],
        model_name='fixture', base_url='https://example.test', api_key='fixture',
        timeout_seconds=10, tracing_enabled=False)
    assert model.call_count == 2
    assert 'resume_operation_id' in model.call_args.kwargs['validation_feedback']
    assert plan.operations[0].resume_operation_id is None
    assert plan.operations[0].intent == ('CASE_GENERATE' if recovered else 'UNRESOLVED')


@pytest.mark.parametrize('phase', ['candidate_review', 'maintenance', 'brief_review'])
def test_real_knowledge_question_never_enters_asset_scope_parser(monkeypatch, phase):
    from types import SimpleNamespace
    from uuid import uuid4
    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'openai_compatible')
    parser = Mock(side_effect=AssertionError('No regex scope for knowledge questions'))
    monkeypatch.setattr(conversations, 'resolve_scope', parser)
    selector = Mock(side_effect=AssertionError('No asset selection for knowledge questions'))
    monkeypatch.setattr(conversations, '_resolve_model_scope', selector)
    db = Mock()
    conv = SimpleNamespace(collection_id=uuid4(), context={'phase': phase})
    payload = ConversationMessageCreate(content='先不要修改或生成任何用例。解释一下等价类划分是什么。')
    result, error = conversations._resolve_action_scope(db, conv, payload, 'KNOWLEDGE_QA')
    assert result == payload and error is None
    db.scalars.assert_not_called()
    parser.assert_not_called()
    selector.assert_not_called()


@pytest.mark.parametrize('current', ['generate', 'select', 'select_and_generate'])
@pytest.mark.parametrize('explicit_change', [False, True])
def test_planning_revision_preserves_strategy_unless_model_detects_explicit_switch(monkeypatch, current, explicit_change):
    from types import SimpleNamespace
    from uuid import uuid4
    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate
    monkeypatch.setattr(conversations.settings, 'agent_provider', 'openai_compatible')
    choice = SimpleNamespace(strategy='select_and_generate', brief_action='revise',
                             strategy_change_requested=explicit_change, rewrite_existing_assets=False,
                             continue_cases=False)
    monkeypatch.setattr(conversations, 'interpret_generation_choice', lambda *a: choice)
    db = Mock()
    db.scalar.return_value = SimpleNamespace(content={'generation_strategy': current})
    conv = SimpleNamespace(id=uuid4(), collection_id=uuid4())
    captured = []
    sentinel = ('gate', {}, None)
    def gate(db, conv, payload, *args):
        captured.append(payload)
        return sentinel
    monkeypatch.setattr(conversations, '_collection_gate', gate)
    result = conversations._start_action(db, SimpleNamespace(), conv, None,
        ConversationMessageCreate(content='仅替换退出登录测试点，使用退出前同一会话访问页面，其他不变'),
        'CASE_GENERATE', 1.0)
    assert result == sentinel
    assert captured[0].generation_strategy == ('select_and_generate' if explicit_change else current)


@pytest.mark.parametrize('repaired', [True, False])
def test_clarification_evidence_repair_does_not_misdiagnose_valid_resume(monkeypatch, repaired):
    content = '我指的是错误密码登录失败的那条，优先级P0，别的不用改。'
    def draft(evidence):
        return router.IntentPlanDraft(operations=[router.IntentOperationDraft(
            intent='CASE_MODIFY', instruction=content, confidence=1,
            action_evidence=evidence, resume_operation_id='pending-modification',
        )])
    semantic = Mock(side_effect=[
        draft('优先级调成P0'),
        draft('优先级P0' if repaired else '优先级调成P0'),
    ])
    monkeypatch.setattr(router, 'sdk_plan', semantic)
    result = router.plan_intents(content, Mock(side_effect=AssertionError('No rules')),
        has_targets=False, phase='maintenance', target_context=[],
        active_operations=[{'id':'pending-modification','status':'awaiting_target','intent':'CASE_MODIFY'}],
        provider='openai_compatible', model_name='fixture', base_url='https://example.test',
        api_key='fixture', timeout_seconds=20, tracing_enabled=False)
    assert 'action_evidence' in semantic.call_args.kwargs['validation_feedback']
    assert '上次resume_operation_id' not in semantic.call_args.kwargs['validation_feedback']
    op = result.operations[0]
    assert op.intent == ('CASE_MODIFY' if repaired else 'UNRESOLVED')
    assert op.resume_operation_id == ('pending-modification' if repaired else None)
