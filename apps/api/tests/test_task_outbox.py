from unittest.mock import Mock
from uuid import uuid4

from casepilot_api.models import TaskOutbox
from casepilot_api.task_outbox import enqueue_task


def test_enqueue_task_uses_the_callers_transaction() -> None:
    session = Mock()
    job_id = uuid4()

    enqueue_task(session, "casepilot.agent.generate", [str(job_id)], task_id=job_id)

    outbox = session.add.call_args.args[0]
    assert isinstance(outbox, TaskOutbox)
    assert outbox.task_name == "casepilot.agent.generate"
    assert outbox.task_args == [str(job_id)]
    assert outbox.task_id == str(job_id)
