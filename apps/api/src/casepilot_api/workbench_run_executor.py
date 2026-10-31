"""API-image continuation worker. GET and SSE never import or invoke this executor.

Broker delivery is at least once. A session advisory guard serializes a durable
run without retaining a row lock across model calls. Reservations survive crashes.
"""
from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID

from celery import Celery
from sqlalchemy import select, text

from casepilot_api.config import get_settings
from casepilot_api.database import get_session_factory
from casepilot_api.models import (
    Account,
    CaseChangeSet,
    Conversation,
    GenerationJob,
    WorkbenchContinuation,
    WorkspaceCandidate,
    WorkspaceTestBrief,
)
from casepilot_api.workbench_continuation import (
    TASK_NAME,
    TERMINAL,
    claim_event,
    complete_event,
    enqueue_event,
    load_run,
    recover_claim,
    reserve_budget,
)

settings = get_settings()
app = Celery("casepilot_workbench", broker=settings.celery_broker_url,
             backend=settings.celery_result_backend)
app.conf.update(task_routes={TASK_NAME: {"queue": "workbench"}},
                task_acks_late=True, task_reject_on_worker_lost=True,
                worker_prefetch_multiplier=1)


def _review_boundary(db, run, job):
    """Discover only artifacts produced by this exact bound worker/operation."""
    checkpoint = dict(run.checkpoint)
    change = db.scalar(select(CaseChangeSet).where(CaseChangeSet.generation_job_id == job.id))
    if change is not None and change.status == "ready":
        from casepilot_api.workbench_artifact_version import change_set_version
        return {"waiting_artifact_kind": "change_set", "waiting_artifact_id": str(change.id),
                "waiting_artifact_version": change_set_version(change)}
    operation_id = checkpoint.get("waiting_operation_id")
    if operation_id:
        brief = db.scalar(select(WorkspaceTestBrief).where(
            WorkspaceTestBrief.conversation_id == run.conversation_id,
            WorkspaceTestBrief.source_operation_id == UUID(operation_id),
            WorkspaceTestBrief.status == "draft",
        ).order_by(WorkspaceTestBrief.version.desc()))
        if brief is not None:
            return {"waiting_artifact_kind": "test_brief", "waiting_artifact_id": str(brief.id),
                    "waiting_artifact_version": str(brief.version)}
    candidates = list(db.scalars(select(WorkspaceCandidate).where(
        WorkspaceCandidate.generation_job_id == job.id,
        WorkspaceCandidate.status == "candidate")))
    if candidates:
        return {"waiting_artifact_kind": "candidates", "waiting_artifact_id": str(job.id),
                "waiting_artifact_version": str(job.id),
                "candidate_versions": {str(c.id): c.version for c in candidates}}
    return None


def _advance(db, run, event, token):
    steps = deepcopy(run.plan.get("steps", []))
    if run.cursor < len(steps):
        steps[run.cursor]["status"] = "completed"
    run.plan = {**run.plan, "steps": steps}
    done = run.cursor + 1 >= len(steps)
    checkpoint = {k: v for k, v in run.checkpoint.items() if not k.startswith("waiting_")}
    complete_event(db, event.id, token, {"outcome": "step_completed"},
                   status="completed" if done else "active", checkpoint=checkpoint)
    if not done:
        enqueue_event(db, run, "next_step", str(event.id), str(run.cursor),
                      {"previous_step": run.cursor - 1})


def _observe(db, run, event, token):
    if event.event_kind == "approval_completed":
        if event.payload.get("outcome") != "approved" or event.payload.get("next_job_id"):
            raise ValueError("invalid_approval_continuation")
        _advance(db, run, event, token)
        return
    job_id = event.payload.get("job_id")
    if event.event_kind != "job_completed" or not job_id:
        raise ValueError("unbound_workbench_observation")
    if str(run.checkpoint.get("waiting_job_id")) != str(job_id):
        # An exact human approval may have already started the successor job.
        complete_event(db, event.id, token, {"outcome": "superseded_observation"},
                       status="waiting_job" if run.checkpoint.get("waiting_job_id")
                       else "waiting_approval", advance_cursor=False)
        return
    job = db.get(GenerationJob, UUID(job_id))
    if job is None or str(job.input_payload.get("workbench_run_id")) != str(run.id):
        raise ValueError("unbound_workbench_job")
    status = str(getattr(job.status, "value", job.status))
    if status in {"failed", "cancelled"}:
        complete_event(db, event.id, token, {"job_id": job_id, "status": status}, status=status,
                       advance_cursor=False)
        return
    if status == "awaiting_input":
        complete_event(db, event.id, token, {"outcome": "human_review"},
            status="waiting_approval", advance_cursor=False,
            checkpoint={**run.checkpoint, "waiting_artifact_kind": "generation_job",
                        "waiting_artifact_id": str(job.id),
                        "waiting_artifact_version": str(job.input_payload.get("task_revision", 1))})
        return
    if status != "completed":
        raise ValueError("nonterminal_workbench_job")
    boundary = _review_boundary(db, run, job)
    if boundary:
        complete_event(db, event.id, token, {"job_id": job_id, "outcome": "human_review"},
                       status="waiting_approval", advance_cursor=False,
                       checkpoint={**run.checkpoint, **boundary, "waiting_job_id": None})
    else:
        _advance(db, run, event, token)


