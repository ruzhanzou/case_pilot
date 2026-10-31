"""Bound QA adapter for the existing real durable dispatcher/executor.

Only broker transport is replaced. All objects stay internal; no model output,
arguments, IDs or database contents are emitted by this adapter.
"""

from copy import deepcopy
from unittest.mock import patch
from uuid import UUID

from workbench_agent_live_continuation import CONTINUE, DurableDispatch
from workbench_agent_live_journey import require, runtime_diagnostics


class BoundCollectionDispatch(DurableDispatch):
    def __init__(self, cid, turn):
        super().__init__(cid)
        state = (
            turn.get("assistant_message", {})
            .get("metadata", {})
            .get("workbench_agent", {})
        )
        binding = state.get("durable_run") or {}
        require(
            bool(binding.get("id")) and bool(turn.get("user_message", {}).get("id")),
            "durable_binding_missing",
        )
        self.run_id = UUID(binding["id"])
        self.request_id = UUID(binding["request_id"])
        self.root_id = UUID(turn["user_message"]["id"])
        self.epoch = binding["epoch"]

    def bound_run(self, db):
        from casepilot_api.models import WorkbenchRun

        run = db.get(WorkbenchRun, self.run_id)
        require(
            run is not None
            and run.conversation_id == self.cid
            and run.root_message_id == self.root_id
            and run.request_id == self.request_id
            and run.epoch == self.epoch,
            "durable_binding_changed",
        )
        return run

    def enqueue(self, name, args, **kwargs):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import WorkbenchContinuation

        require(name == CONTINUE and len(args) == 1, "unexpected_task_dispatch")
        with get_session_factory()() as db:
            self.bound_run(db)
            event = db.get(WorkbenchContinuation, UUID(str(args[0])))
            require(
                event is not None and event.run_id == self.run_id,
                "outbox_continuation_scope_mismatch",
            )
        # Duplicate/stale deliveries go through the real executor's claim guard.
        super().enqueue(name, args, **kwargs)

    def proposal_turn(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import Conversation, ConversationMessage
        from sqlalchemy import select

        with get_session_factory()() as db:
            run = self.bound_run(db)
            if (
                run.status != "waiting_approval"
                or run.checkpoint.get("waiting_artifact_kind") != "collection_proposal"
            ):
                return None
            conversation = db.get(Conversation, self.cid)
            proposal = (conversation.context or {}).get(
                "workbench_collection_proposal"
            ) or {}
            checkpoint = run.checkpoint
            require(
                proposal.get("status") == "pending"
                and checkpoint.get("waiting_artifact_kind") == "collection_proposal"
                and checkpoint.get("waiting_artifact_id") == proposal.get("id")
                and checkpoint.get("waiting_artifact_version") == proposal.get("id"),
                "durable_proposal_binding_invalid",
            )
            # Project only a real assistant receipt from this run/epoch and artifact.
            messages = db.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == self.cid,
                    ConversationMessage.role == "assistant",
                )
                .order_by(ConversationMessage.created_at.desc())
            )
            for message in messages:
                metadata = message.message_metadata or {}
                state = metadata.get("workbench_agent") or {}
                binding = state.get("durable_run") or {}
                if (
                    binding.get("id") == str(self.run_id)
                    and binding.get("request_id") == str(self.request_id)
                    and binding.get("epoch") == self.epoch
                    and metadata.get("workbench_collection_proposal") == proposal
                ):
                    return deepcopy(
                        {
                            "action": {
                                "type": "collection_proposal",
                                "proposal": proposal,
                            },
                            "assistant_message": {
                                "metadata": {"workbench_agent": state}
                            },
                        }
                    )
            require(False, "durable_proposal_receipt_missing")

    def pending_delivery(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import TaskOutbox, WorkbenchContinuation
        from sqlalchemy import select

        with get_session_factory()() as db:
            run = self.bound_run(db)
            if run.status in {
                "waiting_approval",
                "awaiting_input",
                "failed",
                "cancelled",
                "completed",
                "budget_exhausted",
                "invalidated",
                "paused_question",
            }:
                return False
            pending = list(
                db.scalars(select(TaskOutbox).where(TaskOutbox.status == "pending"))
            )
            for row in pending:
                require(row.task_name == CONTINUE, "unexpected_task_dispatch")
                event = db.get(WorkbenchContinuation, UUID(row.task_id))
                require(
                    event is not None and event.run_id == run.id,
                    "outbox_continuation_scope_mismatch",
                )
            return bool(pending)

    def safe_state(self):
        from casepilot_api.database import get_session_factory
        from casepilot_api.workbench_tool_diagnostics import safe_tool_diagnostic

        with get_session_factory()() as db:
            run = self.bound_run(db)
            steps = run.plan.get("steps") or []
            current = steps[run.cursor] if 0 <= run.cursor < len(steps) else {}
            value = safe_tool_diagnostic(
                {
                    "plan_present": bool(steps),
                    "plan_cursor": run.cursor,
                    "plan_action": current.get("action"),
                }
            )
            value["run_status"] = (
                run.status
                if run.status
                in {
                    "active",
                    "running",
                    "waiting_approval",
                    "awaiting_input",
                    "waiting_job",
                    "failed",
                    "cancelled",
                    "completed",
                    "budget_exhausted",
                    "paused_question",
                    "invalidated",
                }
                else "unrecognized"
            )
            return value


async def await_collection_proposal(cid, turn, tasks, report):
    dispatch = BoundCollectionDispatch(cid, turn)
    try:
        proposed = dispatch.proposal_turn()
        if proposed is None:
            # No queue is a bounded diagnostic terminal, never an empty wait loop.
            require(dispatch.pending_delivery(), "durable_no_deliverable_continuation")
            with patch.object(
                tasks.celery_app, "send_task", side_effect=dispatch.enqueue
            ):
                await dispatch.drain(tasks, timeout_seconds=180)
            proposed = dispatch.proposal_turn()
        require(proposed is not None, "durable_proposal_not_ready")
        report["runtime_diagnostics"] = runtime_diagnostics(
            proposed["assistant_message"]["metadata"]["workbench_agent"]
        )
        return proposed
    finally:
        report["continuation_tasks_executed"] = (
            report.get("continuation_tasks_executed", 0) + dispatch.executed
        )
        report["broker_transport"] = "in_process_real_outbox_executor"
        try:
            report["continuation_terminal"] = dispatch.safe_state()
        except Exception:  # noqa: BLE001 - diagnostic failure must preserve the original outcome
            report["continuation_terminal"] = {"diagnostic_unavailable": True}


async def finish_collection_approval(cid, turn, proposal, tasks, report):
    """Consume only the real approval of the final collection-delete step."""
    from casepilot_api.database import get_session_factory
    from casepilot_api.models import TaskOutbox, WorkbenchContinuation
    from sqlalchemy import select

    dispatch = BoundCollectionDispatch(cid, turn)
    with get_session_factory()() as db:
        run = dispatch.bound_run(db)
        steps = run.plan.get("steps") or []
        require(
            run.status == "waiting_approval"
            and run.cursor == len(steps) - 1
            and steps[run.cursor].get("action") == "COLLECTION_DELETE",
            "durable_approval_step_invalid",
        )
        events = list(
            db.scalars(
                select(WorkbenchContinuation).where(
                    WorkbenchContinuation.run_id == run.id,
                    WorkbenchContinuation.status == "pending",
                )
            )
        )
        require(len(events) == 1, "durable_approval_event_invalid")
        event = events[0]
        require(
            event.event_kind == "approval_completed"
            and event.source_id == proposal["id"]
            and event.source_version == proposal["id"]
            and event.expected_epoch == run.epoch
            and event.cursor == run.cursor,
            "durable_approval_event_invalid",
        )
        deliveries = list(
            db.scalars(select(TaskOutbox).where(TaskOutbox.status == "pending"))
        )
        require(
            len(deliveries) == 1
            and deliveries[0].task_name == CONTINUE
            and deliveries[0].task_id == str(event.id),
            "durable_approval_outbox_invalid",
        )
    try:
        with patch.object(tasks.celery_app, "send_task", side_effect=dispatch.enqueue):
            await dispatch.drain(tasks, timeout_seconds=180)
        with get_session_factory()() as db:
            run = dispatch.bound_run(db)
            pending = list(
                db.scalars(
                    select(WorkbenchContinuation.id).where(
                        WorkbenchContinuation.run_id == run.id,
                        WorkbenchContinuation.status.in_(["pending", "running"]),
                    )
                )
            )
            outbox = list(
                db.scalars(select(TaskOutbox.id).where(TaskOutbox.status == "pending"))
            )
            report["approval_continuation_remaining"] = len(pending)
            report["approval_outbox_remaining"] = len(outbox)
            require(
                run.status == "completed"
                and run.cursor == len(run.plan["steps"])
                and not pending
                and not outbox,
                "durable_approval_not_completed",
            )
    finally:
        report["continuation_tasks_executed"] = (
            report.get("continuation_tasks_executed", 0) + dispatch.executed
        )
        try:
            report["approval_continuation_terminal"] = dispatch.safe_state()
            from casepilot_api.workbench_tool_diagnostics import safe_tool_diagnostic

            with get_session_factory()() as db:
                observed = db.get(WorkbenchContinuation, event.id)
                report["approval_event_status"] = (
                    observed.status
                    if observed.status
                    in {
                        "pending",
                        "running",
                        "completed",
                        "invalidated",
                        "failed",
                        "cancelled",
                    }
                    else "unknown"
                )
                code = (observed.receipt or {}).get("error_code")
                report["approval_binding_code"] = (
                    code
                    if type(code) is str
                    and code
                    in {
                        "workbench_run_authority_changed",
                        "workbench_run_binding_changed",
                        "workbench_legacy_scope_requires_reselection",
                        "workbench_run_source_changed",
                    }
                    else "unknown"
                )
                report["approval_event_diagnostic"] = safe_tool_diagnostic(
                    {"http_detail_code": (observed.receipt or {}).get("error_code")}
                )
        except Exception:  # noqa: BLE001 - diagnostics cannot replace the original failure
            report["approval_continuation_terminal"] = {"diagnostic_unavailable": True}
