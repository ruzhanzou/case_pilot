import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from casepilot_api import agent_router
from casepilot_api.agent_router import (
    IntentPlanDraft,
    deterministic_plan,
    plan_intents,
    sdk_plan,
)
from casepilot_api.conversations import classify_intent


def classify(clause: str) -> tuple[str, float]:
    if "生成" in clause:
        return "CASE_GENERATE", 0.96
    if "修改" in clause or "改写" in clause:
        return "CASE_MODIFY", 0.93
    if "删除" in clause:
        return "CASE_DELETE", 0.95
    return "KNOWLEDGE_QA", 0.9


def test_multi_intent_plan_preserves_order_without_dropping_the_fourth_action() -> None:
    plan = deterministic_plan(
        "先生成登录用例，然后修改刚生成的异常场景；删除旧用例；查询全部用例",
        classify,
        has_targets=False,
    )

    assert [item.intent for item in plan.operations] == [
        "CASE_GENERATE",
        "CASE_MODIFY",
        "CASE_DELETE",
        "KNOWLEDGE_QA",
    ]
    assert plan.operations[1].target_kind == "previous_result"
    assert plan.operations[2].requires_confirmation is True


def test_english_multi_intent_plan_preserves_generation_then_deletion() -> None:
    plan = deterministic_plan(
        "Generate test cases and then delete the old ones.",
        classify_intent,
        has_targets=False,
    )
    assert [item.intent for item in plan.operations] == [
        "CASE_GENERATE",
        "CASE_DELETE",
    ]
    assert plan.operations[1].requires_confirmation is True


def test_model_failure_does_not_dispatch_rule_based_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_router(*args, **kwargs):
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(agent_router, "sdk_plan", fail_router)
    plan = plan_intents(
        "Generate test cases and then delete the old ones.",
        classify_intent,
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="test",
        base_url="https://example.test/v1",
        api_key="test-only",
        timeout_seconds=5,
        tracing_enabled=False,
    )
    assert [item.intent for item in plan.operations] == ["UNRESOLVED"]
    assert plan.operations[0].requires_confirmation


def test_model_failure_keeps_explicit_query_with_negated_write_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_router(*args, **kwargs):
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(agent_router, "sdk_plan", fail_router)
    plan = plan_intents(
        "查询当前集合的P0正式用例，只查询不修改。",
        classify_intent,
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="test",
        base_url="https://example.test/v1",
        api_key="test-only",
        timeout_seconds=5,
        tracing_enabled=False,
    )

    assert [item.intent for item in plan.operations] == ["UNRESOLVED"]
    assert plan.operations[0].requires_confirmation is True
    assert "SEMANTIC_ROUTING_UNAVAILABLE" in plan.operations[0].reason_codes


def test_negated_generation_is_not_an_explicit_write_request() -> None:
    for content in ("不要生成测试用例", "Please don't generate test cases"):
        assert agent_router._has_explicit_write_request(content) is False


@pytest.mark.parametrize(
    ("content", "phase"),
    [
        ("如何修改测试说明？", "brief_review"),
        ("请问如何生成测试用例？", "idle"),
        ("Can you explain how to generate test cases?", "idle"),
    ],
)
def test_model_plan_cannot_turn_information_question_into_write(content: str, phase: str) -> None:
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_GENERATE",
                    "instruction": content,
                    "confidence": 0.99,
                }
            ],
        }
    )
    validated = agent_router._validate_model_plan(content, plan, has_targets=False, phase=phase)
    assert validated.operations[0].intent == "UNRESOLVED"


def test_model_plan_cannot_turn_negated_generation_into_write() -> None:
    content = "请不要生成测试用例"
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_GENERATE",
                    "instruction": content,
                    "confidence": 0.99,
                }
            ],
        }
    )
    validated = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert validated.operations[0].intent == "UNRESOLVED"


def test_negated_delete_is_never_dispatched_as_delete() -> None:
    plan = deterministic_plan(
        "不要删除当前用例",
        classify,
        has_targets=True,
    )

    assert plan.operations[0].intent == "KNOWLEDGE_QA"
    assert plan.operations[0].requires_confirmation is False


def test_small_talk_uses_the_same_model_answer_action_as_knowledge_qa() -> None:
    plan = deterministic_plan(
        "你是谁？你能做什么？",
        lambda clause: ("SMALL_TALK", 0.99),
        has_targets=False,
    )

    assert plan.operations[0].intent == "SMALL_TALK"
    assert plan.operations[0].action == "ANSWER_QUESTION"