def execute_workbench_continuation(event_id, *, session_factory=None):
    factory = session_factory or get_session_factory()
    with factory() as db:
        event = db.get(WorkbenchContinuation, UUID(str(event_id)))
        if event is None:
            return {"status": "missing"}
        run_id = event.run_id
        engine = db.get_bind()
    # Session-level guard on a dedicated connection; no row is locked during I/O.
    guard_key = UUID(str(run_id)).int % (2**63 - 1)
    with engine.connect() as guard:
        if not guard.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": guard_key}):
            return {"status": "busy"}
        try:
            with factory() as db:
                recover_claim(db, event_id)
                claimed = claim_event(db, event_id)
                if claimed is None:
                    db.commit()
                    return {"status": "ignored"}
                run, event, token = claimed
                if event.event_kind != "next_step":
                    _observe(db, run, event, token)
                    db.commit()
                    return {"status": run.status}
                from fastapi import HTTPException

                from casepilot_api.workbench_scope import restore_authorized_scope
                try:
                    restore_authorized_scope(run, db.get(Conversation, run.conversation_id))
                except HTTPException:
                    complete_event(db, event.id, token,
                        {"error_code": "workbench_scope_requires_selection"},
                        status="waiting_approval", advance_cursor=False,
                        checkpoint={**run.checkpoint,
                                    "error_code": "workbench_scope_requires_selection"})
                    db.commit()
                    return {"status": "waiting_approval"}
                limits = {"segments": 1, "model_turns": settings.workbench_agent_max_turns,
                          "tool_calls": settings.workbench_agent_max_tool_calls,
                          "reserved_sdk_requests": settings.workbench_agent_max_turns}
                if not reserve_budget(db, run.id, limits):
                    event.status, event.receipt = "completed", {"error_code": "budget_exhausted"}
                    db.commit()
                    return {"status": "budget_exhausted"}
                from casepilot_api.workbench_events import reserved_segment_base
                run.checkpoint = {**run.checkpoint, "event_sequence_base": reserved_segment_base(
                    run.used, settings.workbench_agent_max_turns,
                    settings.workbench_agent_max_tool_calls)}
                db.commit()  # Durable conservative reservation precedes any provider call.
            from casepilot_api.submissions import SubmissionTransaction
            from casepilot_api.workbench_tools import run_workbench_turn
            with factory() as db:
                run = load_run(db, run_id)
                original_cursor = run.cursor
                db.expunge(run)  # Runtime checkpoint is local until effect/receipt commit.
                conversation = db.get(Conversation, run.conversation_id)
                account = db.get(Account, run.account_id)
                from casepilot_api.workbench_scope import restore_authorized_scope
                payload = restore_authorized_scope(run, conversation)
                transaction = SubmissionTransaction(db)
                observation = ("Continue the SAME original user task. No new user authorization. "
                    "Completed steps are observations, not new receipts. Execute only the current "
                    "pending step; stop for real human review. Durable server plan: " + json.dumps(
                        {"steps": run.plan.get("steps", []), "cursor": run.cursor},
                        ensure_ascii=False))
                def stopped():
                    with factory() as check:
                        current = load_run(check, run_id)
                        return (current.cancelled_at is not None
                                or current.status in TERMINAL | {"paused_question"}
                                or current.epoch != run.epoch
                                or current.cursor != original_cursor)

                run_workbench_turn(transaction, account, conversation, payload, settings,
                    durable_run=run, continuation_observation=observation,
                    reserve=lambda amounts: True, cancel_check=stopped)
                desired = run.status
                current = load_run(db, run_id, for_update=True)
                if (current.cancelled_at or current.status in TERMINAL | {"paused_question"}
                        or current.epoch != run.epoch or current.cursor != original_cursor):
                    db.rollback()
                    return {"status": "obsolete"}
                current.plan, current.binding = run.plan, run.binding
                current.checkpoint = run.checkpoint
                current.status = "running"
                db.flush()
                complete_event(db, event_id, token, {"outcome": "segment_checkpoint"},
                               status=desired, checkpoint=run.checkpoint,
                               advance_cursor=False)
                # Query prefixes may consume several distinct real read receipts
                # before a preparation in this segment; never collapse that cursor.
                current.cursor = run.cursor
                db.commit()
                transaction.publish_committed_effects()
                return {"status": desired}
        except Exception:
            # Process loss (BaseException) is recovered with budgets still spent.
            # Ordinary execution/contract failures pause once, never hot-loop.
            with factory() as failure_db:
                failed_run = load_run(failure_db, run_id, for_update=True)
                failed_event = failure_db.get(WorkbenchContinuation, UUID(str(event_id)))
                if (failed_event is not None and failed_event.status == "running"
                        and failed_run.status not in TERMINAL | {"paused_question"}):
                    failed_event.status = "failed"
                    failed_event.receipt = {"error_code": "workbench_continuation_failed"}
                    failed_run.status = "failed"
                    failed_run.checkpoint = {**failed_run.checkpoint,
                        "error_code": "workbench_continuation_failed"}
                    failure_db.commit()
            return {"status": "failed", "error_code": "workbench_continuation_failed"}
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": guard_key})
            guard.commit()


@app.task(name=TASK_NAME, bind=True, max_retries=5)
def continue_workbench(self, event_id):
    result = execute_workbench_continuation(event_id)
    if result.get("status") == "busy":
        raise self.retry(countdown=min(2 ** self.request.retries, 30))
    return result


@app.task(name="casepilot.workbench.planning_review", acks_late=True)
def planning_review_task(review_id, phase):
    from casepilot_api.planning_review import execute
    return execute(review_id, phase)
