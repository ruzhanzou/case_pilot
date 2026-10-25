from copy import deepcopy

import pytest

from casepilot_agent.case_allocation import CaseAllocation, AllocationReview
from casepilot_agent.compact_generation import StageContractError
from casepilot_agent.quantity import OutputQuantity
from test_compact_generation import request as base_request, run, execute


def request(count):
    req = base_request(count)
    req.prompt += "；" + "；".join(f"有效账号{i}、未激活账号{i}" for i in range(10))
    req.prompt += "；原有效账号；另一个有效账号；原第二点"
    return req


@pytest.mark.parametrize('point_count,groups', [
    (2, [['P-0'], ['P-0'], ['P-1'], ['P-1']]),
    (4, [['P-0', 'P-1'], ['P-2', 'P-3']]),
])
def test_case_budget_independent_of_immutable_points(point_count, groups):
    req = request(point_count)
    before = deepcopy(req.confirmed_plan)
    previews = []
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'test_case.allocation_reviewed':
            return AllocationReview(supported=True, issues=[])
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=len(groups))
        if stage == 'test_case.allocated':
            return CaseAllocation(scenarios=[dict(point_ids=ids, title=f'登录条件{i}', variant=f'有效账号{i}')
                                             for i, ids in enumerate(groups)])
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(req, executor, lambda *a: previews.append(a))
    assert req.confirmed_plan == before
    assert [p.model_dump(mode='json') for p in result.test_points] == before['test_points']
    assert len(result.test_cases) == len(groups)
    assert [c.test_point_ids for c in result.test_cases] == groups
    assert len({c.id for c in result.test_cases}) == len(groups)
    assert all(not p.startswith('ALLOC-') for c in result.test_cases for p in c.test_point_ids)
    assert result.quality.passed
    assert not previews  # Partial allocations never become adoptable candidates.


@pytest.mark.parametrize('groups,error', [
    ([['P-0'], ['foreign'], ['P-1']], 'invalid_point_reference'),
    ([['P-0'], ['P-0'], ['P-0']], 'uncovered_test_point'),
    ([['P-0', 'P-0'], ['P-1'], ['P-1']], 'invalid_point_reference'),
])
def test_allocation_rejects_wrong_scope(groups, error):
    def executor(stage, *args):
        if stage == 'test_case.allocation_reviewed':
            return AllocationReview(supported=True, issues=[])
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=3)
        if stage == 'test_case.allocated':
            return CaseAllocation(scenarios=[dict(point_ids=ids, title=f'条件{i}', variant=f'账号{i}')
                                             for i, ids in enumerate(groups)])
        raise AssertionError('Invalid allocation must not generate')
    with pytest.raises(StageContractError, match=error):
        run(request(2), executor)


def test_partial_allocated_batch_is_failure_not_success_with_wrong_count():
    previews = []
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'test_case.allocation_reviewed':
            return AllocationReview(supported=True, issues=[])
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=4)
        if stage == 'test_case.allocated':
            return CaseAllocation(scenarios=[dict(point_ids=[f'P-{i//2}'], title=f'登录{i}', variant=f'账号{i}')
                                             for i in range(4)])
        result = execute(stage, instruction, payload, result_type, model_id)
        if stage == 'test_case.generated':
            result.test_cases = [c for c in result.test_cases if (c.get('slot') if isinstance(c, dict) else c.slot) != 4]
        return result
    result = run(request(2), executor, lambda *a: previews.append(a))
    assert len(result.test_cases) == 3
    assert not result.quality.passed
    assert any(i.code == 'case_count_mismatch' for i in result.quality.issues)
    assert not previews


def test_unsupported_account_state_never_reaches_generation_after_bounded_repair():
    allocations, reviews = [], []
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=4)
        if stage == 'test_case.allocated':
            allocations.append(payload)
            return CaseAllocation(scenarios=[dict(point_ids=[f'P-{i//2}'], title=f'登录{i}',
                                                   variant=f'未激活账号{i}') for i in range(4)])
        if stage == 'test_case.allocation_reviewed':
            reviews.append(payload)
            return AllocationReview(supported=False, issues=['需求未允许未激活账号登录'])
        raise AssertionError('Unsupported variants must never generate content')
    from casepilot_agent.pipeline import AwaitingInput
    with pytest.raises(AwaitingInput):
        run(request(2), executor)
    assert len(allocations) == len(reviews) == 2
    assert allocations[1]['validation_feedback'] == ['需求未允许未激活账号登录']


