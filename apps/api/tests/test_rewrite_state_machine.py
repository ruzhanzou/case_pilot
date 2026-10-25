"""Execution invariants across reply events and persisted draft states."""
from itertools import product

import pytest

from casepilot_api.rewrite_dialogue import RewriteReply, rewrite_transition


@pytest.mark.parametrize('preview,scope,ready,requirements,clarification,changed',
                         list(product([False, True], repeat=6)))
def test_confirmation_requires_complete_unchanged_draft(
        preview, scope, ready, requirements, clarification, changed):
    state = dict(scope_resolved=scope, requirements_ready=ready,
                 requirements='步骤清晰' if requirements else '',
                 clarification='请选择范围' if clarification else '')
    action, _ = rewrite_transition(state, RewriteReply(action='confirm'),
                                   has_preview=preview, selection_changed=changed)
    assert (action == 'confirm') == (
        preview and scope and ready and requirements and not clarification and not changed)


@pytest.mark.parametrize('action', ['confirm', 'cancel', 'update', 'clarify'])
def test_uncertain_intents_never_execute_or_cancel(action):
    state = dict(scope_resolved=True, requirements_ready=True, requirements='步骤清晰')
    assert rewrite_transition(state, RewriteReply(action=action, confidence=.84),
                              has_preview=True, selection_changed=False)[0] == 'clarify'


def test_update_requires_new_preview_and_does_not_mutate_state():
    state = dict(scope_resolved=True, requirements_ready=True, requirements='步骤清晰')
    before = dict(state)
    assert rewrite_transition(state, RewriteReply(action='update', requirements='保留标题'),
                              has_preview=True, selection_changed=False)[0] == 'update'
    assert state == before


def test_scope_only_update_preserves_missing_requirements():
    from casepilot_api.rewrite_state import reduce_draft
    result = reduce_draft(dict(requirements='', requirements_ready=False, scope_resolved=True),
                          RewriteReply(action='update', scope_action='replace',
                                       scope_instruction='前两条'), confirmation=None)
    assert not result.state['requirements_ready']
    assert not result.state['scope_resolved']
    assert result.phase == 'collecting'


def test_clarification_preserves_draft_and_invalidates_preview():
    from casepilot_api.rewrite_state import reduce_draft
    state = dict(requirements='不改标题', requirements_ready=True, scope_resolved=True)
    result = reduce_draft(state, RewriteReply(action='update', confidence=.5,
                                             requirements='修改标题'),
                          confirmation={'instruction': '不改标题'})
    assert result.state['requirements'] == '不改标题'
    assert result.confirmation is None
    assert result.phase == 'clarifying'
    assert 'phase' not in state


def test_failed_scope_cannot_leave_preview_phase():
    from casepilot_api.rewrite_state import settle_draft
    state = settle_draft({'phase': 'preview'}, scope_resolved=False,
                         confirmation=None, dispatched=False, clarification='数量不一致')
    assert state['phase'] == 'clarifying'
    assert state['clarification'] == '数量不一致'


def test_routing_context_keeps_current_draft_without_asset_bodies():
    from casepilot_api.rewrite_state import routing_draft_context
    context = routing_draft_context({
        'instruction': '修改优先级',
        'rewrite_draft': {'requirements': '优先级P1，标题不变',
                          'scope_instruction': '登录模块前两条',
                          'clarification': '请指定优先级',
                          'requirements_ready': False, 'scope_resolved': True},
        'modification_confirmation': {'cases': [{'snapshot': {'steps': 'PRIVATE BODY'}}]},
        'attachment_context': {'body': 'PRIVATE ATTACHMENT'},
    })
    assert context['rewrite_draft']['requirements'] == '优先级P1，标题不变'
    assert context['rewrite_draft']['clarification'] == '请指定优先级'
    assert context['scope_resolved']
    assert not context['requirements_ready']
    assert 'PRIVATE' not in str(context)


def test_legacy_routing_context_and_limits():
    from casepilot_api.rewrite_state import routing_draft_context
    context = routing_draft_context({'instruction': 'x' * 9000, 'rewrite_draft': None})
    assert len(context['instruction']) == 8000
    assert context['rewrite_draft']['clarification'] == ''
    assert not context['has_modification_preview']