def test_english_generation_request_routes_to_workspace_without_model() -> None:
    instruction = (
        "doubao Generate test cases for phone verification-code login, "
        "covering the happy path, rate limits, code expiry, and poor networks."
    )
    plan = plan_intents(
        instruction,
        classify_intent,
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="mock",
        model_name="mock",
        base_url="",
        api_key="",
        timeout_seconds=5,
        tracing_enabled=False,
    )
    assert plan.operations[0].intent == "CASE_GENERATE"
    assert plan.operations[0].action == "BRIEF_CREATE"
    assert plan.operations[0].requires_confirmation is False


def test_joined_wake_word_routes_generation_to_workspace() -> None:
    plan = plan_intents(
        "dou baoGenerate test cases for phone verification-code login, "
        "covering the happy path, rate limits, code expiry, and poor networks.",
        classify_intent,
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="mock",
        model_name="mock",
        base_url="",
        api_key="",
        timeout_seconds=5,
        tracing_enabled=False,
    )
    assert plan.operations[0].intent == "CASE_GENERATE"
    assert plan.operations[0].action == "BRIEF_CREATE"
    assert plan.operations[0].requires_confirmation is False


def test_model_authored_action_is_normalized_to_the_server_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_router,
        "sdk_plan",
        lambda *args, **kwargs: IntentPlanDraft.model_validate(
            {
                "operations": [
                    {
                        "intent": "KNOWLEDGE_QA",
                        "action": "回答问题",
                        "instruction": "如何删除测试用例？",
                        "confidence": 0.96,
                    }
                ]
            }
        ),
    )

    plan = plan_intents(
        "如何删除测试用例？",
        lambda clause: ("KNOWLEDGE_QA", 0.94),
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="doubao-test",
        base_url="https://ark.example/v1",
        api_key="test-only",
        timeout_seconds=5,
        tracing_enabled=False,
    )

    assert plan.operations[0].action == "ANSWER_QUESTION"


def test_selected_module_is_expressed_as_structured_target_kind() -> None:
    plan = deterministic_plan(
        "改写当前模块的公共前置条件",
        classify,
        has_targets=True,
    )

    assert plan.operations[0].intent == "CASE_MODIFY"
    assert plan.operations[0].target_kind == "module"


def test_sdk_router_uses_the_configured_chat_completions_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    agents = ModuleType("agents")
    openai = ModuleType("openai")

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured["agent"] = kwargs

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            captured["model"] = kwargs

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

    class FakeRunner:
        @staticmethod
        def run_sync(agent, prompt, max_turns):
            captured["prompt"] = prompt
            captured["max_turns"] = max_turns
            return SimpleNamespace(
                final_output=captured["agent"]["output_type"].model_validate(
                    {
                        "operations": [
                            {
                                "intent": "KNOWLEDGE_QA",
                                "instruction": "解释边界值",
                                "confidence": 0.96,
                            }
                        ]
                    }
                )
            )

    agents.Agent = FakeAgent
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: captured.update(tracing_disabled=disabled)
    openai.AsyncOpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "agents", agents)
    monkeypatch.setitem(sys.modules, "openai", openai)

    plan = sdk_plan(
        "解释边界值",
        phase="idle",
        target_context=[],
        attachment_context={"document_ids": ["checked-document"]},
        model_name="doubao-test",
        base_url="https://ark.example/v1/",
        api_key="test-only",
        timeout_seconds=5,
        tracing_enabled=False,
    )

    assert plan.operations[0].intent == "KNOWLEDGE_QA"
    assert captured["client"]["base_url"] == "https://ark.example/v1"
    assert captured["client"]["max_retries"] == 0
    assert captured["max_turns"] == 1
    assert captured["model"]["model"] == "doubao-test"
    assert captured["agent"]["output_type"] is agent_router.SemanticIntentPlan
    fields = agent_router.SemanticIntentOperation.model_fields
    assert "action" not in fields
    assert "routing_source" not in fields
    assert "action_evidence" in fields
    assert plan.operations[0].action == "ANSWER_QUESTION"
    assert captured["tracing_disabled"] is True

    assert json.loads(captured["prompt"])["available_attachments"] == {"document_ids": ["checked-document"]}


def test_unique_coverage_in_dedup_request_does_not_create_an_extra_review():
    plan = deterministic_plan(
        "检查账号登录模块重复冗余用例，说明重复依据和独有覆盖，只检查不修改。",
        classify_intent,
        has_targets=False,
    )
    assert [operation.intent for operation in plan.operations] == ["CASE_DEDUP"]


