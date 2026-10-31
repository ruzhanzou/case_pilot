"""Real PostgreSQL durability/claim tests; no provider or broker calls."""
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    Conversation,
    ConversationMessage,
    GenerationJob,
    TaskOutbox,
    WorkbenchContinuation,
    WorkbenchRun,
)
from casepilot_api.workbench_continuation import (
    TASK_NAME,
    cancel_run,
    capture_approval_binding,
    claim_event,
    complete_event,
    create_run,
    enqueue_event,
    invalidate_runs,
    record_approval,
    recover_claim,
    reserve_budget,
)


async def authority():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, conversation = await setup(client)
    with get_session_factory()() as db:
        owner = db.get(Account, UUID(account["id"]))
        convo = db.get(Conversation, UUID(conversation["id"]))
        message = ConversationMessage(conversation_id=convo.id, role="user",
            content="Generate, review, then verify the exact approved result", status="completed",
            target_case_ids=[], citations=[], message_metadata={})
        db.add(message)
        db.flush()
        run = create_run(db, owner, convo, message.id, uuid4())
        db.commit()
        return run.id, convo.id


@pytest.mark.asyncio
async def test_unique_event_outbox_and_rollback_and_short_claim_receipt():
    run_id, _ = await authority()
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        event = enqueue_event(db, run, "job_completed", "job-one", "completed:1")
        again = enqueue_event(db, run, "job_completed", "job-one", "completed:1")
        assert event.id == again.id
        event_id = event.id
        db.commit()
    with get_session_factory()() as db:
        assert len(list(db.scalars(select(TaskOutbox).where(
            TaskOutbox.task_id == str(event_id))))) == 1
        rolled = enqueue_event(db, db.get(WorkbenchRun, run_id), "job_completed", "rolled", "1")
        rolled_id = rolled.id
        db.rollback()
    with get_session_factory()() as db:
        assert db.get(WorkbenchContinuation, rolled_id) is None
        assert db.scalar(select(TaskOutbox.id).where(TaskOutbox.task_id == str(rolled_id))) is None
        run, event, token = claim_event(db, event_id)
        assert reserve_budget(db, run.id, {"segments": 1, "model_turns": 2})
        db.commit()
    with get_session_factory()() as db:
        assert claim_event(db, event_id) is None
        complete_event(db, event_id, token, {"verified": True}, status="completed")
        db.commit()
    with get_session_factory()() as db:
        assert complete_event(db, event_id, token, {"ignored": True}).receipt == {"verified": True}
        assert db.get(WorkbenchRun, run_id).used == {"segments": 1, "model_turns": 2}
        assert db.get(WorkbenchRun, run_id).cursor == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cancel", "instruction", "selection", "budget"])
async def test_cancel_new_instruction_binding_change_and_budget_fail_closed(reason):
    run_id, cid = await authority()
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        event_id = enqueue_event(db, run, "job_completed", "one", "1").id
        if reason == "cancel":
            cancel_run(db, run_id)
        elif reason == "instruction":
            assert invalidate_runs(db, cid) == 1
        elif reason == "selection":
            conversation = db.get(Conversation, cid)
            conversation.context = {**conversation.context,
                                    "workbench_selection": {"version": 1, "items": []}}
        else:
            assert not reserve_budget(db, run_id, {"segments": 9})
        db.commit()
    with get_session_factory()() as db:
        assert claim_event(db, event_id) is None
        assert db.get(WorkbenchRun, run_id).used == {}
        db.commit()


@pytest.mark.asyncio
async def test_crash_claim_recovery_does_not_refund_budget_and_old_token_fails():
    from fastapi import HTTPException

    run_id, _ = await authority()
    with get_session_factory()() as db:
        event_id = enqueue_event(db, db.get(WorkbenchRun, run_id), "job_completed", "one", "1").id
        _, _, old_token = claim_event(db, event_id)
        assert reserve_budget(db, run_id, {"segments": 1})
        db.commit()
    # The real executor must acquire its advisory run guard before this helper.
    with get_session_factory()() as db:
        assert recover_claim(db, event_id)
        _, _, token = claim_event(db, event_id)
        assert token != old_token
        with pytest.raises(HTTPException, match="workbench_continuation_obsolete"):
            complete_event(db, event_id, old_token, {})
        assert db.get(WorkbenchRun, run_id).used == {"segments": 1}
        db.commit()


