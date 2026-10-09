from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api import conversations
from casepilot_api.case_scope import filter_priority
from casepilot_api.schemas import ConversationMessageCreate


@pytest.mark.parametrize("text", ["查询优先级为P0的用例", "查询P0用例", "修改P0用例，优先级改为P1"])
def test_priority_source_is_distinct_from_assignment(text):
    assert filter_priority(text, [{"priority": "P0"}, {"priority": "P1"}]) == [{"priority": "P0"}]


@pytest.mark.parametrize(
    "intent,text",
    [
        ("CASE_QUERY", "查询登录模块中包含短信验证码的用例"),
        ("CASE_QUERY", "查询登录模块中标签为安全的用例"),
        ("CASE_MODIFY", "把登录模块中包含短信验证码的用例优先级改为P0"),
    ],
)
def test_content_selection_keeps_full_condition_and_body(monkeypatch, intent, text):
    cases = [
        dict(
            id=str(uuid4()),
            case_key=f"TC-{i}",
            title="登录验证",
            module="登录",
            priority="P1",
            steps=[{"action": action, "expected": "成功"}],
        )
        for i, action in enumerate(["发送短信验证码", "提交密码"])
    ]
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *args: cases)
    selector = Mock(return_value=[cases[0]["id"]])
    monkeypatch.setattr(conversations, "select_query_case_ids", selector)
    result, error = conversations._resolve_action_scope(
        Mock(),
        SimpleNamespace(collection_id=uuid4(), context={"phase": "maintenance"}),
        ConversationMessageCreate(content=text),
        intent,
        "登录",
    )
    assert not error
    assert list(map(str, result.target_case_ids)) == [cases[0]["id"]]
    assert result.content == text
    assert selector.call_args.args == (text, cases)


def test_explicit_selection_still_filters_content_and_rejects_unknown_ids(monkeypatch):
    cases = [
        dict(id=str(uuid4()), case_key=f"TC-{i}", title="验证", module="", priority="P1")
        for i in range(2)
    ]
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *args: cases)
    monkeypatch.setattr(conversations, "_expand_conversation_targets", lambda db, c, p: p)
    selector = Mock(return_value=[cases[1]["id"]])
    monkeypatch.setattr(conversations, "select_query_case_ids", selector)
    result, error = conversations._resolve_action_scope(
        Mock(),
        SimpleNamespace(collection_id=uuid4(), context={"phase": "maintenance"}),
        ConversationMessageCreate(
            content="查询选中用例中包含验证码的用例", target_case_ids=[cases[0]["id"]]
        ),
        "CASE_QUERY",
    )
    assert selector.call_args.args[1] == [cases[0]]
    assert error  # The model cannot introduce a case outside the UI selection.


def test_selector_receives_all_query_evidence(monkeypatch):
    import json

    from agents import Runner

    from casepilot_api.agent_router import QueryCaseSelection, select_query_case_ids

    case = dict(
        id=str(uuid4()),
        title="验证",
        module="登录",
        priority="P0",
        description="说明",
        tags=["安全"],
        preconditions=["已注册"],
        steps=[{"action": "发送验证码", "expected": "不泄露验证码"}],
    )

    def run(agent, payload, **kwargs):
        supplied = json.loads(payload)["cases"][0]
        for key, value in case.items():
            assert supplied[key] == value
        return SimpleNamespace(final_output=QueryCaseSelection(ids=[case["id"]], ambiguous=False))

    monkeypatch.setattr(Runner, "run_sync", run)
    assert select_query_case_ids(
        "涉及验证码",
        [case],
        model_name="test",
        base_url="https://example.test/v1",
        api_key="test",
        timeout_seconds=1,
        tracing_enabled=False,
    ) == [case["id"]]


def test_mutation_assignment_does_not_filter_original_priority():
    cases = [{"priority": "P0"}, {"priority": "P1"}]
    assert filter_priority("修改登录模块用例优先级为P0", cases, mutation=True) == cases
    assert (
        filter_priority("修改优先级为P0的用例，标题改为「登录」", cases, mutation=True) == cases[:1]
    )


def test_shortened_model_scope_cannot_drop_priority(monkeypatch):
    cases = [
        dict(id=str(uuid4()), title="登录验证", module="登录", priority=priority)
        for priority in ["P0", "P1"]
    ]
    monkeypatch.setattr(conversations, "_load_scope_snapshots", lambda *args: cases)
    result, error = conversations._resolve_action_scope(
        Mock(),
        SimpleNamespace(collection_id=uuid4(), context={"phase": "maintenance"}),
        ConversationMessageCreate(content="查询登录模块优先级为P0的用例"),
        "CASE_QUERY",
        "登录",
    )
    assert not error
    assert list(map(str, result.target_case_ids)) == [cases[0]["id"]]


