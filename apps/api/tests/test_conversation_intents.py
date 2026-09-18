from types import SimpleNamespace
from uuid import uuid4

import pytest

from casepilot_api.conversations import (
    AGENT_MEMORY_CONTENT_LIMIT,
    AGENT_MEMORY_MESSAGE_LIMIT,
    _agent_conversation_memory,
    _collection_candidates,
    _expand_conversation_targets,
    _extract_explicit_test_object,
    _looks_like_brief_confirmation,
    _merge_change_fields,
    _test_object_from_messages,
    classify_intent,
    recover_terminal_workspace_job,
    render_test_brief_markdown,
    small_talk_response,
    summarize_conversation_title,
    terminal_workspace_context,
)
from casepilot_api.schemas import (
    ConversationMessageCreate,
)
from casepilot_api.schemas import (
    TestBriefContent as BriefContent,
)


def test_intent_classifier_routes_generation_modification_and_qa() -> None:
    assert classify_intent("补充弱网用例")[0] == "CASE_GENERATE"
    assert classify_intent(
        "doubao Generate test cases for phone verification-code login, "
        "covering the happy path, rate limits, code expiry, and poor networks."
    ) == ("CASE_GENERATE", 0.98)
    assert classify_intent(
        "dou baoGenerate test cases for phone verification-code login, "
        "covering the happy path, rate limits, code expiry, and poor networks."
    ) == ("CASE_GENERATE", 0.98)
    assert classify_intent("How to generate test cases?")[0] == "KNOWLEDGE_QA"
    assert classify_intent("Can you generate test cases for login?")[0] == (
        "CASE_GENERATE"
    )
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
    assert classify_intent("CasePilot 可以帮我做什么？")[0] == "SMALL_TALK"
    assert classify_intent("CasePilot 可以帮我完成哪些测试工作？")[0] == (
        "SMALL_TALK"
    )
    assert classify_intent("边界值分析和等价类有什么区别？")[0] == "KNOWLEDGE_QA"
    assert classify_intent("介绍一下接口幂等性的测试方法")[0] == "KNOWLEDGE_QA"
    assert classify_intent("帮我设计登录功能的测试用例")[0] == "CASE_GENERATE"
    assert classify_intent("查询登录集合中的 P0 用例")[0] == "CASE_QUERY"
    assert classify_intent("查询已有用例")[0] == "CASE_QUERY"
    assert classify_intent("删除当前选中的两条用例", has_targets=True)[0] == (
        "CASE_DELETE"
    )
    assert classify_intent("先别删除当前用例", has_targets=True)[0] == (
        "KNOWLEDGE_QA"
    )
    assert classify_intent(
        "把失败场景的预期结果改得更明确", has_targets=True
    )[0] == "CASE_MODIFY"
    assert classify_intent("请把预期结果写得更明确。")[0] == "CASE_MODIFY"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("不要生成测试用例", "KNOWLEDGE_QA"),
        ("请不要生成测试用例", "KNOWLEDGE_QA"),
        ("Don't generate test cases.", "KNOWLEDGE_QA"),
        ("Modify the selected test case to cover poor networks.", "CASE_MODIFY"),
        ("Delete the selected test case.", "CASE_DELETE"),
        ("Find all P0 test cases.", "CASE_QUERY"),
        ("Please generate test cases for login and tell me why.", "CASE_GENERATE"),
    ],
)
def test_english_actions_and_negated_generation(
    content: str, expected: str
) -> None:
    assert classify_intent(content, has_targets=True)[0] == expected


def test_change_set_merges_selected_nested_step_without_touching_other_steps() -> None:
    item = {
        "base_snapshot": {
            "title": "登录成功",
            "steps": [
                {"action": "输入账号", "expected": "信息显示"},
                {"action": "点击登录", "expected": "登录成功"},
            ],
        },
        "proposed_snapshot": {
            "title": "新标题",
            "steps": [
                {"action": "输入账号", "expected": "信息显示"},
                {"action": "点击登录", "expected": "登录成功且只有一个会话"},
            ],
        },
    }
    merged = _merge_change_fields(item, {"steps[1].expected"})
    assert merged["title"] == "登录成功"
    assert merged["steps"][0]["expected"] == "信息显示"
    assert merged["steps"][1]["expected"] == "登录成功且只有一个会话"
    assert item["base_snapshot"]["steps"][1]["expected"] == "登录成功"


def test_module_target_expands_generated_candidates() -> None:
    candidates = [
        SimpleNamespace(ref="TC-1", version=2, snapshot={"module": "登录", "title": "正常登录"}),
        SimpleNamespace(ref="TC-2", version=1, snapshot={"module": "支付", "title": "支付成功"}),
    ]

    class FakeDb:
        def scalars(self, statement):
            assert statement is not None
            return candidates

    conversation = SimpleNamespace(
        id=uuid4(), collection_id=uuid4(), context={"phase": "candidate_review"}
    )
    payload = ConversationMessageCreate.model_validate(
        {
            "content": "修改登录模块的预期结果",
            "targets": [{"kind": "module", "module": "登录"}],
        }
    )
    expanded = _expand_conversation_targets(FakeDb(), conversation, payload)
    assert [(item.ref, item.version) for item in expanded.target_candidate_snapshots] == [
        ("TC-1", 2)
    ]


