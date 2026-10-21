from copy import deepcopy

import pytest

from casepilot_agent.planning import PlanningAnalysis, reconcile_planning


def plan(prefix, count):
    return {
        'feature_points': [{'id': f'F-{prefix}', 'name': prefix}],
        'test_points': [{'id': f'{prefix}-{i}', 'title': f'{prefix} {i}',
                         'feature_point_ids': [f'F-{prefix}'], 'source_refs': [{'label': prefix}]}
                        for i in range(count)],
        'evidence': [{'label': prefix}],
    }


def analysis(**kwargs):
    return PlanningAnalysis(summary='登录', **kwargs)


def test_successive_additions_preserve_all_original_points_and_sources():
    original = plan('login', 18)
    baseline = deepcopy(original)
    added = plan('stability', 3)
    second = reconcile_planning(original, added, [analysis()])
    third = reconcile_planning(second, plan('security', 2), [analysis()])
    assert len(second['test_points']) == 21
    assert len(third['test_points']) == 23
    assert third['test_points'][:18] == original['test_points']
    assert original == baseline
    assert len(added['test_points']) == 3
    assert reconcile_planning(second, added, [analysis()]) == second


def test_explicit_point_revision_preserves_other_points():
    original = plan('login', 3)
    result = reconcile_planning(original, plan('replacement', 1),
                                [analysis(superseded_test_point_ids=['login-1'])])
    assert [p['id'] for p in result['test_points']] == ['login-0', 'login-2', 'replacement-0']


def test_explicit_feature_removal_and_full_replacement():
    original = reconcile_planning(plan('login', 18), plan('stability', 3), [analysis()])
    result = reconcile_planning(original, plan('new-login', 2),
                                [analysis(superseded_feature_ids=['F-login'])])
    assert len(result['test_points']) == 5
    assert 'F-login' not in [f['id'] for f in result['feature_points']]
    fresh = plan('fresh', 1)
    assert reconcile_planning(original, fresh, [analysis(planning_update_mode='replace')]) == fresh


def test_reject_unknown_deletions_and_broken_links():
    with pytest.raises(ValueError, match='unknown prior IDs'):
        reconcile_planning(plan('login', 18), plan('new', 1),
                           [analysis(superseded_test_point_ids=['invented'])])
    incoming = plan('new', 1)
    incoming['test_points'][0]['feature_point_ids'] = ['missing']
    with pytest.raises(ValueError, match='dangling'):
        reconcile_planning(plan('login', 18), incoming, [analysis()])


def test_task_persists_and_previews_incremental_plan(monkeypatch):
    from test_draft_planning_progress import Store
    from test_parallel_planning import features, points

    from casepilot_agent import tasks
    from casepilot_agent.contracts import UsageMetadata

    store = Store()
    previous = plan('original', 18)
    store.job['input_payload']['current_test_brief'] = {'planning': previous}
    store.job['input_payload']['prompt'] = '增加稳定性测试'

    class Provider:
        def complete(self, *, stage, payload, **kwargs):
            if stage == 'requirement.analyzed':
                result = PlanningAnalysis(summary='登录稳定性', test_object='登录',
                                          test_object_specified=True,
                                          feature_points=features(6).feature_points)
            else:
                result = points(payload)
            return result, UsageMetadata(model='mock')

    monkeypatch.setattr(tasks, 'JobStore', lambda *args: store)
    monkeypatch.setattr(tasks, 'create_provider', lambda *args: Provider())
    monkeypatch.setattr(tasks, 'create_embedding_provider', lambda: None)
    monkeypatch.setattr(tasks, '_context_payload', lambda *args, **kwargs: {'evidence': []})
    tasks.draft_test_brief(str(store.job['id']))
    assert store.briefs[0]['planning']['test_points'][:18] == previous['test_points']
    previews = [e['planning_preview']['planning'] for e in store.events
                if e.get('planning_preview', {}).get('planning')]
    assert previews
    assert all(p['test_points'][:18] == previous['test_points'] for p in previews)


def test_deletion_only_revision_does_not_regenerate_unrelated_features():
    from casepilot_agent.contracts import FeaturePlan, RequirementAnalysis
    from casepilot_agent.planning import build_planning

    def forbidden(*args):
        raise AssertionError('Deletion-only update must not regenerate original features')

    delta = build_planning(RequirementAnalysis(summary='删除指定测试点'), {'evidence': []},
                           forbidden, feature_plans=[FeaturePlan(feature_points=[])],
                           allow_empty=True)
    result = reconcile_planning(plan('login', 3), delta,
                                [analysis(superseded_test_point_ids=['login-1'])])
    assert [p['id'] for p in result['test_points']] == ['login-0', 'login-2']


def test_successive_point_edits_keep_untouched_points_and_accept_current_ids():
    initial = plan('login', 18)
    v2 = reconcile_planning(initial, plan('stability', 3), [analysis()])
    v3 = reconcile_planning(v2, plan('edited', 1),
                           [analysis(superseded_test_point_ids=['stability-1'])])
    v4 = reconcile_planning(v3, plan('edited-again', 1),
                           [analysis(superseded_test_point_ids=['edited-0'])])
    assert len(v4['test_points']) == 21
    assert v4['test_points'][:18] == initial['test_points']
    assert {'stability-0', 'stability-2', 'edited-again-0'} <= {
        p['id'] for p in v4['test_points']}
    assert 'edited-0' not in {p['id'] for p in v4['test_points']}


@pytest.mark.parametrize('prompt,count', [
    ('登录测试规划增加2个安全测试点', 2),
    ('修改指定测试点，仅替换为1个测试点', 1),
    ('增加稳定性测试，持续运行2小时', None),
])
def test_explicit_point_quantity_is_a_revision_budget(prompt, count):
    from casepilot_agent.planning import requested_point_count
    assert requested_point_count(prompt) == count