def test_invalid_allocation_cannot_be_stored_as_a_valid_checkpoint():
    from casepilot_agent.compact_generation import validate_stage_result
    bad = CaseAllocation(scenarios=[dict(point_ids=['outside'], title='登录', variant='有效账号')])
    with pytest.raises(StageContractError, match='invalid_point_reference'):
        validate_stage_result(bad, {'requested_case_count':1,'test_points':[{'id':'P-0'}]})


def test_allocating_extra_cases_keeps_confirmed_reuse_snapshot_exact():
    from casepilot_agent.providers.mock import MockProvider
    from casepilot_agent.contracts import GenerationRequest
    req = request(2)
    source = MockProvider().generate(GenerationRequest(prompt='登录')).test_cases[0].model_dump(mode='json')
    req.confirmed_plan['reuse'] = {'strategy':'select_and_generate', 'decisions':[
        {'point_id':'P-0', 'action':'reuse', 'reason':'已确认复用',
         'source':{'key':'original','label':'原用例','locator':'原集合','snapshot':deepcopy(source)}}]}
    original_plan = deepcopy(req.confirmed_plan)
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=3)
        if stage == 'test_case.allocated':
            return CaseAllocation(scenarios=[
                dict(point_ids=['P-0'],source_point_id='P-0',title='原场景',variant='原有效账号'),
                dict(point_ids=['P-0'],title='第二账号',variant='另一个有效账号'),
                dict(point_ids=['P-1'],title='第二点',variant='原第二点')])
        if stage == 'test_case.allocation_reviewed':
            return AllocationReview(supported=True, issues=[])
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(req, executor)
    assert result.quality.passed and len(result.test_cases) == 3
    reused = result.test_cases[0].model_dump(mode='json')
    for field in ['title','preconditions','steps','priority','tags','case_type','module']:
        assert reused[field] == source[field]
    assert req.confirmed_plan == original_plan


def test_allocation_cannot_silently_replace_confirmed_reuse_with_new_cases():
    from casepilot_agent.case_allocation import validate_allocation
    allocation = CaseAllocation(scenarios=[dict(point_ids=['P-0'],title='新用例',variant='新账号')])
    with pytest.raises(StageContractError, match='dropped_confirmed_reuse'):
        validate_allocation(allocation, {'requested_case_count':1,'test_points':[{'id':'P-0'}],
                                         'reuse_decisions':[{'point_id':'P-0'}], 'prompt':'新账号'})


def test_invented_variant_is_rejected_even_if_another_model_might_approve_it():
    from casepilot_agent.case_allocation import validate_allocation
    allocation = CaseAllocation(scenarios=[dict(point_ids=['P-0'],variant='企业认证账号')])
    with pytest.raises(StageContractError, match='variant_not_in_user_request'):
        validate_allocation(allocation, {'requested_case_count':1,'test_points':[{'id':'P-0'}],
                                         'prompt':'正确账号密码登录成功'})


def test_missing_conditions_asks_question_without_generating():
    from casepilot_agent.pipeline import AwaitingInput
    def executor(stage, *args):
        if stage == 'output_quantity.interpreted': return OutputQuantity(case_count=4)
        if stage == 'test_case.allocated':
            return CaseAllocation(scenarios=[],needs_clarification=True,
                                  clarification_question='请明确两种账号条件')
        raise AssertionError('Must wait for user input')
    with pytest.raises(AwaitingInput) as error:
        run(base_request(2), executor)
    assert error.value.requirement.open_questions[0].id == 'case_allocation_conditions'


def test_answer_is_forwarded_and_can_ground_subsequent_allocation():
    from types import SimpleNamespace
    from casepilot_agent.pipeline import GenerationPipeline
    from semantic_validation_fixture import with_point_semantics
    answer = '普通账号、管理员账号，均遵循相同登录规则'
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'output_quantity.interpreted': return OutputQuantity(case_count=4)
        if stage == 'test_case.allocated':
            assert payload['conversation_memory'][-1] == {'role':'user','content':answer}
            return CaseAllocation(scenarios=[dict(point_ids=[f'P-{i//2}'],
                variant=['普通账号','管理员账号'][i%2]) for i in range(4)])
        if stage == 'test_case.allocation_reviewed': return AllocationReview(supported=True,issues=[])
        return execute(stage, instruction, payload, result_type, model_id)
    result = GenerationPipeline(SimpleNamespace(name='real')).run(base_request(2), context={},
        answers={'case_allocation_conditions':answer},execute_stage=with_point_semantics(executor))
    assert len(result.test_cases) == 4 and result.quality.passed