@pytest.mark.asyncio
async def test_partial_approval_does_not_advance_or_mask_final_same_version():
    run_id, cid = await authority()
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        run.checkpoint = {"waiting_artifact_kind": "change_set", "waiting_artifact_id": "diff",
                          "waiting_artifact_version": "2"}
        conversation = db.get(Conversation, cid)
        token = capture_approval_binding(db, conversation, "change_set", "diff", "2")
        partial = record_approval(db, conversation, "change_set", "diff", "2",
                                  complete=False, preapproval_binding=token)
        assert partial.status == "completed"
        assert run.cursor == 0
        assert record_approval(db, conversation, "change_set", "diff", "2",
                               complete=False, preapproval_binding=token).id == partial.id
        assert run.binding["selection_version"] == 0
        final = record_approval(db, conversation, "change_set", "diff", "2",
                                preapproval_binding=token)
        assert final.id != partial.id
        assert final.status == "pending"
        replay = record_approval(db, conversation, "change_set", "diff", "2",
                                 preapproval_binding=token)
        assert replay.id == final.id
        assert record_approval(db, db.get(Conversation, cid), "change_set", "foreign", "2") is None
        db.commit()


@pytest.mark.asyncio
async def test_real_worker_terminal_update_emits_once_atomically_and_rollback_removes_event():
    from casepilot_agent.store import JobStore
    from casepilot_agent.tasks import settings

    run_id, cid = await authority()
    job_id = uuid4()
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        run.checkpoint = {"waiting_job_id": str(job_id)}
        run.status = "waiting_job"
        db.add(GenerationJob(id=job_id, space_id=run.space_id, account_id=run.account_id,
            collection_id=db.get(Conversation, cid).collection_id,
            operation="draft_brief", status="running", stage="planning",
            input_payload={"conversation_id": str(cid), "workbench_run_id": str(run.id),
                "workbench_epoch": run.epoch, "workbench_cursor": run.cursor}))
        db.commit()
    store = JobStore(settings.database_url, settings.redis_url)
    with pytest.raises(RuntimeError, match="rollback"), store.connection() as connection:
        store.update_job(connection, job_id, status="completed", stage="completed")
        raise RuntimeError("rollback")
    with get_session_factory()() as db:
        assert db.get(GenerationJob, job_id).status == "running"
        assert db.scalar(select(WorkbenchContinuation.id).where(
            WorkbenchContinuation.run_id == run_id)) is None
    with store.connection() as connection:
        store.update_job(connection, job_id, status="completed", stage="completed")
        store.update_job(connection, job_id, status="completed", stage="completed")
    with get_session_factory()() as db:
        events = list(db.scalars(select(WorkbenchContinuation).where(
            WorkbenchContinuation.run_id == run_id)))
        assert len(events) == 1
        assert events[0].payload == {"job_id": str(job_id), "status": "completed",
                                     "operation": "draft_brief"}
        assert len(list(db.scalars(select(TaskOutbox).where(
            TaskOutbox.task_name == TASK_NAME, TaskOutbox.task_id == str(events[0].id))))) == 1
        # User may approve before the continuation queue observes completion.
        conversation = db.get(Conversation, cid)
        token = capture_approval_binding(db, conversation, "candidates", job_id, job_id)
        approval = record_approval(db, conversation, "candidates",
                                   str(job_id), str(job_id), preapproval_binding=token)
        assert approval is not None and approval.status == "pending"
        db.flush()
        assert db.get(WorkbenchContinuation, events[0].id).status == "invalidated"
        assert claim_event(db, events[0].id) is None
        assert claim_event(db, approval.id) is not None
        db.commit()


@pytest.mark.asyncio
async def test_initial_reservation_survives_outer_rollback_and_retries_do_not_reset_budget():
    from fastapi import HTTPException

    from casepilot_api.models import WorkbenchReservation
    from casepilot_api.workbench_continuation import reserve_initial_segment

    run_id, cid = await authority()
    request_id = uuid4()
    with get_session_factory()() as outer:
        run = outer.get(WorkbenchRun, run_id)
        conversation = outer.get(Conversation, cid)
        outer.refresh(conversation, with_for_update=True)
        owner_id = run.account_id
        reserved = reserve_initial_segment(get_session_factory(), owner_id, cid, request_id,
                                           {"segments": 1}, {"segments": 2})
        assert reserved["used"] == {"segments": 1}
        # The ledger did not wait on the outer conversation row or commit it.
        conversation.title = "Must roll back"
        outer.rollback()
    with get_session_factory()() as db:
        assert db.get(Conversation, cid).title != "Must roll back"
        assert db.get(WorkbenchReservation, (owner_id, cid, request_id)).used == {"segments": 1}
    second = reserve_initial_segment(get_session_factory(), owner_id, cid, request_id,
                                     {"segments": 1}, {"segments": 2})
    assert second["used"] == {"segments": 2}
    with pytest.raises(HTTPException, match="workbench_budget_exhausted"):
        reserve_initial_segment(get_session_factory(), owner_id, cid, request_id,
                                {"segments": 1}, {"segments": 2})