def test_shortened_model_scope_cannot_drop_explicit_excluded_case(monkeypatch):
    cases = [dict(id=str(uuid4()), case_key=f'QA-{i}', title='登录验证', module='登录', priority='P1') for i in range(2)]
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    selector = Mock(return_value=[cases[1]['id']])
    monkeypatch.setattr(conversations, 'select_query_case_ids', selector)
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase': 'maintenance'}),
        ConversationMessageCreate(content='修改登录模块优先级为P0，排除用例QA-0'),
        'CASE_MODIFY', '登录模块',
    )
    assert not error
    assert list(map(str, result.target_case_ids)) == [cases[1]['id']]
    selector.assert_not_called()


def test_exact_exclusion_keeps_query_priority_filter(monkeypatch):
    cases = [dict(id=str(uuid4()), case_key=f'QA-{i}', title='登录验证', module='登录', priority=p) for i, p in enumerate(['P0','P0','P1'])]
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    selector = Mock(side_effect=AssertionError('Exact filter must not invoke a model'))
    monkeypatch.setattr(conversations, 'select_query_case_ids', selector)
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase': 'maintenance'}),
        ConversationMessageCreate(content='查询登录模块优先级为P0的用例，排除用例QA-0'), 'CASE_QUERY', '登录模块',
    )
    assert not error
    assert list(map(str, result.target_case_ids)) == [cases[1]['id']]


@pytest.mark.parametrize('text,allowed', [
    ('删除登录模块的用例，但排除用例QA-0', True),
    ('删除登录模块失败场景的用例，但排除用例QA-0', False),
    ('删除登录模块的用例，但排除用例QA-404', False),
])
def test_deletion_only_accepts_fully_resolved_exclusions(monkeypatch, text, allowed):
    cases = [dict(id=str(uuid4()), case_key=f'QA-{i}', title='登录验证', module='登录', priority='P1') for i in range(2)]
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    selector = Mock(side_effect=AssertionError('Deletion must not guess semantic scope'))
    monkeypatch.setattr(conversations, 'select_query_case_ids', selector)
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase': 'maintenance'}),
        ConversationMessageCreate(content=text), 'CASE_DELETE', '登录模块',
    )
    assert bool(error) is not allowed
    if allowed:
        assert list(map(str, result.target_case_ids)) == [cases[1]['id']]
    selector.assert_not_called()


def test_priority_like_text_in_assignment_is_not_a_source_filter():
    cases = [{'priority': 'P0'}, {'priority': 'P1'}]
    assert filter_priority('将用例QA-1的标题改为「P0登录验收」', cases, mutation=True) == cases
    assert filter_priority('修改P1用例，标题改为「P0登录验收」', cases, mutation=True) == cases[1:]


@pytest.mark.parametrize('text,expected', [
    ('查询登录模块中步骤包含短信验证码的用例', [0]),
    ('查询前置条件中包含「审计账号」的正式用例', [0]),
    ('查询标题包含「P0登录」的用例', [0]),
    ('查询步骤不包含「短信验证码」的用例', [1]),
    ('查询预期结果包含「登录成功」的用例', [1]),
    ('查询标题包含「不存在XYZ」的用例', []),
])
def test_explicit_field_substrings_do_not_depend_on_model(monkeypatch, text, expected):
    cases = [
        dict(id=str(uuid4()), case_key='TC-1', title='P0登录', module='登录', priority='P1', preconditions=['审计账号已配置'], steps=[{'action':'输入短信验证码', 'expected':'校验通过'}]),
        dict(id=str(uuid4()), case_key='TC-2', title='密码登录', module='登录', priority='P0', preconditions=[], steps=[{'action':'提交密码', 'expected':'登录成功'}]),
    ]
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    selector = Mock(side_effect=AssertionError('Literal field match must not invoke model'))
    monkeypatch.setattr(conversations, 'select_query_case_ids', selector)
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase':'maintenance'}),
        ConversationMessageCreate(content=text), 'CASE_QUERY',
    )
    assert not error
    assert list(map(str,result.target_case_ids)) == [cases[i]['id'] for i in expected]
    selector.assert_not_called()


@pytest.mark.parametrize('text', [
    '查询标题包含「登录」或优先级为P0的用例',
    '查询标题包含「登录」且状态为停用的用例',
    '查询已停用的标题包含「登录」的用例',
    '查询标题包含「登录」且步骤包含「密码」的用例',
])
def test_literal_shortcut_does_not_ignore_additional_conditions(text):
    from casepilot_api.case_scope import resolve_literal_content
    assert resolve_literal_content(text, [{'title':'登录','module':'登录'}]) is None


@pytest.mark.parametrize('operator', ['不是', '不为', '不等于'])
def test_simple_negative_priority_is_resolved_without_a_model(monkeypatch, operator):
    cases = [dict(id=str(uuid4()), title='登录', module='登录', priority=p) for p in ['P0','P1','P2']]
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    monkeypatch.setattr(conversations, 'select_query_case_ids', Mock(side_effect=AssertionError('No model needed')))
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase':'maintenance'}),
        ConversationMessageCreate(content=f'查询登录模块优先级{operator}P0的用例'), 'CASE_QUERY', '登录模块',
    )
    assert not error
    assert list(map(str,result.target_case_ids)) == [c['id'] for c in cases[1:]]


