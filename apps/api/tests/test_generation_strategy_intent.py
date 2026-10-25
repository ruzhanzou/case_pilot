import pytest

from casepilot_api.generation_strategy import generation_strategy_from_text, is_strategy_question


@pytest.mark.parametrize(
    "text,expected",
    [
        ("测试对象：账号系统，生成登录用例", "generate"),
        ("参考历史用例补充回归", "select_and_generate"),
        ("请复用已有资产", "select_and_generate"),
        ("select", "select"),
        ("SELECT：测试对象账号系统", "select"),
        ("策略：select\n测试对象：账号系统", "select"),
        ("请使用 select_and_generate 生成测试用例", "select_and_generate"),
        ("strategy=select_and_generate", "select_and_generate"),
        ("select是什么意思？", "generate"),
        ("请解释使用select的步骤", "generate"),
        ("不要使用select", "generate"),
        ("不要select，直接生成", "generate"),
        ("selectivity测试", "generate"),
        ("select_and_generate_extra", "generate"),
        ("执行SQL select * from accounts", "generate"),
        ("请总结：```select```", "generate"),
        ("请翻译“使用 select”", "generate"),
        ("策略：select，但不要复用", "generate"),
        ("新增发票管理模块并生成10条候选用例，现有用例和其他模块不得改写或删除", "generate"),
    ],
)
def test_only_explicit_unambiguous_strategy_directives_enable_reuse(text, expected):
    assert generation_strategy_from_text(text) == expected


def test_strategy_question_is_qa_not_generation():
    assert is_strategy_question("select和select_and_generate有什么区别")


@pytest.mark.parametrize("text,expected", [
    ("找一下已有登录用例，参考后改写", "select_and_generate"),
    ("能帮我找已有登录用例吗？", "select_and_generate"),
    ("选择现有用例组成新集合", "select"),
    ("直接复用已有的登录用例", "select"),
    ("复用已有的，缺少的补齐", "select_and_generate"),
    ("系统支持搜索用例资产吗？", "generate"),
    ("如果找到已有用例，可以复用吗？", "generate"),
    ("不要搜索历史用例，直接生成", "generate"),
    ("请翻译“参考历史用例改写”", "generate"),
    ("生成登录用例", "generate"),
    ("复用已有会话进行登录测试", "generate"),
    ("参照历史用例补充登录场景", "select_and_generate"),
    ("不要改标题，参考已有资产修改步骤", "select_and_generate"),
    ("为青禾系统全新生成用例，不复用历史", "generate"),
    ("能帮我复用已有登录用例吗？", "select_and_generate"),
])
def test_natural_language_asset_authorization(text, expected):
    assert generation_strategy_from_text(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("确认复用", ["a", "b"]), ("只用第一条", ["a"]),
    ("这两条直接用", ["a", "b"]), ("这三条直接用", None),
    ("只用第3条", None), ("不复用，继续生成", []),
    ("确认复用但修改第二条", None), ("那条直接用", None),
])
def test_asset_replies_are_bound_to_displayed_scope(text, expected):
    from casepilot_api.generation_strategy import asset_choice_from_text
    assert asset_choice_from_text(text, ["a", "b"]) == expected


@pytest.mark.parametrize("text,expected", [
    ("帮我找找以前账号登录那块的用例，拿来参考一下", "select_and_generate"),
    ("搜一下登录相关的用例", "select_and_generate"),
    ("有没有现成的登录用例可以参考？", "select_and_generate"),
    ("帮我找类似登录流程的用例参考", "select_and_generate"),
    ("请检索账号认证的测试案例", "select_and_generate"),
    ("不要找以前的用例，重新生成", "generate"),
    ("别搜登录相关用例", "generate"),
    ("如果搜一下登录用例会怎样", "generate"),
    ("请翻译“搜一下登录用例”", "generate"),
    ("为搜索功能生成用例", "generate"),
    ("搜索功能的用例需要覆盖空结果", "generate"),
])
def test_colloquial_search_requires_an_operation_not_a_feature_description(text, expected):
    assert generation_strategy_from_text(text) == expected


@pytest.mark.parametrize('action,confirmed,expected', [
    ('revise', True, False), ('none', True, False),
    ('confirm', True, True), ('confirm', False, False),
])
def test_revision_never_passes_brief_confirmation_gate(monkeypatch, action, confirmed, expected):
    from types import SimpleNamespace
    from agents import Runner
    from casepilot_api.config import get_settings
    from casepilot_api.generation_strategy import interpret_generation_choice

    def run(agent, *args, **kwargs):
        return SimpleNamespace(final_output=agent.output_type(
            brief_action=action, confirms_brief=confirmed))

    monkeypatch.setattr(Runner, 'run_sync', run)
    settings = get_settings().model_copy(update={'agent_provider': 'openai_compatible', 'agent_api_key': 'fixture'})
    result = interpret_generation_choice('在现有规划中增加一个测试点，其余保持不变', settings)
    assert result.confirms_brief is expected