@pytest.mark.asyncio
async def test_approval_launch_tags_next_job_and_does_not_schedule_model_early():
    run_id, cid = await authority()
    job_id = uuid4()
    with get_session_factory()() as db:
        run, conversation = db.get(WorkbenchRun, run_id), db.get(Conversation, cid)
        run.checkpoint = {"waiting_artifact_kind": "brief", "waiting_artifact_id": "brief-one",
                          "waiting_artifact_version": 3}
        job = GenerationJob(id=job_id, space_id=run.space_id, account_id=run.account_id,
            collection_id=conversation.collection_id, operation="generate", status="queued",
            stage="queued", input_payload={"conversation_id": str(cid)})
        db.add(job)
        db.flush()
        token = capture_approval_binding(db, conversation, "brief", "brief-one", "3")
        event = record_approval(db, conversation, "brief", "brief-one", "3", next_job_id=job_id,
                               preapproval_binding=token)
        assert event.status == "completed"
        assert job.input_payload["workbench_run_id"] == str(run_id)
        assert job.input_payload["workbench_cursor"] == run.cursor
        assert run.checkpoint["waiting_job_id"] == str(job_id)
        assert run.status == "waiting_job"
        assert db.scalar(select(TaskOutbox.status).where(TaskOutbox.task_id == str(event.id))) == (
            "cancelled"
        )
        db.commit()


@pytest.mark.asyncio
async def test_two_sessions_budget_reservation_is_atomic():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    run_id, _ = await authority()
    with get_session_factory()() as db:
        db.get(WorkbenchRun, run_id).budget = {"segments": 1}
        db.commit()
    barrier = Barrier(2)

    def reserve():
        with get_session_factory()() as db:
            barrier.wait(timeout=5)
            result = reserve_budget(db, run_id, {"segments": 1})
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sorted(results) == [False, True]
    with get_session_factory()() as db:
        assert db.get(WorkbenchRun, run_id).used == {"segments": 1}


@pytest.mark.asyncio
async def test_external_revision_change_invalidates_unchanged_canonical_selection():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, conversation = await setup(client)
        created = await client.post(f"/api/v1/collections/{collection['id']}/test-cases", json={
            "title": "Original", "module": "Scope", "priority": "P1",
            "case_type": "functional", "steps": [{"action": "Act", "expected": "Original"}],
        })
        assert created.status_code == 201, created.text
        case = created.json()
        selected = await client.patch(f"/api/v1/workspaces/{conversation['id']}/selection", json={
            "base_version": 0, "action": "replace",
            "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
        })
        assert selected.status_code == 200, selected.text
        with get_session_factory()() as db:
            owner = db.get(Account, UUID(account["id"]))
            convo = db.get(Conversation, UUID(conversation["id"]))
            message = ConversationMessage(conversation_id=convo.id, role="user", content="Review",
                status="completed", target_case_ids=[], citations=[], message_metadata={})
            db.add(message)
            db.flush()
            run = create_run(db, owner, convo, message.id, uuid4())
            event_id = enqueue_event(db, run, "job_completed", "exact-job", "1").id
            run_id = run.id
            db.commit()
        changed = await client.patch(f"/api/v1/test-cases/{case['id']}", json={
            "base_revision_id": case["current_revision_id"], "title": "External edit",
            "steps": case["steps"],
        })
        assert changed.status_code == 200, changed.text
    with get_session_factory()() as db:
        assert claim_event(db, event_id) is None
        assert db.get(WorkbenchRun, run_id).status == "invalidated"
        assert db.get(WorkbenchContinuation, event_id).receipt == {
            "error_code": "workbench_run_source_changed"
        }
        db.commit()