def test_current_requirement_document_can_ground_variant():
    from casepilot_agent.case_allocation import validate_allocation
    allocation = CaseAllocation(scenarios=[dict(point_ids=['P-0'],variant='管理员账号')])
    assert validate_allocation(allocation, {'requested_case_count':1,'test_points':[{'id':'P-0'}],
        'prompt':'依据附件生成用例','source_excerpts':['登录支持普通账号和管理员账号']}) == allocation


def test_contradictory_clarification_cannot_be_cached_or_generated():
    from casepilot_agent.case_allocation import validate_allocation
    allocation = CaseAllocation(needs_clarification=True,clarification_question='需要补充条件',
        scenarios=[dict(point_ids=['P-0'],variant='普通账号')])
    with pytest.raises(StageContractError, match='invalid_clarification'):
        validate_allocation(allocation, {'requested_case_count':1,'test_points':[{'id':'P-0'}],
                                         'prompt':'普通账号'})


def test_subset_budget_and_scope_reach_allocation_together():
    req = base_request(1)
    req.prompt = '原来两个点四条，每个点有普通账号、管理员账号'
    scope = {'original_test_point_ids':['P-0','P-1'],'selected_test_point_ids':['P-0']}
    req.confirmed_plan['selection_context'] = scope
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'output_quantity.interpreted': return OutputQuantity(case_count=2)
        if stage == 'test_case.allocated':
            assert payload['requested_case_count'] == 2
            assert payload['selection_context'] == scope
            assert [p['id'] for p in payload['test_points']] == ['P-0']
            return CaseAllocation(scenarios=[dict(point_ids=['P-0'],variant=v)
                                             for v in ['普通账号','管理员账号']])
        if stage == 'test_case.allocation_reviewed': return AllocationReview(supported=True,issues=[])
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(req, executor)
    assert len(result.test_cases) == 2 and result.quality.passed
    assert all(c.test_point_ids == ['P-0'] for c in result.test_cases)


def test_confirmed_point_design_does_not_require_literal_user_phrase():
    from casepilot_agent.case_allocation import validate_allocation
    allocation = CaseAllocation(scenarios=[{
        'point_ids': ['P1'], 'variant': '输入为空后重新填写有效值',
        'basis': 'confirmed_point',
    }])
    assert validate_allocation(allocation, {
        'requested_case_count': 1, 'test_points': [{'id': 'P1'}],
        'prompt': '增加用例数量',
    }) is allocation


def test_designed_variant_still_requires_semantic_review():
    from casepilot_agent.pipeline import AwaitingInput
    reviews = []
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=2)
        if stage == 'test_case.allocated':
            return CaseAllocation(scenarios=[
                dict(point_ids=['P-0'], variant=f'编造锁定阈值{i}', basis='confirmed_point')
                for i in range(2)
            ])
        if stage == 'test_case.allocation_reviewed':
            reviews.append(payload)
            return AllocationReview(supported=False, issues=['编造了未声明的锁定阈值'])
        raise AssertionError('Unsupported designs must not reach generation')
    with pytest.raises(AwaitingInput):
        run(request(1), executor)
    assert len(reviews) == 2


def test_shared_reuse_source_allocates_missing_output_instead_of_underproducing():
    from casepilot_agent.providers.mock import MockProvider
    from casepilot_agent.contracts import GenerationRequest
    req = request(2)
    source = MockProvider().generate(GenerationRequest(prompt='登录')).test_cases[0].model_dump(mode='json')
    req.confirmed_plan['reuse'] = {'strategy': 'regression', 'decisions': [
        {'point_id': p['id'], 'point_snapshot': deepcopy(p), 'action': 'reuse', 'reason': '复用',
         'source': {'key': 'shared', 'label': '原用例', 'locator': '原集合', 'snapshot': source}}
        for p in req.confirmed_plan['test_points']]}
    def executor(stage, instruction, payload, result_type, model_id):
        if stage == 'output_quantity.interpreted':
            return OutputQuantity(case_count=2)
        if stage == 'test_case.allocated':
            assert len(payload['reuse_decisions']) == 1
            return CaseAllocation(scenarios=[
                dict(point_ids=['P-0'], source_point_id='P-0', variant='原有效账号'),
                dict(point_ids=['P-1'], variant='原第二点')])
        if stage == 'test_case.allocation_reviewed':
            return AllocationReview(supported=True, issues=[])
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(req, executor)
    assert result.quality.passed
    assert len(result.test_cases) == 2