def test_identical_choices_are_shared_only_inside_one_request(monkeypatch):
    from unittest.mock import Mock
    from pydantic import BaseModel
    from types import SimpleNamespace
    from casepilot_api import generation_strategy as module
    class Result(BaseModel):
        selected_ids: list[str] = []
    settings = SimpleNamespace(agent_provider='openai_compatible', routing_model='fixture')
    call = Mock(return_value=Result(selected_ids=['a']))
    monkeypatch.setattr(module, '_interpret_generation_choice', call)
    token = module.choice_request_cache.set({})
    try:
        first = module.interpret_generation_choice('只选这一条', settings, ['a'])
        first.selected_ids.clear()
        assert module.interpret_generation_choice('只选这一条', settings, ['a']).selected_ids == ['a']
        assert call.call_count == 1
        module.interpret_generation_choice('只选这一条', settings, ['b'])
        module.interpret_generation_choice('只选这一条', settings, ['a'], [{'role':'user','content':'新上下文'}])
        assert call.call_count == 3
        module.interpret_generation_choice('只选这一条', settings, ['a'], retry_only=True)
        assert call.call_count == 4
    finally:
        module.choice_request_cache.reset(token)
    module.interpret_generation_choice('只选这一条', settings, ['a'])
    assert call.call_count == 5


@pytest.mark.parametrize('reference,evidence,target,valid,expected', [
    ('current', '', 'other', True, None),
    ('named', '切换到订单集合', 'other', True, 'other'),
    ('named', '模型编造的引用', 'other', False, None),
    ('named', '', 'other', False, None),
    ('none', '切换到订单集合', 'other', False, None),
    ('named', '', 'current', True, None),
])
def test_bound_collection_switch_requires_original_user_evidence(
        monkeypatch, reference, evidence, target, valid, expected):
    from types import SimpleNamespace
    from agents import Runner
    from casepilot_api.config import get_settings
    from casepilot_api.generation_strategy import interpret_generation_choice

    def run(agent, prompt, **kwargs):
        import json
        assert json.loads(prompt)['current_collection_id'] == 'current'
        return SimpleNamespace(final_output=agent.output_type(
            target_collection_id=target, collection_reference=reference,
            target_collection_evidence=evidence,
        ))

    monkeypatch.setattr(Runner, 'run_sync', run)
    settings = get_settings().model_copy(update={'agent_provider': 'openai_compatible', 'agent_api_key': 'fixture'})
    arguments = dict(collection_catalog=[{'id': 'current', 'name': '当前工作区'},
                                        {'id': 'other', 'name': '订单'}],
                     explicit_collection_only=True, current_collection_id='current')
    if not valid:
        with pytest.raises(ValueError, match='collection_reference_without_user_evidence'):
            interpret_generation_choice('切换到订单集合', settings, **arguments)
    else:
        assert interpret_generation_choice('切换到订单集合', settings, **arguments).target_collection_id == expected


@pytest.mark.parametrize('catalog,case_ids,narrow', [(None, None, False), ([], None, True),
                                                    ([], ['a'], False)])
def test_collection_only_interpretation_omits_unrelated_generation_decisions(monkeypatch, catalog, case_ids, narrow):
    from types import SimpleNamespace
    from agents import Runner
    from casepilot_api.config import get_settings
    from casepilot_api.generation_strategy import interpret_generation_choice

    def run(agent, prompt, **kwargs):
        fields = set(agent.output_type.model_fields)
        collection_fields = {'target_collection_id', 'collection_reference', 'target_collection_evidence'}
        if narrow:
            assert fields == collection_fields
            assert 'requested_count' not in agent.instructions
            assert 'brief_action' not in agent.instructions
        else:
            assert fields > collection_fields
            assert 'selected_ids' in fields and 'brief_action' in fields
        return SimpleNamespace(final_output=agent.output_type())

    monkeypatch.setattr(Runner, 'run_sync', run)
    settings = get_settings().model_copy(update={'agent_provider': 'openai_compatible', 'agent_api_key': 'fixture'})
    result = interpret_generation_choice('查询当前集合', settings, case_ids=case_ids, collection_catalog=catalog)
    assert result.target_collection_id is None
    assert result.strategy == 'generate'


@pytest.mark.parametrize('requested,kind', [(False, None), (True, None), (True, 'CASE_MODIFY')])
def test_retry_interpretation_only_requests_retry_decisions(monkeypatch, requested, kind):
    from types import SimpleNamespace
    from agents import Runner
    from casepilot_api.config import get_settings
    from casepilot_api.generation_strategy import interpret_generation_choice
    import json

    def run(agent, prompt, **kwargs):
        assert set(agent.output_type.model_fields) == {'retry_requested', 'retry_kind'}
        assert 'brief_action' not in agent.instructions
        assert json.loads(prompt)['conversation_memory'] == [{'role': 'assistant', 'content': '修改失败'}]
        return SimpleNamespace(final_output=agent.output_type(retry_requested=requested, retry_kind=kind))

    monkeypatch.setattr(Runner, 'run_sync', run)
    settings = get_settings().model_copy(update={'agent_provider': 'openai_compatible', 'agent_api_key': 'fixture'})
    result = interpret_generation_choice('再做一遍', settings, retry_only=True,
        conversation_memory=[{'role': 'assistant', 'content': '修改失败'}])
    assert result.retry_requested is requested
    assert result.retry_kind == kind
