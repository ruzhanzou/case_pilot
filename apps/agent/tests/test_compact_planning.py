from copy import deepcopy

import pytest
from test_parallel_planning import features, points

from casepilot_agent.contracts import FeaturePlan, RequirementAnalysis, SourceRef
from casepilot_agent.planning import (
    PlanningAnalysis,
    build_planning,
    compact_planning_context,
)
from casepilot_agent.providers.mock import MockProvider


def test_fused_analysis_reuses_features_and_reduces_point_input_without_losing_sources():
    evidence, plans = [], []
    for i in range(32):
        quote = 'RULE-1: 连续5次错误锁定15分钟。'
        source = {'document_id': 'doc', 'chunk_id': str(i), 'label': '登录',
                  'excerpt': '样例数据' * 2000 + quote + '管理员除外。' + '样例数据' * 2000}
        evidence.append(source)
        feature = features(1).feature_points[0]
        feature.name = 'RULE-1 连续5次错误锁定15分钟'
        feature.module = '登录' if i % 2 else '账户/登录'
        feature.requirement_refs = ['RULE-1']
        feature.source_refs = [SourceRef(**{**source, 'excerpt': quote})]
        plans.append(FeaturePlan(feature_points=[feature]))
    original = deepcopy(evidence)
    calls = []

    def complete(stage, instruction, payload, result_type):
        assert stage == 'test_point.generated'
        calls.append(payload)
        return points(payload)

    requirement = RequirementAnalysis(summary='登录', business_rules=['管理员除外'])
    result = build_planning(requirement, {'evidence': evidence}, complete,
                            [requirement] * 32, feature_plans=plans, target_count=1)
    assert len(calls) == 1
    assert [s["excerpt"] for s in calls[0]["source_catalog"]] == [
        e["excerpt"] for e in calls[0]["context"]["evidence"]
    ]  # Point choices expose only compacted, actually shown evidence.
    assert len(result['feature_points']) == len(result['test_points']) == 1
    excerpts = calls[0]['context']['evidence']
    assert sum(len(s['excerpt']) for s in excerpts) < sum(len(s['excerpt']) for s in evidence) / 20
    assert all('管理员除外' in s['excerpt'] for s in excerpts)
    assert len(result['test_points'][0]['source_refs']) == 32
    assert result['evidence'] == evidence == original


@pytest.mark.parametrize('quote,document', [
    ('模型编造的未出现规则', 'doc'), ('规则原文必须保留', 'foreign'),
])
def test_unverified_quote_or_source_falls_back_to_original(quote, document):
    common = {'requirement': {}, 'context': {'evidence': [
        {'document_id': 'doc', 'label': '来源', 'excerpt': '规则原文必须保留'},
    ]}}
    feature = features(1).feature_points[0]
    feature.source_refs = [SourceRef(document_id=document, label='来源', excerpt=quote)]
    assert compact_planning_context(common, [feature]) is common


def test_terminal_punctuation_is_tolerated_but_unverified_exception_keeps_full_context():
    source = {'document_id': 'doc', 'label': '来源',
              'excerpt': 'x' * 1000 + 'RULE-1： 错误密码拒绝登录。管理员账户除外。' + 'y' * 1000}
    common = {'requirement': {}, 'context': {'evidence': [source]}}
    feature = features(1).feature_points[0]
    feature.source_refs = [SourceRef(document_id='doc', label='来源',
                                     excerpt='RULE-1: 错误密码拒绝登录.')]
    compact = compact_planning_context(common, [feature])
    assert compact is not common
    assert '管理员账户除外。' in compact['context']['evidence'][0]['excerpt']
    feature.source_refs.append(
        SourceRef(document_id='doc', label='来源', excerpt='未能逐字匹配的例外'))
    assert compact_planning_context(common, [feature]) is common


def test_missing_fused_features_fall_back_only_for_that_batch():
    context = {'evidence': [{'label': str(i), 'excerpt': str(i) * 18000} for i in range(2)]}
    plans = [features(1), FeaturePlan(feature_points=[])]
    calls = []

    def complete(stage, instruction, payload, result_type):
        if stage == 'feature.generated':
            calls.append(payload['context']['evidence'][0]['label'])
            result = features(1)
            result.feature_points[0].name = '其他功能'
            return result
        return points(payload)

    result = build_planning(RequirementAnalysis(summary='登录'), context, complete,
                            feature_plans=plans)
    assert calls == ['1']
    assert len(result['feature_points']) == 2


@pytest.mark.parametrize('conflict', [False, True])
def test_same_rule_label_does_not_merge_different_documents_or_conflicting_definitions(conflict):
    evidence, plans = [], []
    for i in range(2):
        definition = '连续5次错误锁定15分钟' if not conflict or i == 0 else '连续3次错误锁定10分钟'
        quote = f'RULE-1: {definition}。'
        source = {'document_id': 'doc' if conflict else f'doc{i}', 'chunk_id': str(i),
                  'label': str(i), 'excerpt': quote + 'x' * (18000 - len(quote))}
        evidence.append(source)
        feature = features(1).feature_points[0]
        feature.module = f'模块{i}'
        feature.requirement_refs = ['RULE-1']
        feature.source_refs = [SourceRef(**{**source, 'excerpt': quote})]
        plans.append(FeaturePlan(feature_points=[feature]))

    def complete(stage, instruction, payload, result_type):
        assert stage == 'test_point.generated'
        return points(payload)

    result = build_planning(RequirementAnalysis(summary='账户'), {'evidence': evidence},
                            complete, feature_plans=plans)
    assert len(result['feature_points']) == 2
    assert {f['module'] for f in result['feature_points']} == {'模块0', '模块1'}