@pytest.mark.parametrize('reference', ['刚才查到的用例', '上次查询到的用例', '前面查找出的测试用例'])
@pytest.mark.parametrize('new_title', ['订单', '二十二条验收'])
def test_previous_query_reference_cannot_be_shadowed_by_new_title(monkeypatch, reference, new_title):
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={'phase': 'maintenance'})
    target_id = uuid4()
    source = SimpleNamespace(id=uuid4(), conversation_id=conversation.id)
    db = Mock()
    db.scalar.return_value = source
    monkeypatch.setattr(conversations, '_expand_conversation_targets',
        lambda db, c, p: p.model_copy(update={'target_case_ids': [target_id]}))
    result, error = conversations._resolve_action_scope(db, conversation,
        ConversationMessageCreate(content=f'把{reference}标题改为「{new_title}」'),
        'CASE_MODIFY', new_title)
    assert error is None
    assert result.target_case_ids == [target_id]
    assert result.source_operation_id == source.id


def test_or_query_keeps_module_and_priority_pairing(monkeypatch):
    cases = [dict(id=str(uuid4()), case_key=f'TC-{i}', title='验证', module=m, priority=p)
             for i, (m, p) in enumerate([('登录', 'P0'), ('登录', 'P1'), ('订单', 'P1')])]
    text = '查询登录模块中优先级为P0的用例，或者订单模块中优先级为P1的用例，只查询不修改'
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    selector = Mock(side_effect=AssertionError('Structured OR needs no model'))
    monkeypatch.setattr(conversations, 'select_query_case_ids', selector)
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase': 'maintenance'}),
        ConversationMessageCreate(content=text), 'CASE_QUERY', '登录模块、订单模块',
    )
    assert error is None
    assert list(map(str, result.target_case_ids)) == [cases[0]['id'], cases[2]['id']]
    selector.assert_not_called()


@pytest.mark.parametrize('text,expected', [
    ('查询标题包含「登录」的用例', [2]),
    ('查询标题包含登录的用例', [2]),
    ('查询订单模块标题包含「登录」的用例', [2]),
    ('查询登录模块标题包含「登录」的用例', []),
    ('查询标题包含「TC-0」的用例', [2]),
])
def test_query_field_values_do_not_become_module_or_case_references(monkeypatch, text, expected):
    cases = [dict(id=str(uuid4()), case_key=f'TC-{i}', title=t, module=m, priority='P1')
             for i, (t, m) in enumerate([('短信验证码', '登录'), ('密码验证码', '登录'), ('登录异常提示 TC-0', '订单')])]
    monkeypatch.setattr(conversations, '_load_scope_snapshots', lambda *args: cases)
    monkeypatch.setattr(conversations, '_expand_conversation_targets', lambda db, c, p: p)
    monkeypatch.setattr(conversations, 'select_query_case_ids', Mock(side_effect=AssertionError('Literal query needs no model')))
    result, error = conversations._resolve_action_scope(
        Mock(), SimpleNamespace(collection_id=uuid4(), context={'phase': 'maintenance'}),
        ConversationMessageCreate(content=text), 'CASE_QUERY', '登录模块',
    )
    assert error is None
    assert list(map(str, result.target_case_ids)) == [cases[i]['id'] for i in expected]


@pytest.mark.parametrize('text', [
    '查询登录模块P0用例或者订单模块P1用例，且标题包含错误',
    '查询登录模块P0用例或者未知模块P1用例',
    '查询登录模块P0用例或者订单模块中步骤包含支付的用例',
])
def test_structured_union_never_discards_unsupported_qualifiers(text):
    from casepilot_api.case_scope import resolve_module_priority_union
    cases = [dict(id=str(uuid4()), module=m, priority='P0') for m in ['登录', '订单']]
    assert resolve_module_priority_union(text, cases) is None


@pytest.mark.parametrize('quantity,count,expected_error', [
    ('二十二', 2, True), ('二十二', 22, False), ('十一', 1, True),
    ('十一', 11, False), ('十', 10, False), ('二十', 20, False), ('二二', 2, True),
])
def test_previous_query_quantity_uses_complete_chinese_number(
    monkeypatch, quantity, count, expected_error,
):
    conversation = SimpleNamespace(id=uuid4(), collection_id=uuid4(), context={})
    db = Mock()
    db.scalar.return_value = SimpleNamespace(id=uuid4(), conversation_id=conversation.id)
    ids = [uuid4() for _ in range(count)]
    monkeypatch.setattr(conversations, '_expand_conversation_targets',
        lambda db, c, p: p.model_copy(update={'target_case_ids': ids}))
    result, error = conversations._resolve_action_scope(db, conversation,
        ConversationMessageCreate(content=f'删除刚才查询到的{quantity}条用例'), 'CASE_DELETE')
    assert bool(error) is expected_error
    if not expected_error:
        assert result.target_case_ids == ids
