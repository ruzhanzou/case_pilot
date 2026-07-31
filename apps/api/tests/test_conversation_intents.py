from types import SimpleNamespace
from uuid import uuid4

from casepilot_api.conversations import (
    AGENT_MEMORY_CONTENT_LIMIT,
    AGENT_MEMORY_MESSAGE_LIMIT,
    _agent_conversation_memory,
    _extract_explicit_test_object,
    _looks_like_brief_confirmation,
    _test_object_from_messages,
    classify_intent,
    render_test_brief_markdown,
    summarize_conversation_title,
)
from casepilot_api.schemas import (
    ConversationMessageCreate,
)
from casepilot_api.schemas import (
    TestBriefContent as BriefContent,
)


def test_intent_classifier_routes_generation_modification_and_qa() -> None:
    assert classify_intent("补充弱网用例")[0] == "CASE_GENERATE"
    assert classify_intent("为已登录用户修改密码生成测试用例") == (
        "CASE_GENERATE",
        0.98,
    )
    assert classify_intent("给当前用例补充弱网恢复步骤", has_targets=True)[0] == (
        "CASE_MODIFY"
    )
    assert classify_intent("为什么这条用例是 P0？", has_targets=True)[0] == (
        "KNOWLEDGE_QA"
    )
    assert classify_intent("你好") == ("SMALL_TALK", 0.99)
    assert classify_intent("你是谁") == ("SMALL_TALK", 0.99)
    assert classify_intent("删除当前用例", has_targets=True)[0] == "CASE_DELETE"
    assert classify_intent("查询用例")[0] == "CASE_QUERY"


def test_ambiguous_modification_requires_confirmation() -> None:
    intent, confidence = classify_intent("优化一下", has_targets=True)
    assert intent == "CASE_MODIFY"
    assert confidence < 0.8


def test_brief_review_routes_requirements_to_brief_updates() -> None:
    statement = "锁屏和切后台后允许继续保持实时语音通话"
    assert classify_intent(statement, phase="brief_review")[0] == "CASE_GENERATE"
    assert classify_intent("你好", phase="brief_review")[0] == "SMALL_TALK"
    assert (
        classify_intent("实时通话超时策略是什么？", phase="brief_review")[0]
        == "KNOWLEDGE_QA"
    )


def test_natural_language_brief_confirmation_phrases() -> None:
    assert _looks_like_brief_confirmation("确认说明并开始生成")
    assert _looks_like_brief_confirmation("确认测试说明并开始生成")
    assert not _looks_like_brief_confirmation("继续修改测试说明")


def test_conversation_message_supports_batch_candidate_targets() -> None:
    payload = ConversationMessageCreate.model_validate(
        {
            "content": "把这些用例的优先级调整为 P1",
            "scope": "module",
            "target_candidate_snapshots": [
                {
                    "ref": "candidate-0",
                    "version": 2,
                    "snapshot": {
                        "title": "弱网恢复",
                        "priority": "P0",
                    },
                }
            ],
        }
    )
    assert payload.target_candidate_snapshots[0].version == 2
    assert payload.scope == "module"


def test_conversation_title_uses_a_compact_first_turn_summary() -> None:
    assert (
        summarize_conversation_title(
            "请帮我为手机号验证码登录生成测试用例，覆盖频控、过期和弱网。"
        )
        == "手机号验证码登录用例设计"
    )
    assert summarize_conversation_title("CasePilot 可以帮我做什么？") == (
        "了解 CasePilot 能力"
    )
    assert summarize_conversation_title("测试说明与测试用例有什么区别？") == (
        "测试说明与测试用例的区别"
    )


def test_agent_memory_keeps_the_latest_100_non_empty_messages_in_order() -> None:
    newest_first = [
        SimpleNamespace(
            role="user" if index % 2 else "assistant",
            content=f"第 {index} 句话",
        )
        for index in range(104, -1, -1)
    ]

    class FakeDb:
        def scalars(self, statement):
            del statement
            return newest_first

    memory = _agent_conversation_memory(FakeDb(), uuid4())

    assert len(memory) == AGENT_MEMORY_MESSAGE_LIMIT
    assert memory[0]["content"] == "第 5 句话"
    assert memory[-1]["content"] == "第 104 句话"


def test_agent_memory_bounds_each_message_before_model_input() -> None:
    long_message = SimpleNamespace(
        role="user",
        content="测" * (AGENT_MEMORY_CONTENT_LIMIT + 20),
    )

    class FakeDb:
        def scalars(self, statement):
            del statement
            return [long_message]

    memory = _agent_conversation_memory(FakeDb(), uuid4())

    assert len(memory[0]["content"]) == AGENT_MEMORY_CONTENT_LIMIT
    assert memory[0]["content"].endswith("…")


def test_test_brief_only_renders_test_object_clarification() -> None:
    markdown = render_test_brief_markdown(
        1,
        {
            "test_object": "手机号验证码登录",
            "test_objective": "验证登录流程",
            "open_questions": [],
        },
    )

    assert "## 测试对象\n\n手机号验证码登录" in markdown
    assert "## 测试对象澄清" in markdown
    assert "测试对象已明确，无需澄清" in markdown
    assert "建议确认" not in markdown


def test_test_brief_schema_discards_non_object_clarifications() -> None:
    content = BriefContent.model_validate(
        {
            "test_object": "支付回调接口",
            "open_questions": [
                {
                    "id": "Q-TIMEOUT",
                    "question": "超时阈值是多少？",
                    "blocking": True,
                }
            ],
        }
    )

    assert content.open_questions == []


def test_latest_explicit_test_object_survives_a_follow_up_question() -> None:
    messages = [
        SimpleNamespace(
            role="user",
            content="测试对象为豆包APP",
            created_at=1,
        ),
        SimpleNamespace(
            role="user",
            content="测试对象不是明确了吗",
            created_at=2,
        ),
    ]

    assert _extract_explicit_test_object("测试对象为豆包APP") == "豆包APP"
    assert _extract_explicit_test_object("测试对象不是明确了吗") == ""
    assert _test_object_from_messages(messages) == "豆包APP"
