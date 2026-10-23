from types import SimpleNamespace
from uuid import uuid4

from casepilot_api.conversations import _brief_belongs_to_generation_task


def test_new_generation_does_not_merge_previously_completed_planning():
    prior = SimpleNamespace(id=uuid4(), payload={})
    current = SimpleNamespace(id=uuid4(), payload={})
    brief = SimpleNamespace(source_operation_id=prior.id, status='confirmed')
    assert not _brief_belongs_to_generation_task(brief, prior, current)


def test_revision_of_same_task_preserves_planning_even_across_operations():
    task_id = str(uuid4())
    prior = SimpleNamespace(id=uuid4(), payload={'task_id': task_id})
    current = SimpleNamespace(id=uuid4(), payload={'task_id': task_id})
    brief = SimpleNamespace(source_operation_id=prior.id, status='confirmed')
    assert _brief_belongs_to_generation_task(brief, prior, current)


def test_manual_draft_is_editable_but_confirmed_legacy_brief_is_not_new_scope():
    current = SimpleNamespace(id=uuid4(), payload={})
    brief = SimpleNamespace(source_operation_id=None, status='draft')
    assert _brief_belongs_to_generation_task(brief, None, current)
    brief.status = 'confirmed'
    assert not _brief_belongs_to_generation_task(brief, None, current)
