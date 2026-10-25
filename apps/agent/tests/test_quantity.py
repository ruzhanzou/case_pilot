"""Execution contracts; semantic accuracy is evaluated separately with a real model."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.pipeline import requested_case_count
from casepilot_agent.planning import requested_point_count
from casepilot_agent.quantity import OutputQuantity, interpret_quantity


def test_case_budget_uses_model_response_and_preserves_context():
    execute = Mock(return_value=OutputQuantity(case_count=7, test_point_count=3))
    request = GenerationRequest(prompt="不要十条，改成七条", markdown_content="密码至少8位")
    assert requested_case_count(request, execute) == 7
    args = execute.call_args.args
    assert args[0] == "output_quantity.interpreted"
    assert args[2]["prompt"] == request.prompt
    assert args[2]["markdown_content"] == request.markdown_content
    assert args[4] == request.model_id


def test_case_budget_does_not_become_point_budget():
    execute = Mock(return_value=OutputQuantity(case_count=20))
    assert requested_point_count("生成二十条用例", execute) is None


@pytest.mark.parametrize("budget", [0, -1])
def test_non_positive_quantity_is_rejected(budget):
    with pytest.raises(ValidationError):
        OutputQuantity(case_count=budget)


@pytest.mark.parametrize("field", ["case_count", "test_point_count"])
def test_over_limit_model_result_is_rejected(field):
    execute = Mock(return_value=OutputQuantity(**{field: 501}))
    with pytest.raises(ValueError, match="500"):
        interpret_quantity(execute, {"prompt": "生成五百零一条"})


def test_model_failure_never_falls_back_to_regex():
    execute = Mock(side_effect=TimeoutError("unavailable"))
    with pytest.raises(TimeoutError):
        requested_point_count("生成2个测试点", execute)


def test_point_budget_forwards_history_for_model_references():
    execute = Mock(return_value=OutputQuantity(test_point_count=7))
    memory = [{"role": "user", "content": "测试点先按七个规划"}]
    assert requested_point_count("就按刚才说的数量", execute, memory) == 7
    assert execute.call_args.args[2]["conversation_memory"] == memory


def test_selected_scope_is_forwarded_for_model_budget_interpretation():
    execute = Mock(return_value=OutputQuantity(case_count=1))
    context = {'original_test_point_ids':['P1','P2'], 'selected_test_point_ids':['P1']}
    request = GenerationRequest(prompt='两个测试点两条用例', confirmed_plan={
        'selection_context':context,'test_points':[{'id':'P1'}]})
    assert requested_case_count(request, execute) == 1
    assert execute.call_args.args[2]['selection_context'] == context


def test_incremental_point_budget_receives_retained_plan_and_replacements():
    execute = Mock(return_value=OutputQuantity(test_point_count=1))
    context = {
        'previous_test_points': [{'id': 'P1'}, {'id': 'P2'}],
        'update_mode': 'merge', 'superseded_test_point_ids': [],
        'revision_actions': ['upsert'],
    }
    assert requested_point_count('原来的两个不动，再加一个', execute,
                                 planning_context=context) == 1
    assert execute.call_args.args[2]['planning_context'] == context


@pytest.mark.parametrize("mode, expected", [("new", 30), ("total", 13)])
def test_total_and_additional_budgets_use_live_inventory(mode, expected):
    execute = Mock(return_value=OutputQuantity(case_count=30, case_count_mode=mode))
    request = GenerationRequest(prompt="增加到30个", confirmed_plan={
        "existing_cases": [{"id": str(i)} for i in range(17)]})
    assert requested_case_count(request, execute) == expected
    assert len(execute.call_args.args[2]["existing_cases"]) == 17


@pytest.mark.parametrize("cases", [None, [{"id": "a"}, {"id": "a"}]])
def test_total_requires_valid_inventory(cases):
    from casepilot_agent.quantity import resolve_case_budget
    with pytest.raises(ValueError):
        resolve_case_budget(OutputQuantity(case_count=30, case_count_mode="total"), cases)


def test_total_does_not_generate_or_delete_when_target_already_met():
    from casepilot_agent.quantity import resolve_case_budget
    with pytest.raises(ValueError, match="无需新增"):
        resolve_case_budget(OutputQuantity(case_count=1, case_count_mode="total"), [{"id": "a"}])


def test_module_total_excludes_unrelated_inventory():
    from casepilot_agent.quantity import resolve_case_budget
    cases = [{'id': str(i)} for i in range(37)]
    quantity = OutputQuantity(case_count=30, case_count_mode='total',
                              scope_case_ids=[str(i) for i in range(17)])
    assert resolve_case_budget(quantity, cases) == 13


def test_scope_cannot_invent_or_repeat_asset_ids():
    from casepilot_agent.quantity import resolve_case_budget
    for ids in [['foreign'], ['a', 'a']]:
        with pytest.raises(ValueError):
            resolve_case_budget(OutputQuantity(case_count=30, case_count_mode='total',
                                               scope_case_ids=ids), [{'id': 'a'}])


def test_additional_budget_reserves_unique_reuse_outputs():
    execute = Mock(return_value=OutputQuantity(case_count=13, count_includes_reuse=False,
                                               preserve_existing=True))
    request = GenerationRequest(prompt='复用17条再新增13条', confirmed_plan={'reuse': {
        'decisions': [{'action': 'reuse', 'source': {'key': str(i)}} for i in range(17)]}})
    assert requested_case_count(request, execute) == 30
    assert request.confirmed_plan['generation_budget']['preserve_existing']
