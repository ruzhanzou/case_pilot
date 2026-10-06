from uuid import UUID, uuid4

import pytest

from casepilot_api.agent_router import deterministic_plan
from casepilot_api.case_scope import (
    common_module_path,
    filter_priority,
    module_contains,
    resolve_scope,
)
from casepilot_api.conversations import classify_intent

CASES = [
    {
        "id": str(uuid4()),
        "case_key": "TC-1",
        "title": "支付成功",
        "module": "支付/退款",
        "priority": "P0",
    },
    {
        "id": str(uuid4()),
        "case_key": "TC-10",
        "title": "支付失败",
        "module": "支付/下单",
        "priority": "P1",
    },
    {
        "id": str(uuid4()),
        "case_key": "TC-2",
        "title": "登录成功",
        "module": "账号/登录",
        "priority": "P0",
    },
]


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("review支付模块的用例", "CASE_REVIEW"),
        ("检查支付模块的冗余", "CASE_DEDUP"),
        ("分析支付模块覆盖缺口", "COVERAGE_ANALYZE"),
        ("删除支付模块用例", "CASE_DELETE"),
        ("编写支付模块用例", "CASE_GENERATE"),
        ("修改支付模块的预期结果", "CASE_MODIFY"),
        ("如何检查冗余", "KNOWLEDGE_QA"),
        ("检查冗余，不要删除用例", "CASE_DEDUP"),
    ],
)
def test_action_intents(text, intent):
    assert classify_intent(text)[0] == intent


def test_explicit_case_does_not_match_key_prefix():
    assert resolve_scope("修改 TC-10", CASES)["ids"] == [CASES[1]["id"]]
    assert resolve_scope("修改 TC-999", CASES)["error"]


def test_parent_module_and_priority():
    scope = resolve_scope("查询支付模块的 P0 用例", CASES)
    assert set(scope["ids"]) == {CASES[0]["id"], CASES[1]["id"]}
    assert filter_priority("P0", CASES) == [CASES[0], CASES[2]]
    assert module_contains("支付", "支付 / 退款")
    assert not module_contains("支付", "支付设置/退款")


def test_numbered_module_label_resolves_natural_name():
    cases = [{**CASES[0], "module": "性能验收/07-支付结算/01-场景组"}]
    assert resolve_scope("review支付结算模块的用例", cases)["ids"] == [CASES[0]["id"]]


def test_generation_target_uses_common_parent_path():
    assert common_module_path([
        "性能验收/07-支付结算/01-场景组",
        "性能验收/07-支付结算/02-场景组",
    ]) == "性能验收/07-支付结算"
    assert common_module_path(["A/B/C", "A/X/C"]) == "A"


def test_ambiguous_leaf_and_missing_module_do_not_select_everything():
    cases = CASES + [{**CASES[0], "module": "海外/退款"}]
    assert resolve_scope("修改退款模块", cases)["error"]
    assert resolve_scope("修改支付/退款模块", cases)["ids"] == [CASES[0]["id"]]
    assert resolve_scope("删除不存在模块", cases)["error"]


def test_each_operation_resolves_its_own_module():
    plan = deterministic_plan(
        "修改支付模块的预期并删除账号模块用例", classify_intent, has_targets=False
    )
    assert [item.intent for item in plan.operations] == ["CASE_MODIFY", "CASE_DELETE"]
    scopes = [resolve_scope(item.instruction, CASES)["ids"] for item in plan.operations]
    assert set(scopes[0]).isdisjoint(scopes[1])


def test_server_explicit_scope_overrides_stale_selection(monkeypatch):
    from types import SimpleNamespace

    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate

    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda db, conversation: CASES)

    class Db:
        def scalars(self, query):
            return CASES

    monkeypatch.setattr(
        conversations,
        "case_to_view",
        lambda db, item: SimpleNamespace(model_dump=lambda **kwargs: item),
    )
    conversation = SimpleNamespace(
        id=uuid4(), collection_id=uuid4(), context={"phase": "maintenance"}
    )
    payload = ConversationMessageCreate(content="修改TC-10", target_case_ids=[CASES[0]["id"]])
    resolved, error = conversations._resolve_action_scope(
        Db(), conversation, payload, "CASE_MODIFY"
    )
    assert error is None
    assert [str(item) for item in resolved.target_case_ids] == [CASES[1]["id"]]
    missing, error = conversations._resolve_action_scope(
        Db(), conversation, payload.model_copy(update={"content": "修改不存在模块"}), "CASE_MODIFY"
    )
    assert error