def test_positive_write_preserves_negative_constraints_and_low_confidence() -> None:
    content = "修改账号登录模块的前置条件，不要修改标题和步骤"
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_MODIFY",
                    "instruction": content,
                    "confidence": 0.6,
                    "target_kind": "module",
                    "target_text": "账号登录模块",
                    "action_evidence": "修改账号登录模块的前置条件",
                    "constraints": ["不要修改标题和步骤"],
                }
            ]
        }
    )
    draft = agent_router._validate_model_plan(
        content, plan, has_targets=False, phase="idle"
    ).operations[0]
    assert draft.intent == "CASE_MODIFY"
    assert draft.constraints == ["不要修改标题和步骤"]
    assert not agent_router.draft_needs_confirmation(draft.model_dump())


def test_unknown_target_retains_intent_and_asks_specific_question() -> None:
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_MODIFY",
                    "instruction": "修改优先级为P0",
                    "confidence": 0.98,
                }
            ]
        }
    )
    draft = agent_router._validate_model_plan(
        "修改优先级为P0", plan, has_targets=False, phase="idle"
    ).operations[0]
    assert draft.intent == "UNRESOLVED"
    assert "WRITE_ACTION_NOT_EXPLICIT" in draft.reason_codes


def test_high_rule_confidence_still_uses_semantic_router(monkeypatch) -> None:
    called = []

    def semantic(*args, **kwargs):
        called.append(args[0])
        return IntentPlanDraft.model_validate(
            {
                "operations": [
                    {
                        "intent": "CASE_QUERY",
                        "instruction": args[0],
                        "confidence": 0.6,
                    }
                ]
            }
        )

    monkeypatch.setattr(agent_router, "sdk_plan", semantic)
    plan = plan_intents(
        "查询全部用例",
        lambda text: ("CASE_QUERY", 0.99),
        has_targets=False,
        phase="idle",
        target_context=[],
        provider="openai_compatible",
        model_name="test",
        base_url="test",
        api_key="test",
        timeout_seconds=5,
        tracing_enabled=False,
    )
    assert called == ["查询全部用例"]
    assert not agent_router.draft_needs_confirmation(plan.operations[0].model_dump())


def test_dependencies_cannot_reference_future_operations() -> None:
    with pytest.raises(ValueError, match="dependency_must_reference"):
        IntentPlanDraft.model_validate(
            {
                "operations": [
                    {
                        "intent": "CASE_QUERY",
                        "instruction": "查询",
                        "confidence": 0.99,
                        "depends_on": 0,
                    }
                ]
            }
        )


def test_model_cannot_invent_action_evidence() -> None:
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_DELETE",
                    "instruction": "删除所有用例",
                    "confidence": 0.99,
                    "action_evidence": "删除所有用例",
                }
            ]
        }
    )
    draft = agent_router._validate_model_plan(
        "看看现有用例", plan, has_targets=False, phase="idle"
    ).operations[0]
    assert draft.intent == "UNRESOLVED"


@pytest.mark.parametrize(('content', 'evidence', 'expected'), [
    ('仅将用例 CASE-176BE2 的标题改为「登录成功」，其他字段保持不变。', '将用例的标题改为', 'CASE_MODIFY'),
    ('修改用例 CASE-176BE2：仅将标题改为「库存不足时拒绝创建订单」，其他字段保持不变。', '修改用例 CASE-176BE2', 'CASE_MODIFY'),
    ('不要将用例 CASE-176BE2 的标题改为「登录成功」。', '将用例的标题改为', 'KNOWLEDGE_QA'),
    ('仅将用例 CASE-176BE2 的标题改为「登录成功」。', '将用例 CASE-OTHER 的标题改为', 'UNRESOLVED'),
    ('仅查看用例 CASE-176BE2 的标题。', '将用例的标题改为', 'UNRESOLVED'),
    ('将用例 CASE-176BE2 归档，标题改为需要另行确认。', '将用例的标题改为', 'UNRESOLVED'),
])
def test_action_evidence_can_omit_case_identifier_but_not_meaning(content, evidence, expected):
    plan = IntentPlanDraft(operations=[agent_router.IntentOperationDraft(
        intent=expected if expected != 'UNRESOLVED' else 'CASE_MODIFY',
        instruction=content, confidence=1,
        target_kind='case', target_text='CASE-176BE2', action_evidence=evidence,
    )])
    draft = agent_router._validate_model_plan(content, plan, has_targets=False, phase='idle').operations[0]
    assert draft.intent == expected
    if expected == 'CASE_MODIFY':
        assert draft.action_evidence in content
        assert 'CASE-176BE2' in draft.action_evidence


