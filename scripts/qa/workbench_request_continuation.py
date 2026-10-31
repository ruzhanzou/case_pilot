"""QA transport adapter: follow one real user root with the existing executor.

No plan scheduling, approval, scope mutation or fabricated response lives here.
The production outbox/executor owns all work and state transitions.
"""

from copy import deepcopy
from typing import ClassVar
from unittest.mock import patch
from uuid import UUID

from workbench_agent_live_continuation import CONTINUE, DurableDispatch
from workbench_agent_live_journey import (
    Journey,
    JourneyFailure,
    emit_json,
    require,
    runtime_diagnostics,
    safe_turn_evidence,
)

TERMINAL = {"completed", "cancelled", "invalidated", "failed", "budget_exhausted"}

FAILURE_CODES = frozenset(
    [
        "durable_apply_not_terminal",
        "durable_foreign_delivery",
        "durable_mode_invalid",
        "durable_no_deliverable_work",
        "durable_outbox_args_invalid",
        "durable_pending_not_consumed",
        "durable_prepared_response_missing",
        "durable_request_binding_changed",
        "durable_request_epoch_changed",
        "durable_request_missing",
        "durable_response_not_persisted",
        "durable_response_run_stopped",
        "durable_response_scope_invalid",
        "durable_run_failed",
        "durable_wait_timeout",
        "durable_worker_failed",
        "outbox_delivery_failed",
        "unexpected_task_dispatch",
        "worker_task_budget_exhausted",
    ]
)