@pytest.mark.asyncio
async def test_paused_question_preserves_pending_event_and_claimed_effects_cannot_commit():
    from fastapi import HTTPException

    run_id, _ = await authority()
    with get_session_factory()() as db:
        run = db.get(WorkbenchRun, run_id)
        event_id = enqueue_event(db, run, "job_completed", "waiting", "1").id
        run.status = "paused_question"
        db.commit()
    with get_session_factory()() as db:
        assert claim_event(db, event_id) is None
        assert not reserve_budget(db, run_id, {"segments": 1})
        assert db.get(WorkbenchContinuation, event_id).status == "pending"
        assert db.get(WorkbenchRun, run_id).status == "paused_question"
        db.get(WorkbenchRun, run_id).status = "active"
        db.commit()
    with get_session_factory()() as db:
        _, _, token = claim_event(db, event_id)
        db.commit()
    with get_session_factory()() as db:
        db.get(WorkbenchRun, run_id).status = "paused_question"
        db.commit()
    with get_session_factory()() as db:
        assert not recover_claim(db, event_id)
        with pytest.raises(HTTPException, match="workbench_run_paused"):
            complete_event(db, event_id, token, {"must_not_commit": True})
        assert db.get(WorkbenchContinuation, event_id).receipt == {}
        assert db.get(WorkbenchRun, run_id).cursor == 0
        db.rollback()


@pytest.mark.asyncio
async def test_preapproval_rejects_external_binding_change_before_any_effect():
    from fastapi import HTTPException

    run_id, cid = await authority()
    with get_session_factory()() as db:
        run, conversation = db.get(WorkbenchRun, run_id), db.get(Conversation, cid)
        run.checkpoint = {"waiting_artifact_kind": "change_set", "waiting_artifact_id": "diff",
                          "waiting_artifact_version": "1"}
        conversation.context = {**conversation.context,
                                "workbench_selection": {"version": 1, "items": []}}
        with pytest.raises(HTTPException, match="workbench_run_binding_changed"):
            capture_approval_binding(db, conversation, "change_set", "diff", "1")
        assert run.binding["selection_version"] == 0
        assert db.scalar(select(WorkbenchContinuation.id).where(
            WorkbenchContinuation.run_id == run_id)) is None
        db.rollback()


@pytest.mark.asyncio
async def test_approval_token_cannot_be_omitted_forged_or_reused_after_transaction():
    from fastapi import HTTPException

    run_id, cid = await authority()
    with get_session_factory()() as db:
        run, conversation = db.get(WorkbenchRun, run_id), db.get(Conversation, cid)
        run.checkpoint = {"waiting_artifact_kind": "change_set", "waiting_artifact_id": "diff",
                          "waiting_artifact_version": "1"}
        with pytest.raises(HTTPException, match="workbench_approval_binding_required"):
            record_approval(db, conversation, "change_set", "diff", "1")
        with pytest.raises(HTTPException, match="workbench_approval_binding_invalid"):
            record_approval(db, conversation, "change_set", "diff", "1",
                            preapproval_binding={"run_id": str(run_id)})
        token = capture_approval_binding(db, conversation, "change_set", "diff", "1")
        db.commit()
    with get_session_factory()() as db:
        with pytest.raises(HTTPException, match="workbench_approval_binding_invalid"):
            record_approval(db, db.get(Conversation, cid), "change_set", "diff", "1",
                            preapproval_binding=token)
        assert db.scalar(select(WorkbenchContinuation.id).where(
            WorkbenchContinuation.run_id == run_id)) is None


@pytest.mark.asyncio
async def test_postapproval_cannot_rebase_unrelated_current_selection_or_fake_delta():
    from fastapi import HTTPException

    run_id, cid = await authority()
    with get_session_factory()() as db:
        run, conversation = db.get(WorkbenchRun, run_id), db.get(Conversation, cid)
        run.checkpoint = {"waiting_artifact_kind": "change_set", "waiting_artifact_id": "diff",
                          "waiting_artifact_version": "1"}
        token = capture_approval_binding(db, conversation, "change_set", "diff", "1")
        conversation.context = {**conversation.context,
                                "workbench_selection": {"version": 1, "items": []}}
        with pytest.raises(HTTPException, match="workbench_approval_binding_delta_invalid"):
            record_approval(db, conversation, "change_set", "diff", "1",
                            preapproval_binding=token)
        with pytest.raises(HTTPException, match="workbench_approval_delta_outside_artifact"):
            record_approval(db, conversation, "change_set", "diff", "1",
                            preapproval_binding=token,
                            approved_updates={f"asset:{uuid4()}": str(uuid4())})
        assert run.binding["selection_version"] == 0
        db.rollback()
