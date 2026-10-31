#!/usr/bin/env python3
"""Opt-in synthetic durable continuation journey; only the lead may run live.

Uses the existing bounded/redacted Responses transport. Credentials are consumed
only from explicitly opted-in noninteractive stdin, never discovered or persisted.
Requires a fresh migrated local PostgreSQL/Redis instance. The real transactional
outbox dispatcher delivers to an in-process broker substitute; actual domain tasks
and continuation executor run unchanged. No fabricated effects or user messages.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from collections import deque
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from workbench_agent_live_acceptance import (
    ROOT,
    RequestBudget,
    bounded_clients,
    disable_sensitive_logging,
    emit_json,
    exception_name,
    parser,
    read_key,
)
from workbench_agent_live_journey import (
    Journey,
    configuration_overrides,
    exact_candidate_commit,
    require,
    turn_has_tool,
)
from workbench_domain_diagnostics import safe_domain_failure
from workbench_safe_diagnostics import safe_structured_failure

TASKS = {
    "casepilot.agent.draft_brief": "draft_test_brief",
    "casepilot.agent.generate": "generate_test_cases",
    "casepilot.agent.answer_question": "answer_knowledge_question",
}
CONTINUE = "casepilot.workbench.continue"


class DurableDispatch:
    """Replace broker transport only, retaining actual committed outbox routing."""
    task_methods = TASKS

    def __init__(self, cid):
        self.cid = UUID(cid)
        self.queue = deque()
        self.executed = 0
        self.continuation_ids = []

    def enqueue(self, name, args, **kwargs):
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import (
            GenerationJob,
            WorkbenchContinuation,
            WorkbenchRun,
        )

        require(name in {*self.task_methods, CONTINUE} and len(args) == 1, "unexpected_task_dispatch")
        identifier = UUID(str(args[0]))
        with get_session_factory()() as db:
            if name == CONTINUE:
                event = db.get(WorkbenchContinuation, identifier)
                run = db.get(WorkbenchRun, event.run_id) if event else None
                require(run is not None and run.conversation_id == self.cid,
                        "outbox_continuation_scope_mismatch")
                require(kwargs.get("queue") == "workbench", "outbox_queue_mismatch")
            else:
                job = db.get(GenerationJob, identifier)
                require(job is not None and str(job.input_payload.get("conversation_id")) == str(self.cid),
                        "outbox_domain_scope_mismatch")
        self.queue.append((name, str(identifier)))

    async def drain(self, tasks, *, timeout_seconds=None, stop_when=None, before_dispatch=None):
        from casepilot_api.workbench_run_executor import execute_workbench_continuation

        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        while True:
            require(deadline is None or time.monotonic() < deadline, "durable_wait_timeout")
            if stop_when is not None and stop_when():
                break
            if before_dispatch is not None:
                before_dispatch()
            delivery = await asyncio.to_thread(tasks.dispatch_task_outbox.run)
            require(delivery.get("failed") == 0, "outbox_delivery_failed")
            if not self.queue:
                break
            while self.queue:
                require(deadline is None or time.monotonic() < deadline, "durable_wait_timeout")
                require(self.executed < 30, "worker_task_budget_exhausted")
                name, identifier = self.queue.popleft()
                if name == CONTINUE:
                    result = await asyncio.to_thread(execute_workbench_continuation, identifier)
                    self.continuation_ids.append(identifier)
                else:
                    result = await asyncio.to_thread(getattr(tasks, self.task_methods[name]).run, identifier)
                self.executed += 1
                require(not isinstance(result, dict) or result.get("status") not in {
                    "failed", "cancelled", "budget_exhausted", "invalidated", "obsolete", "busy",
                }, "durable_worker_failed")


def snapshot(cid):
    from casepilot_api.database import get_session_factory
    from casepilot_api.models import ConversationMessage, WorkbenchRun
    from sqlalchemy import func, select

    with get_session_factory()() as db:
        run = db.scalar(select(WorkbenchRun).where(WorkbenchRun.conversation_id == UUID(cid)))
        require(run is not None, "durable_run_missing")
        users = db.scalar(select(func.count()).select_from(ConversationMessage).where(
            ConversationMessage.conversation_id == UUID(cid), ConversationMessage.role == "user"))
        return {"id": str(run.id), "root": str(run.root_message_id), "status": run.status,
                "cursor": run.cursor, "plan": run.plan, "checkpoint": run.checkpoint,
                "used": run.used, "users": users}


def verify_final_query(run, workspace):
    steps = run.get("plan", {}).get("steps", [])
    require(bool(steps) and steps[-1].get("action") == "CASE_QUERY",
            "final_typed_query_step_missing")
    state = workspace.get("context", {}).get("workbench_agent", {})
    require(any(receipt.get("tool") == "query_assets" and receipt.get("effect") == "read"
                for receipt in state.get("receipts", [])), "automatic_query_receipt_missing")
    require(any(event.get("type") == "tool_completed" and event.get("tool") == "query_assets"
                and event.get("returned_count") == 2 for event in state.get("events", [])),
            "automatic_query_did_not_observe_two_adopted_cases")


class ContinuationJourney(Journey):
    async def run(self, budget):
        from casepilot_api.workbench_run_executor import execute_workbench_continuation

        user = await self.post("/auth/register", {
            "email": f"live-continuation-{uuid4().hex}@casepilot.test",
            "display_name": "Synthetic continuation QA", "password": "SyntheticFixture123!",
        })
        cid, _collection_id = await self.create_workspace(user["spaces"][0]["id"],
                                                          "Synthetic durable continuation")
        dispatch = DurableDispatch(cid)
        self.dispatch = dispatch
        # No other synthetic or user work is allowed into this isolated harness.
        with patch.object(self.tasks.celery_app, "send_task", dispatch.enqueue):
            self.stage = "generation_request"
            turn = await self.message(cid,
                "先查询当前集合内已有用例及数量。测试对象：合成验证码登录；有效验证码登录成功，错误验证码显示错误。"
                "然后新生成严格2条测试用例，先规划测试点供我确认，再生成候选供我人工采纳。"
                "我采纳后请在同一个持续任务中自动查询当前集合，核对两条用例的数量和标题并汇报；"
                "不要等我再发消息，不要替我确认、采纳或修改正式用例。不要查询外部资料。")
            require(turn_has_tool(turn, "query_assets"), "initial_query_receipt_missing")
            original = snapshot(cid)
            require(len(original["plan"].get("steps", [])) >= 2, "durable_multistep_plan_missing")
            require(original["users"] == 1, "initial_user_authority_duplicated")
            self.stage = "brief_worker"
            await dispatch.drain(self.tasks)
            after_brief = snapshot(cid)
            require(after_brief["status"] == "waiting_approval"
                    and after_brief["checkpoint"].get("waiting_artifact_kind") == "test_brief",
                    "durable_brief_review_gate_missing")
            require(after_brief["users"] == original["users"], "worker_fabricated_user_message")
            self.passed("durable_real_draft_worker_stops_for_exact_human_brief_review")
            calls = budget.count
            workspace = await self.workspace(cid)
            await self.workspace(cid)
            require(budget.count == calls, "get_triggered_provider_call")
            brief = workspace["test_briefs"][-1]
            self.stage = "brief_confirm"
            await self.post(f"/workspaces/{cid}/test-briefs/confirm",
                            {"version": brief["version"], "model_id": self.model})
            self.stage = "generation_worker"
            await dispatch.drain(self.tasks)
            workspace = await self.workspace(cid)
            require(len(workspace.get("candidates", [])) == 2, "generation_quantity_mismatch")
            state = snapshot(cid)
            require(state["status"] == "waiting_approval"
                    and state["checkpoint"].get("waiting_artifact_kind") == "candidates",
                    "durable_candidate_review_gate_missing")
            self.passed("durable_real_generation_worker_stops_for_exact_candidate_adoption")
            self.stage = "adoption"
            adopted = await self.post(f"/workspaces/{cid}/candidates/commit",
                                      exact_candidate_commit(workspace["candidates"]))
            require(len(adopted) == 2, "adoption_quantity_mismatch")
            revisions = {case["id"]: case["current_revision_id"] for case in adopted}
            approved = snapshot(cid)
            self.stage = "asset_query"
            calls = budget.count
            await dispatch.drain(self.tasks)
            final = snapshot(cid)
            require(final["status"] == "completed", "durable_plan_not_completed")
            require(final["cursor"] == len(final["plan"].get("steps", [])),
                    "durable_plan_cursor_not_terminal")
            require(final["used"].get("segments", 0) >= 2 and budget.count > calls,
                    "no_automatic_second_sdk_segment")
            require(final["root"] == original["root"] and final["users"] == approved["users"],
                    "continuation_fabricated_user_authority")
            final_workspace = await self.workspace(cid)
            verify_final_query(final, final_workspace)
            await self.assert_revisions(revisions)
            self.passed("same_original_request_automatically_continues_after_human_approval")
            require(bool(dispatch.continuation_ids), "continuation_receipts_missing")
            calls = budget.count
            for identifier in dispatch.continuation_ids:
                result = await asyncio.to_thread(execute_workbench_continuation, identifier)
                require(result["status"] == "ignored", "duplicate_continuation_not_ignored")
            require(budget.count == calls, "duplicate_continuation_called_provider")
            await self.assert_revisions(revisions)
            self.passed("duplicate_durable_events_no_model_charge_or_revision_change")
            self.report.update({"durable_run_id": final["id"], "durable_steps": final["cursor"],
                                "durable_budget_used": final["used"],
                                "worker_tasks_executed": dispatch.executed})


async def execute(key, model, budget, report, storage):
    sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "apps/agent/src")]
    from agents import set_tracing_disabled
    from casepilot_agent.config import get_settings as agent_settings
    from casepilot_api.config import get_settings as api_settings

    set_tracing_disabled(True)
    with ExitStack() as stack:
        for settings, values in zip((api_settings(), agent_settings()),
                                     configuration_overrides(key, model, storage), strict=True):
            for name, value in values.items():
                stack.enter_context(patch.object(settings, name, value))
        from casepilot_agent import tasks
        from casepilot_api.main import app
        async with bounded_clients(key, budget), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test",
        ) as client:
            journey = ContinuationJourney(client, None, tasks, report, model)
            try:
                await journey.run(budget)
            finally:
                report["last_stage"] = journey.stage


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=60)
    arguments.add_argument("--storage-dir", default=str(Path(tempfile.gettempdir()) /
                                                        "casepilot-live-continuation"))
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {"event": "summary", "scope": "synthetic_live_durable_continuation",
              "passed": False, "browser_ui_tested": False, "checks": [], "workspace_ids": []}
    key = ""
    try:
        require(args.key_stdin, "explicit_stdin_required")
        key = read_key(args)
        Path(args.storage_dir).mkdir(parents=True, exist_ok=True)
        asyncio.run(execute(key, args.model, budget, report, args.storage_dir))
        report["passed"] = len(report["checks"]) == 4
    except Exception as error:  # noqa: BLE001 -- redact every provider/domain failure
        # Exception messages, request payloads and model text may contain secrets.
        code = safe_domain_failure(error)["code"]
        report["error_code"] = budget.stop_code or (
            code if code != "unclassified_domain_failure" else "journey_failed")
        report["exception_class"] = exception_name(error)
        report["domain_failure"] = safe_domain_failure(error)
        diagnostic = safe_structured_failure(error)
        if diagnostic is not None:
            report["structured_failure"] = diagnostic
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