class RequestContinuation(DurableDispatch):
    task_methods: ClassVar = {
        **DurableDispatch.task_methods,
        "casepilot.agent.rewrite_batch": "rewrite_test_cases_batch",
    }

    def __init__(self, cid, turn, report):
        super().__init__(cid)
        binding = turn["assistant_message"]["metadata"]["workbench_agent"][
            "durable_run"
        ]
        self.run_id, self.root_id = (
            UUID(binding["id"]),
            UUID(turn["user_message"]["id"]),
        )
        self.request_id, self.epoch = UUID(binding["request_id"]), binding["epoch"]
        self.latest_turn, self.report = turn, report

    def bound_run(self, db):
        from casepilot_api.models import WorkbenchRun

        run = db.get(WorkbenchRun, self.run_id)
        require(
            run is not None
            and run.conversation_id == self.cid
            and run.root_message_id == self.root_id
            and run.request_id == self.request_id,
            "durable_request_binding_changed",
        )
        require(
            run.epoch == self.epoch or run.status in {"cancelled", "invalidated"},
            "durable_request_epoch_changed",
        )
        return run

    def validate_delivery(self, db, name, identifier):
        from casepilot_api.models import GenerationJob, WorkbenchContinuation

        run = self.bound_run(db)
        if name == CONTINUE:
            event = db.get(WorkbenchContinuation, UUID(str(identifier)))
            require(
                event is not None and event.run_id == run.id, "durable_foreign_delivery"
            )
        else:
            require(name in self.task_methods, "unexpected_task_dispatch")
            job = db.get(GenerationJob, UUID(str(identifier)))
            require(
                job is not None
                and job.account_id == run.account_id
                and job.space_id == run.space_id
                and job.input_payload.get("workbench_run_id") == str(run.id)
                and job.input_payload.get("workbench_epoch") == self.epoch
                and str(job.input_payload.get("conversation_id")) == str(self.cid),
                "durable_foreign_delivery",
            )

    def before_dispatch(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import TaskOutbox
        from sqlalchemy import select

        # The real dispatcher is global. Refuse an unisolated queue BEFORE it can
        # mark any foreign row dispatched/retried. No selector is patched into it.
        with get_session_factory()() as db:
            for row in db.scalars(
                select(TaskOutbox).where(TaskOutbox.status == "pending")
            ):
                require(row.task_args == [row.task_id], "durable_outbox_args_invalid")
                self.validate_delivery(db, row.task_name, row.task_id)

    def enqueue(self, name, args, **kwargs):
        from casepilot_api.database import get_session_factory

        require(len(args) == 1, "unexpected_task_dispatch")
        with get_session_factory()() as db:
            self.validate_delivery(db, name, args[0])
        super().enqueue(name, args, **kwargs)

    def state(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import (
            GenerationJob,
            TaskOutbox,
            WorkbenchContinuation,
        )
        from sqlalchemy import select

        with get_session_factory()() as db:
            run = self.bound_run(db)
            event_ids = {
                str(v)
                for v in db.scalars(
                    select(WorkbenchContinuation.id).where(
                        WorkbenchContinuation.run_id == run.id
                    )
                )
            }
            job_ids = {
                str(job.id)
                for job in db.scalars(
                    select(GenerationJob).where(
                        GenerationJob.input_payload["workbench_run_id"].astext
                        == str(run.id)
                    )
                )
            }
            pending = sum(
                row.task_id in event_ids | job_ids
                for row in db.scalars(
                    select(TaskOutbox).where(TaskOutbox.status == "pending")
                )
            )
            return {
                "status": run.status,
                "cursor": run.cursor,
                "steps": len(run.plan.get("steps") or []),
                "pending_outbox": pending,
                "pending_events": len(
                    list(
                        db.scalars(
                            select(WorkbenchContinuation.id).where(
                                WorkbenchContinuation.run_id == run.id,
                                WorkbenchContinuation.status.in_(
                                    ["pending", "running"]
                                ),
                            )
                        )
                    )
                ),
                "operation": run.checkpoint.get("waiting_operation_id"),
                "artifact_kind": run.checkpoint.get("waiting_artifact_kind"),
            }

    def capture_turn(self, function):
        def observed(*args, **kwargs):
            run = kwargs.get("durable_run")
            require(
                run is not None
                and run.id == self.run_id
                and run.epoch == self.epoch
                and run.root_message_id == self.root_id,
                "durable_response_scope_invalid",
            )
            value = function(*args, **kwargs)
            # Executor still owns an uncommitted SubmissionTransaction here.
            # Retain the actual return internally; verify persistence only AFTER
            # the real executor has completed its checkpoint transaction.
            self.captured_turn = value.model_dump(mode="json")
            self.report["capture_phase"] = "captured_pending_commit"
            return value

        return observed

    def verify_captured_turn(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import ConversationMessage

        turn = getattr(self, "captured_turn", None)
        if turn is None:
            return
        require(
            turn["user_message"]["id"] == str(self.root_id),
            "durable_response_scope_invalid",
        )
        with get_session_factory()() as db:
            run = self.bound_run(db)
            require(
                run.status
                not in {"failed", "cancelled", "invalidated", "budget_exhausted"},
                "durable_response_run_stopped",
            )
            message = db.get(ConversationMessage, UUID(turn["assistant_message"]["id"]))
            require(
                message is not None and message.conversation_id == self.cid,
                "durable_response_not_persisted",
            )
            bound = message.message_metadata.get("workbench_agent", {}).get(
                "durable_run", {}
            )
            require(
                bound.get("id") == str(self.run_id)
                and bound.get("request_id") == str(self.request_id)
                and bound.get("epoch") == self.epoch,
                "durable_response_scope_invalid",
            )
        self.latest_turn = deepcopy(turn)
        self.captured_turn = None
        self.report["capture_phase"] = "verified_committed_message"

    async def advance(self, tasks, mode):
        from casepilot_api import workbench_tools

        require(mode in {"message", "workers", "applied"}, "durable_mode_invalid")
        before, continuations = self.executed, len(self.continuation_ids)

        def stop():
            state = self.state()
            if state["status"] in {"cancelled", "invalidated"}:
                return True  # Observe loss of authority, never revive an old root.
            if (
                state["status"]
                in {
                    "completed",
                    "waiting_approval",
                    "awaiting_input",
                    "paused_question",
                }
                and not state["pending_outbox"]
                and not state["pending_events"]
            ):
                return True
            return (
                mode == "message"
                and state["status"] == "waiting_job"
                and bool(state["operation"])
            )

        try:
            with (
                patch.object(tasks.celery_app, "send_task", side_effect=self.enqueue),
                patch.object(
                    workbench_tools,
                    "run_workbench_turn",
                    self.capture_turn(workbench_tools.run_workbench_turn),
                ),
            ):
                await super().drain(
                    tasks,
                    timeout_seconds=180,
                    stop_when=stop,
                    before_dispatch=self.before_dispatch,
                )
            self.verify_captured_turn()
            state = self.state()
            prepared = (
                mode == "message"
                and state["status"] == "waiting_job"
                and state["operation"]
            )
            if prepared:
                operations = (self.latest_turn.get("operation_plan") or {}).get(
                    "operations", []
                )
                require(
                    any(op.get("id") == state["operation"] for op in operations),
                    "durable_prepared_response_missing",
                )
            if not prepared and state["status"] not in {"cancelled", "invalidated"}:
                require(
                    state["pending_outbox"] == 0 and state["pending_events"] == 0,
                    "durable_pending_not_consumed",
                )
                require(
                    state["status"]
                    in TERMINAL
                    | {"waiting_approval", "awaiting_input", "paused_question"},
                    "durable_no_deliverable_work",
                )
            require(
                state["status"] not in {"failed", "budget_exhausted"},
                "durable_run_failed",
            )
            self.report["runtime_diagnostics"] = runtime_diagnostics(
                self.latest_turn["assistant_message"]["metadata"]["workbench_agent"]
            )
            return self.latest_turn
        except JourneyFailure as error:
            code = error.args[0] if error.args else None
            self.report["durable_error_code"] = (
                code if type(code) is str and code in FAILURE_CODES else "unknown"
            )
            raise
        finally:
            self.report["durable_executor_calls"] = self.report.get(
                "durable_executor_calls", 0
            ) + (len(self.continuation_ids) - continuations)
            self.report["durable_domain_tasks"] = self.report.get(
                "durable_domain_tasks", 0
            ) + (self.executed - before - len(self.continuation_ids) + continuations)
            try:
                state = self.state()
                self.report.setdefault("durable_stops", []).append(
                    {
                        "mode": mode,
                        "status": state["status"]
                        if state["status"]
                        in TERMINAL
                        | {
                            "active",
                            "running",
                            "waiting_job",
                            "waiting_approval",
                            "awaiting_input",
                            "paused_question",
                        }
                        else "unknown",
                        "cursor": state["cursor"],
                        "steps": state["steps"],
                        "pending_outbox": state["pending_outbox"],
                        "pending_events": state["pending_events"],
                    }
                )
            except Exception:  # noqa: BLE001 - diagnostics cannot replace the original result
                self.report.setdefault("durable_stops", []).append(
                    {"mode": mode, "diagnostic_unavailable": True}
                )


class NaturalDurableJourney(Journey):
    """Original natural_selection methods/assertions, with explicit durable boundaries."""

    current_request = None

    async def message(self, cid, content, **kwargs):
        before = await self.workspace(cid)
        turn = await super().message(cid, content, **kwargs)
        self.current_request = RequestContinuation(cid, turn, self.report)
        current = await self.current_request.advance(self.tasks, "message")
        if current is not turn:
            self.report["last_turn_evidence"] = safe_turn_evidence(
                current, before, kwargs, self.stage, getattr(self, "_redact_secret", "")
            )
            emit_json(
                {
                    "event": "synthetic_durable_turn_observation",
                    **self.report["last_turn_evidence"],
                }
            )
        return current

    async def apply_selected(self, *args, **kwargs):
        value = await super().apply_selected(*args, **kwargs)
        await self.current_request.advance(self.tasks, "applied")
        if self.current_request.state()["status"] != "completed":
            self.report["durable_error_code"] = "durable_apply_not_terminal"
        require(
            self.current_request.state()["status"] == "completed",
            "durable_apply_not_terminal",
        )
        return value

    async def drain_workers(self, tasks):
        require(self.current_request is not None, "durable_request_missing")
        await self.current_request.advance(tasks, "workers")


class RequestWorkerDispatch:
    """Keep Journey's existing worker boundary; no direct delivery queue."""

    journey = None

    @property
    def executed(self):
        return self.journey.report.get("durable_domain_tasks", 0) if self.journey else 0

    async def drain(self, tasks):
        require(self.journey is not None, "durable_request_missing")
        await self.journey.drain_workers(tasks)
