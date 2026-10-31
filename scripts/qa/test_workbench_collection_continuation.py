"""Offline adapter stop conditions; real claims/approvals covered by PG tests."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import workbench_agent_live_continuation as durable
import workbench_collection_continuation as bound
from workbench_agent_live_journey import JourneyFailure


@pytest.mark.asyncio
async def test_deadline_does_not_start_dispatch_or_executor():
    tasks = SimpleNamespace(dispatch_task_outbox=SimpleNamespace(run=Mock()))
    dispatch = durable.DurableDispatch("00000000-0000-0000-0000-000000000001")
    with pytest.raises(JourneyFailure, match="durable_wait_timeout"):
        await dispatch.drain(tasks, timeout_seconds=0)
    tasks.dispatch_task_outbox.run.assert_not_called()
    assert dispatch.executed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", [False, True])
async def test_no_queue_and_non_proposal_terminal_preserve_failed_status(monkeypatch, pending):
    class FakeBound:
        executed = 0
        def proposal_turn(self):
            return None
        def pending_delivery(self):
            return pending
        async def drain(self, tasks, *, timeout_seconds):
            assert timeout_seconds == 180
            self.executed += 1
        def enqueue(self, *a, **kw):
            raise AssertionError("no broker delivery in this unit test")

    dispatch = FakeBound()
    monkeypatch.setattr(bound, "BoundCollectionDispatch", lambda *a: dispatch)
    tasks = SimpleNamespace(celery_app=SimpleNamespace(send_task=Mock()))
    report = {}
    code = "durable_proposal_not_ready" if pending else "durable_no_deliverable_continuation"
    with pytest.raises(JourneyFailure, match=code):
        await bound.await_collection_proposal("synthetic", {}, tasks, report)
    assert dispatch.executed == int(pending)
    assert report["continuation_tasks_executed"] == int(pending)
    assert "passed" not in report
