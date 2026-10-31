"""Durable, fail-closed suspension of an existing goal during a real side question.

No classifier decides authority. Read-only tool effects restore the old cursor;
a mutating tool intent invalidates it before its domain call. A crash leaves an
honest paused goal. A cancellation or a newer epoch can never be resurrected.
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from casepilot_api.models import WorkbenchContinuation, WorkbenchRun
from casepilot_api.task_outbox import enqueue_task
from casepilot_api.workbench_continuation import TASK_NAME, TERMINAL, _invalidate_events

PAUSED = "paused_question"


def pause_prior_runs(factory, account_id, conversation_id, request_id):
    with factory() as db:
        runs = list(db.scalars(select(WorkbenchRun).where(
            WorkbenchRun.account_id == account_id,
            WorkbenchRun.conversation_id == conversation_id,
            WorkbenchRun.request_id != UUID(str(request_id)),
            WorkbenchRun.status.not_in(TERMINAL),
        ).with_for_update()))
        for run in runs:
            lease = dict(run.checkpoint).get("question_pause")
            if run.status == PAUSED:
                if not lease or lease.get("request_id") != str(request_id):
                    raise HTTPException(409, "workbench_question_in_progress")
                continue
            run.checkpoint = {**run.checkpoint, "question_pause": {
                "request_id": str(request_id), "epoch": run.epoch,
                "previous_status": run.status,
            }}
            run.status = PAUSED
        db.commit()
        return [str(run.id) for run in runs]


def resolve_question(db, account_id, conversation_id, request_id, *, mutated=False):
    runs = list(db.scalars(select(WorkbenchRun).where(
        WorkbenchRun.account_id == account_id,
        WorkbenchRun.conversation_id == conversation_id,
        WorkbenchRun.status == PAUSED,
    ).with_for_update()))
    for run in runs:
        lease = dict(run.checkpoint).get("question_pause") or {}
        if (lease.get("request_id") != str(request_id) or lease.get("epoch") != run.epoch
                or run.cancelled_at is not None):
            continue
        checkpoint = {key: value for key, value in run.checkpoint.items()
                      if key != "question_pause"}
        if mutated:
            run.status, run.epoch = "invalidated", run.epoch + 1
            run.checkpoint = {**checkpoint, "invalidation_reason": "new_mutating_instruction"}
            _invalidate_events(db, run, "invalidated")
        else:
            run.status = lease["previous_status"]
            run.checkpoint = checkpoint
            # A broker may have acknowledged a paused delivery. Republish the SAME
            # durable observation, not a new cursor/model instruction.
            pending = list(db.scalars(select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run.id,
                WorkbenchContinuation.expected_epoch == run.epoch,
                WorkbenchContinuation.cursor == run.cursor,
                WorkbenchContinuation.status.in_(["pending", "running"]),
            ).with_for_update()))
            for event in pending:
                event.status, event.claim_token = "pending", None
                enqueue_task(db, TASK_NAME, [str(event.id)], task_id=event.id)
    db.flush()


def invalidate_for_mutation(factory, account_id, conversation_id, request_id):
    with factory() as db:
        resolve_question(db, account_id, conversation_id, request_id, mutated=True)
        db.commit()
