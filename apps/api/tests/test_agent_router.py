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
    assert validated.operations[0].intent == "KNOWLEDGE_QA"


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
    assert validated.operations[0].intent == "KNOWLEDGE_QA"


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
            return SimpleNamespace(
                final_output=IntentPlanDraft.model_validate(
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
        model_name="doubao-test",
        base_url="https://ark.example/v1/",
        api_key="test-only",
        timeout_seconds=5,
        tracing_enabled=False,
    )

    assert plan.operations[0].intent == "KNOWLEDGE_QA"
    assert captured["client"]["base_url"] == "https://ark.example/v1"
    assert captured["model"]["model"] == "doubao-test"
    assert captured["agent"]["output_type"] is IntentPlanDraft
    assert captured["tracing_disabled"] is True


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
    assert draft.intent == "CASE_MODIFY"
    assert draft.clarification_questions


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
                {
                    "intent": "CASE_REVIEW",
                    "instruction": "审阅新用例",
                    "confidence": 1,
                    "action_evidence": "供我审阅",
                    "depends_on": 0,
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
def test_collection_query_recovers_literal_quantity_without_losing_exclusions(suffix, accepted):
    content = "查询当前集合的全部100条用例" + suffix
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "CASE_QUERY", "instruction": content, "confidence": 1,
        "action_evidence": "查询当前集合的全部100条用例",
        "target_kind": "none", "target_text": "当前集合的全部用例",
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle").operations[0]
    assert bool(result.clarification_questions) is not accepted
    if accepted:
        assert result.target_text == "当前集合的全部100条用例"
        assert result.target_kind == "condition"


@pytest.mark.parametrize("target,accepted", [
    ("账号登录模块的全部10条用例，其他9个模块不得改动", True),
    ("账号登录模块的全部10条用例", True),
    ("账号登录模块的全部100条用例", False),
    ("账号登录模块的全部10条用例，排除管理员", False),
])
def test_module_scope_accepts_literal_fragments_but_not_invented_scope(target, accepted):
    content = "整体重写「账号登录」模块的全部10条用例，保留原标题，其他9个模块不得改动。"
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "CASE_MODIFY", "instruction": content, "confidence": 1,
        "action_evidence": "整体重写「账号登录」模块的全部10条用例",
        "target_kind": "module", "target_text": target,
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="idle").operations[0]
    assert bool(result.clarification_questions) is not accepted
    if accepted: assert "账号登录」模块的全部10条用例" in result.target_text


def test_new_module_generation_uses_the_explicit_action_name():
    content = '新增「发票管理」模块，并生成恰好10条新的候选用例。现有100条用例不得修改。'
    plan = IntentPlanDraft.model_validate({"operations": [{
        "intent": "CASE_GENERATE", "instruction": content, "confidence": 1,
        "action_evidence": '新增「发票管理」模块，并生成恰好10条新的候选用例',
        "target_kind": "module", "target_text": "当前集合新增的发票管理模块",
    }]})
    result = agent_router._validate_model_plan(content, plan, has_targets=False, phase="maintenance").operations[0]
    assert result.target_text == '发票管理'
    assert result.clarification_questions == []
    assert result.intent == 'CASE_GENERATE'
