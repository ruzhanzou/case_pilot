from unittest.mock import Mock
from uuid import uuid4
from casepilot_agent.store import JobStore


def test_subset_rewrite_keeps_other_pending_cases_and_advances_one_version():
    first = {'ref': 'one', 'proposal_version': 2, 'proposed_snapshot': {'title': 'Old draft'}, 'field_diff': [{'field': 'title'}], 'status': 'ready'}
    other = {'ref': 'two', 'proposal_version': 1, 'proposed_snapshot': {'priority': 'P0'}, 'field_diff': [{'field': 'priority'}], 'status': 'ready'}
    updated = {**first, 'proposed_snapshot': {'title': 'Final draft'}}
    connection = Mock()
    connection.execute.return_value.rowcount = 0
    job = {'input_payload': {'change_set_id': str(uuid4()), 'previous_change_set_id': str(uuid4()),
        'conversation_id': str(uuid4()), 'previous_proposals': {'one': first, 'two': other}}}
    JobStore.persist_change_set(None, connection, job=job, items=[updated])
    saved = connection.execute.call_args_list[0].args[0].compile().params['items']
    assert [item['ref'] for item in saved] == ['one', 'two']
    assert [item['proposal_version'] for item in saved] == [3, 3]
    assert saved[1]['proposed_snapshot'] == {'priority': 'P0'}
    assert saved[1]['previous_snapshot'] == {'priority': 'P0'}
    assert other['proposal_version'] == 1


def test_rewrite_snapshot_preserves_actual_base_version():
    connection = Mock()
    row = dict(case_key='QA-1', revision_number=2, title='Saved title', module='Login', case_type='功能',
        priority='P1', tags=[], preconditions=['Account exists'], steps=[{'action':'Login','expected':'Success'}], source_refs=[])
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = row
    snapshot = JobStore.load_case_snapshot(None, connection, uuid4(), uuid4())
    assert snapshot['revision_number'] == 2
    assert snapshot['case_key'] == 'QA-1'


def test_cancelled_batch_stops_before_next_model_call_and_keeps_cancelled_state(monkeypatch):
    from unittest.mock import MagicMock
    from casepilot_agent import tasks
    store = Mock()
    store.connection.return_value = MagicMock()
    store.claim_job.return_value = {'input_payload': {'instruction': '改写', 'candidate_targets': [{'ref': 'one'}]}}
    monkeypatch.setattr(tasks, 'JobStore', lambda *args: store)
    provider = Mock()
    monkeypatch.setattr(tasks, 'create_provider', lambda *args: provider)
    monkeypatch.setattr(tasks, 'ensure_not_cancelled', Mock(side_effect=tasks.GenerationCancelled('cancelled')))
    failure = Mock()
    monkeypatch.setattr(tasks, 'fail_job', failure)
    result = tasks.rewrite_test_cases_batch(str(uuid4()))
    assert result['status'] == 'cancelled'
    provider.rewrite.assert_not_called()
    failure.assert_not_called()
    store.persist_change_set.assert_not_called()