def test_setting_priority_without_modify_keyword_is_an_explicit_action() -> None:
    content = "把账号登录模块用例的优先级设为P0，标题和步骤保持不变。"
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_MODIFY",
                    "instruction": content,
                    "confidence": 0.95,
                    "target_kind": "module",
                    "target_text": "账号登录模块用例",
                    "action_evidence": "把账号登录模块用例的优先级设为P0",
                }
            ]
        }
    )
    draft = agent_router._validate_model_plan(
        content, plan, has_targets=False, phase="idle"
    ).operations[0]
    assert draft.intent == "CASE_MODIFY"
    assert not draft.clarification_questions


def test_human_review_is_not_an_extra_agent_task() -> None:
    content = "生成2条用例，供我审阅"
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_GENERATE",
                    "instruction": content,
                    "confidence": 1,
                    "action_evidence": "生成2条用例",
                },
            ]
        }
    )
    validated = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert [op.intent for op in validated.operations] == ["CASE_GENERATE"]


def test_action_evidence_can_quote_two_original_fragments_with_ellipsis() -> None:
    content = "为账号登录模块增加密码找回功能的2条测试用例。"
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_GENERATE",
                    "instruction": content,
                    "confidence": 1,
                    "action_evidence": "增加...测试用例",
                    "target_kind": "module",
                    "target_text": "账号登录模块",
                }
            ]
        }
    )
    validated = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert validated.operations[0].intent == "CASE_GENERATE"


def test_singleton_dependency_array_keeps_dependency_validation() -> None:
    operations = [
        {"intent": "CASE_GENERATE", "instruction": "生成", "confidence": 1},
        {"intent": "CASE_MODIFY", "instruction": "修改", "confidence": 1, "depends_on": [0]},
    ]
    assert IntentPlanDraft.model_validate({"operations": operations}).operations[1].depends_on == 0
    operations[1]["depends_on"] = [1]
    with pytest.raises(ValueError, match="dependency_must_reference"):
        IntentPlanDraft.model_validate({"operations": operations})


def test_preservation_before_action_does_not_negate_the_action() -> None:
    content = "不要修改标题，只修改账号登录模块的前置条件，补充账号已启用。"
    plan = IntentPlanDraft.model_validate(
        {
            "operations": [
                {
                    "intent": "CASE_MODIFY",
                    "instruction": content,
                    "confidence": 1,
                    "action_evidence": "修改账号登录模块的前置条件",
                    "target_kind": "module",
                    "target_text": "账号登录模块",
                }
            ]
        }
    )
    validated = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert validated.operations[0].intent == "CASE_MODIFY"


@pytest.mark.parametrize("suffix,accepted", [("，只查询不修改。", True), ("，排除账号登录模块。", False)])
def test_original_query_keeps_quantity_and_exclusions_for_selector(suffix, accepted):
    content = "查询当前集合的全部100条用例" + suffix
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "CASE_QUERY", "instruction": content, "confidence": 1,
        "action_evidence": "查询当前集合的全部100条用例",
        "target_kind": "none", "target_text": "当前集合的全部用例",
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle").operations[0]
    assert result.instruction == content
    assert result.target_text == "当前集合的全部用例"


@pytest.mark.parametrize("target,accepted", [
    ("账号登录模块的全部10条用例，其他9个模块不得改动", True),
    ("账号登录模块的全部10条用例", True),
    ("账号登录模块的全部100条用例", False),
    ("账号登录模块的全部10条用例，排除管理员", False),
])
def test_model_scope_is_preserved_for_separate_selection(target, accepted):
    content = "整体重写「账号登录」模块的全部10条用例，保留原标题，其他9个模块不得改动。"
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "CASE_MODIFY", "instruction": content, "confidence": 1,
        "action_evidence": "整体重写「账号登录」模块的全部10条用例",
        "target_kind": "module", "target_text": target,
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle").operations[0]
    assert result.target_text == target
    assert result.instruction == content


def test_new_module_generation_uses_the_explicit_action_name():
    content = '新增「发票管理」模块，并生成恰好10条新的候选用例。现有100条用例不得修改。'
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "CASE_GENERATE", "instruction": content, "confidence": 1,
        "action_evidence": '新增「发票管理」模块，并生成恰好10条新的候选用例',
        "target_kind": "module", "target_text": "当前集合新增的发票管理模块",
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="maintenance").operations[0]
    assert result.target_text == '当前集合新增的发票管理模块'
    assert result.clarification_questions == []
    assert result.intent == 'CASE_GENERATE'


