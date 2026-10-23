from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from casepilot_agent import tasks
from casepilot_agent.store import generation_failure_message


@pytest.mark.parametrize('acquired', [False, True])
def test_guard_skips_duplicate_before_entering_job_body(monkeypatch, acquired):
    released = []

    @contextmanager
    def guard(job_id):
        try:
            yield acquired
        finally:
            released.append(job_id)

    monkeypatch.setattr(tasks, 'JobStore', lambda *_: SimpleNamespace(execution_guard=guard))
    body = Mock(return_value={'status': 'completed'})
    job_id = str(uuid4())
    result = tasks.guarded_job(body)(job_id)
    assert result['status'] == ('completed' if acquired else 'duplicate_ignored')
    assert body.call_count == int(acquired)
    assert released == [UUID(job_id)]


def test_execution_ownership_is_released_on_task_exception(monkeypatch):
    released = []

    @contextmanager
    def guard(job_id):
        try:
            yield True
        finally:
            released.append(job_id)

    monkeypatch.setattr(tasks, 'JobStore', lambda *_: SimpleNamespace(execution_guard=guard))
    body = Mock(side_effect=RuntimeError('provider failed'))
    with pytest.raises(RuntimeError, match='provider failed'):
        tasks.guarded_job(body)(str(uuid4()))
    assert len(released) == 1


def test_process_loss_explains_retry_without_claiming_results_lost():
    message = generation_failure_message('WorkerInterrupted', {})
    assert '进程意外中断' in message
    assert '已保留' in message and '重试' in message


@pytest.mark.parametrize(
    'status,expected_calls',
    [('queued', 1), ('running', 1), ('failed', 0), ('completed', 0), ('cancelled', 0)],
)
def test_early_provider_failure_closes_only_active_job(monkeypatch, status, expected_calls):
    from unittest.mock import MagicMock
    store = MagicMock()
    store.get_job.return_value = {'status': status}
    monkeypatch.setattr(tasks, 'JobStore', lambda *_: store)
    failure = Mock()
    monkeypatch.setattr(tasks, 'fail_job', failure)
    error = ValueError('provider initialization failed')
    body = Mock(side_effect=error)
    with pytest.raises(ValueError, match='initialization failed'):
        tasks.guarded_job(body)(str(uuid4()))
    assert failure.call_count == expected_calls
    if expected_calls:
        assert failure.call_args.args[-1] is error