def test_mock_supports_fused_analysis_contract():
    result, _ = MockProvider().complete(stage='requirement.analyzed', instruction='',
                                      payload={'prompt': '登录'}, result_type=PlanningAnalysis,
                                      model_id='auto')
    assert isinstance(result, PlanningAnalysis)
    assert result.feature_points


def test_fused_analysis_is_checkpointed_and_reused_on_retry(monkeypatch):
    from test_draft_planning_progress import Store

    from casepilot_agent import tasks
    from casepilot_agent.contracts import UsageMetadata

    store = Store()
    context = {'evidence': [{'label': str(i), 'excerpt': str(i) * 18000} for i in range(2)]}
    calls = []
    fail = True

    class Provider:
        def complete(self, *, stage, payload, result_type, **kwargs):
            if stage == "output_quantity.interpreted":
                from casepilot_agent.quantity import OutputQuantity
                return OutputQuantity(), UsageMetadata(model="fixture")
            calls.append(stage)
            if stage == 'requirement.extracted':
                assert issubclass(result_type, PlanningAnalysis)
                assert result_type.__name__ == "SourceScopedPlanningAnalysis"
                index = payload['context']['evidence'][0]['label']
                feature = features(1).feature_points[0]
                feature.name = f'功能{index}'
                result = PlanningAnalysis(summary='登录', test_object='登录',
                                          test_object_specified=True, feature_points=[feature])
            else:
                assert stage == 'test_point.generated'
                assert 'feature_points' not in payload['requirement']
                if fail:
                    raise ValueError('temporary_failure')
                result = points(payload)
            return result, UsageMetadata(model='mock')

    monkeypatch.setattr(tasks, 'JobStore', lambda *args: store)
    monkeypatch.setattr(tasks, 'create_provider', lambda *args: Provider())
    monkeypatch.setattr(tasks, 'create_embedding_provider', lambda: None)
    monkeypatch.setattr(tasks, '_context_payload', lambda *args, **kwargs: context)
    with pytest.raises(ValueError, match='temporary_failure'):
        tasks.draft_test_brief(str(store.job['id']))
    fail = False
    tasks.draft_test_brief(str(store.job['id']))
    assert calls.count('requirement.extracted') == 2
    assert 'feature.generated' not in calls
    assert store.job['status'] == 'completed'
    assert len(store.briefs[0]['planning']['feature_points']) == 2


def test_global_rule_definition_canonicalizes_name_missing_from_local_slice():
    quote = 'REFUND-2: 退款金额不得超过实付金额。'
    evidence = [
        {'document_id': 'doc', 'chunk_id': 'a', 'label': '退款',
         'excerpt': quote + 'x' * 18000},
        {'document_id': 'doc', 'chunk_id': 'b', 'label': '退款', 'excerpt': '续页样例'},
    ]
    from casepilot_agent.planning import evidence_batches
    plans = []
    for i, batch in enumerate(evidence_batches({'evidence': evidence})):
        feature = features(1).feature_points[0]
        feature.name = ('REFUND-2 退款金额不得超过实付金额' if i == 0
                        else 'REFUND-2: 退款金额不得超过实付金额')
        feature.module = '退款'
        feature.requirement_refs = ['REFUND-2']
        feature.source_refs = [SourceRef(**{**batch['evidence'][0], 'excerpt': quote})]
        plans.append(FeaturePlan(feature_points=[feature]))
    result = build_planning(RequirementAnalysis(summary='退款'), {'evidence': evidence},
                            lambda stage, instruction, payload, result_type: points(payload),
                            feature_plans=plans, target_count=1)
    assert len(result['feature_points']) == len(result['test_points']) == 1


def test_truncated_sample_is_not_a_conflicting_rule_definition():
    from casepilot_agent.planning import source_rule_name
    feature = features(1).feature_points[0]
    feature.requirement_refs = ['REFUND-2']
    context = {'evidence': [{'excerpt':
        'REFUND-2: 退款金额不得超过实付金额。\n'
        '样例适用规则REFUND-2：退款金额不得超过实付金\n本章末尾规则复核：\n'}]}
    assert source_rule_name(feature, context) == 'REFUND-2 退款金额不得超过实付金额'
    context['evidence'].append({'excerpt': 'REFUND-2: 退款金额不得超过100元。'})
    assert source_rule_name(feature, context) is None


def test_server_full_reference_does_not_compact_away_distant_explicit_exception():
    text = 'RULE-1： 连续5次错误锁定15分钟。' + '样例数据' * 150 + '管理员账户除外。'
    source = {'source_id': 's', 'document_id': 'd', 'chunk_id': 'c',
              'label': '原始规则', 'locator': 'page 1', 'excerpt': text}
    common = {'requirement': {}, 'context': {'evidence': [source]}}
    feature = features(1).feature_points[0]
    feature.requirement_refs = ['RULE-1']
    feature.source_refs = [SourceRef.model_validate(source)]
    result = compact_planning_context(common, [feature])
    assert result is common
    assert '管理员账户除外。' in result['context']['evidence'][0]['excerpt']


@pytest.mark.parametrize('remote', [
    'Administrators are exempt', '除非管理员授权', '每日最多3次', '另一条完整规则。',
])
def test_canonical_rule_compaction_conservatively_retains_remote_qualifications(remote):
    text = 'RULE-1： 正常流程允许。' + '样例数据' * 150 + remote
    source = {'label': '规则', 'document_id': 'd', 'chunk_id': 'c', 'excerpt': text}
    common = {'requirement': {}, 'context': {'evidence': [source]}}
    feature = features(1).feature_points[0]
    feature.requirement_refs = ['RULE-1']
    feature.source_refs = [SourceRef.model_validate(source)]
    assert compact_planning_context(common, [feature]) is common
