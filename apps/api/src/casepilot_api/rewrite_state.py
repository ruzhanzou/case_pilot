"""Deterministic draft reducer. Model replies are events, never execution authority."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from casepilot_api.rewrite_dialogue import RewriteReply, rewrite_transition

Phase = Literal['collecting', 'clarifying', 'preview', 'executing', 'cancelled']


@dataclass(frozen=True)
class DraftTransition:
    state: dict
    action: str
    phase: Phase
    confirmation: dict | None
    clarification: str = ''


def reduce_draft(state: dict, reply: RewriteReply, *, confirmation: dict | None,
                 selection_changed: bool = False) -> DraftTransition:
    """Preserve input, invalidate stale previews and merge only trusted updates."""
    state = deepcopy(state)
    action, clarification = rewrite_transition(
        state, reply, has_preview=bool(confirmation), selection_changed=selection_changed)
    if action == 'cancel':
        phase = 'cancelled'
        confirmation = None
    elif action == 'clarify':
        phase = 'clarifying'
        state['clarification'] = clarification
        confirmation = None
    elif action == 'confirm':
        phase = 'executing'
    else:
        phase = 'collecting'
        confirmation = None
        state.pop('clarification', None)
        if reply.scope_action == 'replace':
            state['scope_instruction'] = reply.scope_instruction
        if reply.scope_action == 'replace' or selection_changed:
            state['scope_resolved'] = False
        if reply.requirements.strip():
            state['requirements'] = reply.requirements
            state['requirements_ready'] = reply.requirements_ready
        elif not reply.requirements_ready:
            state['requirements_ready'] = False
        # A scope-only update must not invent readiness for missing requirements.
    state['phase'] = phase
    return DraftTransition(state, action, phase, deepcopy(confirmation), clarification)


def settle_draft(state: dict, *, scope_resolved: bool, confirmation: dict | None,
                 dispatched: bool, clarification: str = '') -> dict:
    """Reconcile the reducer with scope validation and dispatch results."""
    state = deepcopy(state)
    state['scope_resolved'] = scope_resolved
    if dispatched:
        state['phase'] = 'executing'
        state.pop('clarification', None)
    elif confirmation and scope_resolved:
        state['phase'] = 'preview'
        state.pop('clarification', None)
    else:
        state['phase'] = 'clarifying'
        if clarification:
            state['clarification'] = clarification
    return state


def routing_draft_context(payload: dict) -> dict:
    """Bounded current intent evidence, independent of truncated chat history.

    Asset bodies, attachments and arbitrary persisted payload fields are excluded.
    These strings are user data, never routing instructions.
    """
    draft = payload.get('rewrite_draft') or {}
    return {
        'instruction': str(payload.get('instruction') or '')[:8000],
        'rewrite_draft': {
            key: str(draft.get(key) or '')[:limit]
            for key, limit in (
                ('scope_instruction', 4000), ('requirements', 8000), ('clarification', 1000)
            )
        },
        'requirements_ready': bool(draft.get('requirements_ready')),
        'scope_resolved': bool(draft.get('scope_resolved')),
        'has_modification_preview': bool(payload.get('modification_confirmation')),
    }
