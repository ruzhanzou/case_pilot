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


def classify(clause: str) -> tuple[str, float]:
    if "生成" in clause:
        return "CASE_GENERATE", 0.96
    if "修改" in clause or "改写" in clause:
        return "CASE_MODIFY", 0.93
    if "删除" in clause:
        return "CASE_DELETE", 0.95
    return "KNOWLEDGE_QA", 0.9


def test_multi_intent_plan_preserves_order_and_limits_to_three() -> None:
    plan = deterministic_plan(
        "先生成登录用例，然后修改刚生成的异常场景；删除旧用例；查询全部用例",
        classify,
        has_targets=False,
    )

    assert [item.intent for item in plan.operations] == [
        "CASE_GENERATE",
        "CASE_MODIFY",
        "CASE_DELETE",
    ]
    assert plan.operations[1].target_kind == "previous_result"
    assert plan.operations[2].requires_confirmation is True


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
    agents.set_tracing_disabled = lambda disabled: captured.update(
        tracing_disabled=disabled
    )
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