def test_current_case_question_expands_selected_candidate() -> None:
    candidate_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        ref="TC-1",
        version=2,
        snapshot={"title": "登录成功", "steps": [{"action": "输入验证码"}]},
    )

    class FakeDb:
        def scalar(self, statement):
            assert statement is not None
            return candidate

    conversation = SimpleNamespace(
        id=uuid4(),
        collection_id=uuid4(),
        context={"selected_case_id": str(candidate_id)},
    )
    payload = ConversationMessageCreate(content="你能告诉我当前用例有什么问题吗？")
    expanded = _expand_conversation_targets(FakeDb(), conversation, payload)
    assert expanded.target_case_ids == []
    assert expanded.target_candidate_snapshots[0].snapshot["title"] == "登录成功"
    assert classify_intent(payload.content, has_targets=True)[0] == "KNOWLEDGE_QA"


def test_current_case_question_expands_selected_formal_case() -> None:
    case_id = uuid4()

    class FakeDb:
        def __init__(self):
            self.scalar_calls = 0

        def scalar(self, statement):
            assert statement is not None
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else case_id

        def scalars(self, statement):
            assert statement is not None
            return [case_id]

    conversation = SimpleNamespace(
        id=uuid4(),
        collection_id=uuid4(),
        context={"selected_case_id": str(case_id)},
    )
    expanded = _expand_conversation_targets(
        FakeDb(),
        conversation,
        ConversationMessageCreate(content="你能告诉我当前用例有什么问题吗？"),
    )
    assert expanded.target_case_ids == [case_id]


def test_terminal_generation_releases_workspace_phase_and_job() -> None:
    context = {"phase": "generating", "active_job_id": "old-job", "chat_width": 400}
    recovered = terminal_workspace_context(
        context,
        operation="generate",
        has_candidates=False,
        has_brief=True,
    )
    assert recovered == {
        "phase": "brief_review",
        "active_job_id": None,
        "active_operation_id": None,
        "chat_width": 400,
    }
    assert context["phase"] == "generating"
    assert terminal_workspace_context(
        context,
        operation="generate",
        has_candidates=True,
        has_brief=True,
    )["phase"] == "candidate_review"


def test_failed_generation_is_recovered_when_workspace_is_read() -> None:
    job_id = uuid4()
    conversation = SimpleNamespace(
        id=uuid4(),
        context={"phase": "generating", "active_job_id": str(job_id)},
        updated_at=None,
    )

    class FakeDb:
        committed = False

        def get(self, model, identifier):
            assert identifier == job_id
            return SimpleNamespace(status="failed", operation="generate")

        def scalar(self, statement):
            return uuid4() if "workspace_test_briefs" in str(statement) else None

        def commit(self):
            self.committed = True

        def refresh(self, item):
            assert item is conversation

    db = FakeDb()
    recover_terminal_workspace_job(db, conversation)
    assert db.committed
    assert conversation.context["phase"] == "brief_review"
    assert conversation.context["active_job_id"] is None


def test_ambiguous_modification_requires_confirmation() -> None:
    intent, confidence = classify_intent("优化一下", has_targets=True)
    assert intent == "CASE_MODIFY"
    assert confidence < 0.8


def test_small_talk_uses_an_instant_context_free_response() -> None:
    assert small_talk_response("你好").startswith("你好！我是 CasePilot")
    assert small_talk_response("谢谢") == "不客气，有需要时继续告诉我即可。"
    assert "生成、修改、删除和查询测试用例" in small_talk_response(
        "CasePilot 可以帮我做什么？"
    )


def test_brief_review_does_not_treat_plain_statements_as_asset_writes() -> None:
    statement = "锁屏和切后台后允许继续保持实时语音通话"
    assert classify_intent(statement, phase="brief_review")[0] == "KNOWLEDGE_QA"
    assert classify_intent("你好", phase="brief_review")[0] == "SMALL_TALK"
    assert (
        classify_intent("实时通话超时策略是什么？", phase="brief_review")[0]
        == "KNOWLEDGE_QA"
    )
    assert classify_intent("什么是ASR", phase="brief_review")[0] == "KNOWLEDGE_QA"
    assert classify_intent("如何修改测试说明？", phase="brief_review")[0] == "KNOWLEDGE_QA"
    assert classify_intent("为什么要补充弱网场景？", phase="brief_review")[0] == "KNOWLEDGE_QA"


def test_collection_candidates_builds_query_with_collection_columns() -> None:
    class FakeDb:
        def scalars(self, statement):
            assert statement is not None
            return []

    candidates, suggested = _collection_candidates(
        FakeDb(),
        SimpleNamespace(space_id=uuid4()),
        "请生成登录用例",
    )

    assert candidates == []
    assert suggested is None


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