def test_explicit_whole_collection_modification_does_not_need_target_clarification():
    content = '将当前集合全部用例的优先级改为P0，其他字段不变。'
    plan = IntentPlanDraft.model_validate({'operations': [{
        'intent': 'CASE_MODIFY', 'instruction': content, 'confidence': 1,
        'action_evidence': '改为', 'target_kind': 'none', 'target_text': '当前集合全部用例的优先级',
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase='maintenance').operations[0]
    assert result.target_kind == 'none'
    assert result.target_text == '当前集合全部用例的优先级'
    assert not result.clarification_questions


def test_model_scope_paraphrase_is_preserved_for_semantic_selector():
    content = '重写用例 QA-1791437437142-1 的步骤和预期：校验登录响应HTTP 200。'
    plan = IntentPlanDraft.model_validate({'operations': [{
        'intent': 'CASE_MODIFY', 'instruction': content, 'confidence': 1,
        'action_evidence': '重写用例 QA-1791437437142-1 的步骤和预期',
        'target_kind': 'case', 'target_text': '编号为QA-1791437437142-1的用例',
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase='maintenance').operations[0]
    assert result.target_text == '编号为QA-1791437437142-1的用例'
    assert result.instruction == content
    assert result.clarification_questions == []


def test_model_candidate_scope_keeps_original_quantity_in_instruction():
    content='重写剩余未纳入的2条候选用例，已纳入正式集合的用例不得改动。补充前置条件。'
    plan=IntentPlanDraft.model_validate({'operations':[{
        'intent':'CASE_MODIFY','instruction':content,'confidence':1,
        'action_evidence':'重写剩余未纳入的2条候选用例','target_kind':'previous_result',
        'target_text':'剩余未纳入的候选用例',
    }]})
    result=agent_router._validate_model_plan(content,plan,has_targets=False,phase='candidate_review').operations[0]
    assert not result.clarification_questions
    assert result.target_text == '剩余未纳入的候选用例'
    assert result.instruction == content


def test_pending_candidate_multi_intent_scope_does_not_absorb_other_clauses():
    content='先查询剩余未纳入的候选用例，然后修改查到的候选：增加前置条件。'
    plan=IntentPlanDraft.model_validate({'operations':[
        {'intent':'CASE_QUERY','instruction':'查询剩余候选','confidence':1,'action_evidence':'先查询剩余未纳入的候选用例','target_kind':'condition','target_text':'当前任务剩余未纳入的候选'},
        {'intent':'CASE_MODIFY','instruction':'修改候选','confidence':1,'action_evidence':'然后修改查到的候选','target_kind':'previous_result','target_text':'上述查询结果','depends_on':0},
    ]})
    result=agent_router._validate_model_plan(content,plan,has_targets=False,phase='candidate_review')
    assert result.operations[0].target_text == '当前任务剩余未纳入的候选'
    assert result.operations[1].target_text == '上述查询结果'
    assert all(not op.clarification_questions for op in result.operations)


@pytest.mark.parametrize("intent,accepted", [("CASE_GENERATE", True), ("CASE_MODIFY", False)])
def test_literal_multi_module_generation_scope(intent, accepted):
    content = '生成30条测试用例，分为“预约创建”“预约变更”“签到与释放”三个模块，每个模块10条。'
    plan = IntentPlanDraft.model_validate({'operations': [{
        'intent': intent, 'instruction': content, 'confidence': 1,
        'action_evidence': '生成30条测试用例', 'target_kind': 'module',
        'target_text': '会议室预约的三个功能模块',
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase='maintenance').operations[0]
    assert result.instruction == content
    assert result.target_text == '会议室预约的三个功能模块'


def test_candidate_module_rewrite_preserves_model_scope():
    content='整体重写“预约变更”模块的全部10条候选。其他模块不要动。'
    plan=IntentPlanDraft.model_validate({'operations':[{
        'intent':'CASE_MODIFY','instruction':content,'confidence':1,
        'action_evidence':'整体重写“预约变更”模块的全部10条候选',
        'target_kind':'module','target_text':'预约变更模块全部待纳入候选用例',
    }]})
    result=agent_router._validate_model_plan(content,plan,has_targets=False,phase='candidate_review').operations[0]
    assert not result.clarification_questions
    assert result.target_text == '预约变更模块全部待纳入候选用例'


@pytest.mark.parametrize('ids,ambiguous,raises', [(['one'],False,False),(['outside'],False,True),(['one'],True,True)])
def test_query_selector_supplies_schema_and_rejects_ungrounded_ids(monkeypatch,ids,ambiguous,raises):
    import sys
    from types import ModuleType, SimpleNamespace
    agents, openai = ModuleType('agents'), ModuleType('openai')
    captured={}
    def agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)
    agents.Agent=agent
    agents.AgentOutputSchema=lambda *args,**kwargs:None
    agents.ModelSettings=SimpleNamespace
    agents.OpenAIChatCompletionsModel=lambda **kwargs:None
    agents.set_tracing_disabled=lambda value:None
    agents.Runner=SimpleNamespace(run_sync=lambda *args,**kwargs:SimpleNamespace(final_output=agent_router.QueryCaseSelection(ids=ids,ambiguous=ambiguous)))
    openai.AsyncOpenAI=lambda **kwargs:None
    monkeypatch.setitem(sys.modules,'agents',agents)
    monkeypatch.setitem(sys.modules,'openai',openai)
    kwargs=dict(model_name='test',base_url='https://example.invalid',api_key='test',timeout_seconds=1,tracing_enabled=False)
    if raises:
        with pytest.raises(ValueError):
            agent_router.select_query_case_ids('目标场景',[{'id':'one','title':'目标场景'}],**kwargs)
    else:
        assert agent_router.select_query_case_ids('目标场景',[{'id':'one','title':'目标场景'}],**kwargs)==['one']
    assert 'JSON Schema:' in captured['instructions']
    assert 'ambiguous' in captured['instructions']


def test_topic_query_keeps_original_instruction_alongside_model_scope():
    content='查询“预约查询”模块中关于无结果展示和取消后状态展示的用例，只列出来，不修改。'
    plan=IntentPlanDraft.model_validate({'operations':[{
        'intent':'CASE_QUERY','instruction':content,'confidence':1,
        'action_evidence':'查询','target_kind':'condition','target_text':'预约查询模块的两类场景',
    }]})
    result=agent_router._validate_model_plan(content,plan,has_targets=False,phase='maintenance').operations[0]
    assert not result.clarification_questions
    assert '无结果展示和取消后状态展示' in result.instruction
    assert result.target_text == '预约查询模块的两类场景'


def test_planning_preview_and_generation_are_one_task_with_literal_object():
    content = "为账号安全系统生成恰好12条候选用例。先提供测试规划供确认，再生成候选。"
    plan = IntentPlanDraft(operations=[
        dict(intent="CASE_GENERATE", instruction="生成12条候选", confidence=1,
             action_evidence="为账号安全系统生成恰好12条候选用例", depends_on=None,
             target_kind="module", target_text="账号安全系统"),
    ])
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert len(result.operations) == 1
    operation = result.operations[0]
    assert operation.intent == "CASE_GENERATE"
    assert operation.depends_on is None
    assert operation.target_text == "账号安全系统"
    assert operation.clarification_questions == []


def test_separate_generation_requests_are_not_merged():
    content = "生成登录用例，然后生成支付用例"
    plan = IntentPlanDraft(operations=[
        dict(intent="CASE_GENERATE", instruction="生成登录用例", confidence=1,
             action_evidence="生成登录用例", target_kind="none"),
        dict(intent="CASE_GENERATE", instruction="生成支付用例", confidence=1,
             action_evidence="生成支付用例", target_kind="none", depends_on=0),
    ])
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert len(result.operations) == 2
    assert result.operations[1].depends_on == 0


@pytest.mark.parametrize('variant,expected', [('batch', 1), ('different', 2), ('ordered', 2), ('ambiguous', 2)])
def test_shared_case_modification_is_one_batch(variant, expected):
    content = '修改候选 TC-TP-aaa-1、TC-TP-bbb-1：前置条件增加审计账号，优先级统一改为P0，其他字段不变。'
    if variant == 'ordered':
        content = content.replace('、', '，然后修改候选 ')
    operations = [dict(
        intent='CASE_MODIFY', instruction=content, confidence=1,
        action_evidence=key, target_kind='case', target_text=key,
        changes=['前置条件增加审计账号', '优先级改为P0'], constraints=['其他字段不变'],
        depends_on=None if index == 0 else 0,
    ) for index, key in enumerate(['TC-TP-aaa-1', 'TC-TP-bbb-1'])]
    if variant == 'different':
        operations[1]['changes'] = ['优先级改为P2']
    if variant == 'ambiguous':
        operations[1]['clarification_questions'] = ['请确认范围']
    if variant == 'batch':
        operations = [operations[0]]
        operations[0]['target_text'] = 'TC-TP-aaa-1、TC-TP-bbb-1'
    result = agent_router._validate_model_plan(content, IntentPlanDraft(operations=operations), has_targets=False, phase='candidate_review')
    assert len(result.operations) == expected
    if expected == 1:
        operation = result.operations[0]
        assert operation.target_text == 'TC-TP-aaa-1、TC-TP-bbb-1'
        assert operation.instruction == content
        assert operation.requires_confirmation
        assert operation.depends_on is None
    else:
        assert result.operations[1].depends_on == 0


@pytest.mark.parametrize('intent', ['CASE_MODIFY', 'CASE_DELETE'])
def test_previous_query_reference_survives_paraphrased_case_scope(intent):
    content = '仅把刚才查询到的用例优先级改为P2，其他字段和其他用例保持不变' if intent == 'CASE_MODIFY' else '删除刚才查询到的用例，其他用例保持不变'
    plan = IntentPlanDraft(operations=[dict(
        intent=intent, instruction='处理上次结果', confidence=1,
        action_evidence='改为' if intent == 'CASE_MODIFY' else '删除',
        target_kind='case', target_text='上次查询结果中的两条用例',
    )])
    operation = agent_router._validate_model_plan(content, plan, has_targets=False, phase='maintenance').operations[0]
    assert operation.target_text == '上次查询结果中的两条用例'
    assert operation.instruction == content
    assert operation.target_kind == 'case'
    assert not operation.clarification_questions
    assert operation.requires_confirmation


@pytest.mark.parametrize('content,uses_model', [
    ('删除刚才查询到的用例', False),
    ('请删除刚才查到的两条用例。', False),
    ('移除上次查询到的2条测试用例', False),
    ('不要删除刚才查询到的用例', True),
    ('如何删除刚才查询到的用例？', True),
    ('删除刚才查询到的失败用例', True),
    ('删除刚才查询到的用例，然后查询订单模块', True),
    ('删除登录模块的用例', True),
])
def test_literal_previous_query_always_uses_model(
    monkeypatch, content, uses_model,
):
    from unittest.mock import Mock

    model = Mock(return_value=IntentPlanDraft(operations=[agent_router.IntentOperationDraft(
        intent='KNOWLEDGE_QA', instruction=content, confidence=1,
    )]))
    monkeypatch.setattr(agent_router, 'sdk_plan', model)
    plan = plan_intents(content, classify_intent, has_targets=False,
        phase='maintenance', target_context=[], provider='openai_compatible',
        model_name='test', base_url='https://example.test/v1', api_key='test-only',
        timeout_seconds=5, tracing_enabled=False)
    model.assert_called_once()
    assert plan.operations[0].intent == 'KNOWLEDGE_QA'
    assert plan.operations[0].routing_source == 'semantic'


def test_model_failure_does_not_turn_query_result_modification_into_query(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(agent_router, 'sdk_plan', Mock(side_effect=TimeoutError()))
    plan = plan_intents('把刚才查询到的用例优先级改为P0，其他内容保持不变',
        classify_intent, has_targets=False, phase='maintenance', target_context=[],
        provider='openai_compatible', model_name='test', base_url='https://example.test/v1',
        api_key='test-only', timeout_seconds=5, tracing_enabled=False)
    assert plan.operations[0].intent == 'UNRESOLVED'
    assert plan.operations[0].requires_confirmation


def test_model_failure_requires_clarification_even_for_literal_write(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(agent_router, 'sdk_plan', Mock(side_effect=TimeoutError()))
    plan = plan_intents(
        '修改不存在模块的用例', classify_intent, has_targets=False,
        phase='maintenance', target_context=[], provider='openai_compatible',
        model_name='test', base_url='https://example.test/v1', api_key='test-only',
        timeout_seconds=5, tracing_enabled=False,
    )
    operation = plan.operations[0]
    assert operation.intent == 'UNRESOLVED'
    assert operation.requires_confirmation
    assert operation.reason_codes == ['MODEL_FAILED', 'SEMANTIC_ROUTING_UNAVAILABLE']


@pytest.mark.parametrize("content,target", [
    ("翻译成英文", "1234"),
    ("把上一条回答翻译成中文", "Delete all test cases"),
])
def test_text_followup_does_not_require_literal_asset_scope(content, target):
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "KNOWLEDGE_QA", "instruction": content, "confidence": 1,
        "action_evidence": content, "target_kind": "none", "target_text": target,
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    operation = result.operations[0]
    assert operation.intent == "KNOWLEDGE_QA"
    assert operation.action == "ANSWER_QUESTION"
    assert not operation.clarification_questions
    assert not operation.requires_confirmation


@pytest.mark.parametrize("separate", [False, True])
def test_reuse_lookup_is_part_of_generation_unless_separate_results_requested(separate):
    content = "查询历史用例资产，复用核心用例并生成新版用例"
    if separate:
        content += "，单独展示查询结果"
    plan = IntentPlanDraft.model_validate({"operations": [
        {"intent": "CASE_QUERY", "instruction": "查询历史用例资产", "action_evidence": "查询历史用例资产", "confidence": 0.99},
        {"intent": "CASE_GENERATE", "instruction": "生成新版用例", "action_evidence": "生成新版用例", "confidence": 0.99, "depends_on": 0},
    ]})
    if not separate:
        plan.operations = [plan.operations[1]]
        plan.operations[0].instruction = content
        plan.operations[0].depends_on = None
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle")
    assert [op.intent for op in result.operations] == (["CASE_QUERY", "CASE_GENERATE"] if separate else ["CASE_GENERATE"])
    if not separate:
        assert result.operations[0].instruction == content
        assert result.operations[0].depends_on is None


@pytest.mark.parametrize("content,expected", [
    ("重写登录模块用例", "CASE_MODIFY"),
    ("请改写登录模块用例", "CASE_MODIFY"),
    ("重写登录模块用例，步骤写得更清楚", "CASE_MODIFY"),
    ("重写登录模块用例并生成一套新版", "CASE_GENERATE"),
    ("如何重写登录模块用例？", "KNOWLEDGE_QA"),
    ("不要重写登录模块用例", "KNOWLEDGE_QA"),
])
def test_model_rewrite_intent_survives_validation(content, expected):
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": expected, "instruction": content, "confidence": 0.9,
        "action_evidence": content, "target_kind": "module", "target_text": "登录模块用例",
        "clarification_questions": ["请说明改动方向"],
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=True, phase="maintenance")
    assert result.operations[0].intent == expected
    if expected == "CASE_MODIFY":
        assert result.operations[0].requires_confirmation
        assert result.operations[0].clarification_questions == ["请说明改动方向"]
        assert result.operations[0].action != "BRIEF_CREATE"


@pytest.mark.parametrize('intent,value,clarifies', [
    ('CASE_MODIFY', 'P9', True), ('CASE_MODIFY', 'P3', True),
    ('CASE_MODIFY', 'P2', False), ('CASE_MODIFY', None, False),
    ('CASE_QUERY', 'P9', False),
])
def test_priority_assignment_validation_never_coerces_unknown_values(intent, value, clarifies):
    content = '把用例TC-1的优先级改成P9，其他不变'
    plan = IntentPlanDraft.model_validate({'operations': [{
        'intent': intent, 'instruction': content, 'confidence': 1,
        'action_evidence': content, 'priority_assignment': value,
    }]})
    operation = agent_router._validate_model_plan(content, plan, has_targets=True, phase='maintenance').operations[0]
    assert operation.priority_assignment == value
    assert bool(operation.clarification_questions) is clarifies
    if clarifies:
        assert operation.clarification_kind == 'requirements'
        assert value in operation.clarification_questions[0]
        assert 'P0、P1、P2' in operation.clarification_questions[0]


@pytest.mark.parametrize("fails", [False, True])
def test_routing_timing_logs_outcome_without_prompt_or_exception_text(monkeypatch, caplog, fails):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from casepilot_api import agent_router
    clock = iter([10.0, 35.25])
    monkeypatch.setattr(agent_router, "perf_counter", lambda: next(clock))
    private = "private-request-title-and-credential"
    result = object()
    runner = SimpleNamespace(run_sync=Mock(
        side_effect=RuntimeError(private) if fails else None,
        return_value=SimpleNamespace(final_output=result),
    ))
    if fails:
        with pytest.raises(RuntimeError):
            agent_router._run_routing_agent(runner, object(), private, stage="rewrite_reply", model_name="test-model")
    else:
        assert agent_router._run_routing_agent(runner, object(), private, stage="rewrite_reply", model_name="test-model") is result
    assert "stage=rewrite_reply" in caplog.text
    assert f"outcome={'error' if fails else 'ok'}" in caplog.text
    assert "duration_seconds=25.250" in caplog.text
    assert private not in caplog.text
    assert runner.run_sync.call_args.kwargs == {"max_turns": 1}