def test_query_scope_does_not_truncate_at_twenty(monkeypatch):
    from types import SimpleNamespace

    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate

    cases = [{**CASES[0], "id": str(uuid4()), "case_key": f"TC-{index}"} for index in range(1000)]

    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda db, conversation: cases)

    class Db:
        def scalars(self, query):
            return cases

    monkeypatch.setattr(
        conversations,
        "case_to_view",
        lambda db, item: SimpleNamespace(model_dump=lambda **kwargs: item),
    )
    conversation = SimpleNamespace(
        id=uuid4(), collection_id=uuid4(), context={"phase": "maintenance"}
    )
    payload = ConversationMessageCreate(content="查询支付模块全部 P0 用例")
    resolved, error = conversations._resolve_action_scope(Db(), conversation, payload, "CASE_QUERY")
    assert error is None
    assert len(resolved.target_case_ids) == 1000


def test_generate_in_selected_module_stays_generation():
    for text in ["编写支付模块的用例", "给支付模块增加异常用例", "补充支付模块的退款用例"]:
        assert classify_intent(text, has_targets=True)[0] == "CASE_GENERATE"


def test_priority_assignment_is_not_a_target_filter():
    assert filter_priority("将支付模块优先级改为P0", CASES) == CASES
    assert filter_priority("把P1用例优先级调整为P0", CASES) == [CASES[1]]


def test_unknown_second_module_is_not_silently_ignored():
    assert resolve_scope("删除支付模块和不存在模块的用例", CASES)["error"]


def test_mixed_language_module_reference_and_case_key_errors():
    assert len(resolve_scope("review支付模块", CASES)["ids"]) == 2
    assert resolve_scope("修改TC-999", CASES)["error"]
    assert resolve_scope("修改TC-1和TC-999", CASES)["error"]


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Find duplicate test cases", "CASE_DEDUP"),
        ("Review payment cases, do not delete anything", "CASE_REVIEW"),
        ("检查支付模块是否重复", "CASE_DEDUP"),
        ("为支付模块补充覆盖缺口用例", "CASE_GENERATE"),
        ("检查刚生成的用例", "CASE_REVIEW"),
        ("如何生成覆盖缺口的用例", "KNOWLEDGE_QA"),
    ],
)
def test_analysis_and_writing_are_distinguished(text, intent):
    assert classify_intent(text)[0] == intent


def test_query_action_returns_all_matching_cases(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate

    snapshots = [{**CASES[0], "id": str(uuid4()), "case_key": f"TC-{i}"} for i in range(25)]
    rows = [(SimpleNamespace(id=UUID(item["id"])), object()) for item in snapshots]
    by_id = {item["id"]: item for item in snapshots}
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    monkeypatch.setattr(conversations, "_collection_gate", lambda *args: None)
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *args: snapshots)
    monkeypatch.setattr(
        conversations,
        "case_to_view",
        lambda db, item, **kwargs: SimpleNamespace(model_dump=lambda **kwargs: by_id[str(item.id)]),
    )
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), space_id=uuid4(), context={})
    assistant, action, task = conversations._start_action(
        db,
        SimpleNamespace(id=uuid4()),
        conversation,
        None,
        ConversationMessageCreate(content="查询支付模块全部 P0 用例"),
        "CASE_QUERY",
        0.96,
    )
    assert action["count"] == 25 and task is None
    assert len(assistant.target_case_ids) == 25
    assert "TC-24" in assistant.content


def test_delete_redundant_module_does_not_prepare_whole_module_deletion(monkeypatch):
    from types import SimpleNamespace

    from casepilot_api import conversations
    from casepilot_api.schemas import ConversationMessageCreate, ConversationTarget

    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *args: CASES)
    conversation = SimpleNamespace(collection_id=uuid4(), context={})
    payload = ConversationMessageCreate(
        content="删除支付模块的重复用例",
        targets=[ConversationTarget(kind="case", case_ids=[CASES[2]["id"]])],
    )
    _, error = conversations._resolve_action_scope(None, conversation, payload, "CASE_DELETE")
    assert error and "具体用例" in error


def test_unclassified_module_target_remains_supported():
    assert module_contains("", "")
    assert not module_contains("", "支付")
