"""Read-only authorized projection: no events, budgets or tasks from polling."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_workbench_continuation_store import authority

from casepilot_api.database import get_session_factory
from casepilot_api.models import Conversation, TaskOutbox, WorkbenchContinuation, WorkbenchRun
from casepilot_api.workbench_run_projection import project_durable_state


@pytest.mark.asyncio
async def test_latest_progress_is_authoritative_read_only_and_history_is_bound():
    run_id, cid = await authority()
    foreign_run, _ = await authority()
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        run.status = "waiting_job"
        run.cursor = 1
        run.plan = {"steps": [{"action": "query", "status": "completed"},
                              {"action": "generate", "status": "pending"}]}
        run.used = {"segments": 1}
        db.commit()
    with get_session_factory()() as db:
        conversation = db.get(Conversation, cid)
        before = [db.scalar(select(func.count()).select_from(model))
                  for model in (WorkbenchContinuation, TaskOutbox)]
        state = {"status": "completed", "durable_run": {"id": str(run_id), "status": "old"}}
        original = deepcopy(state)
        for _ in range(3):
            projected = project_durable_state(db, conversation, state, latest=True)
            assert projected["durable_run"]["status"] == "waiting_job"
            assert projected["durable_run"]["cursor"] == 1
            assert projected["durable_run"]["used"] == {"segments": 1}
        assert state == original
        for identifier in (str(foreign_run), str(uuid4()), "invalid"):
            assert "durable_run" not in project_durable_state(
                db, conversation, {"durable_run": {"id": identifier}})
        assert [db.scalar(select(func.count()).select_from(model))
                for model in (WorkbenchContinuation, TaskOutbox)] == before
        assert not db.dirty and not db.new


@pytest.mark.asyncio
async def test_resumed_goal_wins_over_later_completed_read_question():
    run_id, cid = await authority()
    with get_session_factory()() as db:
        original = db.get(WorkbenchRun, run_id)
        original.status = "waiting_approval"
        question = WorkbenchRun(
            conversation_id=cid, account_id=original.account_id, space_id=original.space_id,
            root_message_id=original.root_message_id, request_id=uuid4(), status="completed",
            epoch=1, cursor=1, plan={}, binding={}, checkpoint={}, budget={}, used={},
        )
        db.add(question)
        db.commit()
        conversation = db.get(Conversation, cid)
        current = project_durable_state(db, conversation, {}, latest=True)
        assert current["durable_run"]["id"] == str(run_id)
        assert current["durable_run"]["status"] == "waiting_approval"
        historical = project_durable_state(
            db, conversation, {"durable_run": {"id": str(question.id)}})
        assert historical["durable_run"]["id"] == str(question.id)
        assert historical["durable_run"]["status"] == "completed"
