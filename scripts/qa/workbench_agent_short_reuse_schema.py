#!/usr/bin/env python3
"""Fresh synthetic second-draft schema probe, NOT a live NL/full-generation journey.

Setup uses deterministic model seams, real ASGI approval endpoints and first worker.
Second draft uses the configured provider; --through-generation also runs the actual
generation worker, exact human brief approval and candidate adoption. Setup stays scripted.
No DB start/resume.
Requires a newly initialized, unused DB from rootless run_with_services.sh with
CASEPILOT_QA_MARK_SYNTHETIC=1; existing/previous-run databases are rejected.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
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
    set_stage,
)
from workbench_agent_live_journey import configuration_overrides, require
from workbench_domain_diagnostics import emit_domain_failure, safe_domain_failure
from workbench_safe_diagnostics import safe_structured_failure

sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "apps/agent/src")]


class SetupControl:
    """Deterministic setup only; never presented as natural-language model evidence."""
    def __init__(self, title):
        self.title, self.index = title, 0

    def complete(self, messages, tools, instructions):
        from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolCall
        calls = [("query_assets", {"search": self.title, "scope": "space"}),
                 ("prepare_reuse", {"strategy": "select_and_generate", "plan": {
                     "steps": ["CASE_REUSE"], "plan_actions": ["CASE_REUSE"]}})]
        if self.index < len(calls):
            name, args = calls[self.index]
            self.index += 1
            return ModelTurn(calls=[ToolCall(str(self.index), name, json.dumps(args))])
        outputs = [json.loads(item["output"]) for item in messages
                   if item.get("type") == "function_call_output"]
        receipt = [item["_receipt"] for item in outputs if item.get("_receipt")][-1]
        return ModelTurn(final=FinalAnswer(kind="action", message="请确认精确预览。",
            effect=receipt["effect"], receipt_ids=[receipt["id"]]))


def setup_provider():
    from casepilot_agent.contracts import RequirementAnalysis
    from casepilot_agent.providers.mock import MockProvider

    class SetupProvider(MockProvider):
        def complete(self, *, result_type, **kwargs):
            result, usage = super().complete(result_type=result_type, **kwargs)
            if issubclass(result_type, RequirementAnalysis):
                result.test_object = "Account system"
                result.test_object_specified = True
                result.open_questions = []
            return result, usage
    return SetupProvider()


async def protocol(client, report, *, second_provider=None, through_generation=False):
    """Actual protocol shared by paid short probe and offline PG verification."""
    from casepilot_agent import tasks
    from casepilot_api import conversations, workbench_tools
    from casepilot_api.database import get_session_factory
    from casepilot_api.generation_strategy import interpret_generation_choice
    from casepilot_api.models import (
        AuditEvent,
        GenerationJob,
        TestCase,
        TestCaseRevision,
    )
    from sqlalchemy import select

    async def call(method, path, body=None, status=200, owner=None):
        response = await (owner or client).request(method, "/api/v1" + path, json=body)
        require(response.status_code == status, "short_reuse_protocol_status")
        return response.json()

    async def identity(owner=None):
        account = await call("POST", "/auth/register", {
            "email": f"short-reuse-{uuid4().hex}@casepilot.test",
            "display_name": "Synthetic schema probe", "password": "CasePilot123!"}, 201, owner)
        collection = await call("POST", f"/spaces/{account['spaces'][0]['id']}/collections",
                                {"name": "Synthetic source"}, 201, owner)
        return account, collection

    account, origin = await identity()
    source = await call("POST", f"/collections/{origin['id']}/test-cases", {
        "title": "SYNTHETIC original valid-code login", "module": "Account system",
        "priority": "P1", "case_type": "functional", "preconditions": ["Registered account"],
        "steps": [{"action": "Login with valid code", "expected": "Success"}]}, 201)
    from casepilot_api.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://synthetic.test") as outsider:
        _, foreign_collection = await identity(outsider)
        foreign = await call("POST", f"/collections/{foreign_collection['id']}/test-cases", {
            "title": "SYNTHETIC foreign decoy", "module": "Account system", "priority": "P1",
            "case_type": "functional", "preconditions": ["Registered account"],
            "steps": [{"action": "Login with valid code", "expected": "Success"}]}, 201, outsider)
    workspace = await call("POST", "/conversations", {"space_id": account["spaces"][0]["id"]}, 201)
    cid = workspace["id"]
    report["workspace_ids"].append(cid)
    factory = get_session_factory()
    with factory() as db:
        original_ids = set(db.scalars(select(TestCase.id)))
        original_revisions = set(db.scalars(select(TestCaseRevision.id)))
        original_audits = set(db.scalars(select(AuditEvent.id).where(
            AuditEvent.resource_id.in_(original_ids))))
    choice = interpret_generation_choice("策略：select_and_generate。测试对象：Account system",
                                        SimpleNamespace(agent_provider="mock"))
    choice.test_object = "Account system"
    with ExitStack() as setup:
        setup.enter_context(patch.object(conversations, "interpret_generation_choice",
                                         lambda *a, **kw: choice))
        setup.enter_context(patch.object(conversations.settings, "workbench_agent_enabled", True))
        setup.enter_context(patch.object(conversations.settings, "agent_provider", "openai_compatible"))
        setup.enter_context(patch.object(workbench_tools, "make_provider",
                                         lambda *a: SetupControl(source["title"])))
        setup.enter_context(patch.object(tasks, "create_provider", lambda *a, **kw: setup_provider()))
        turn = await call("POST", f"/conversations/{cid}/messages", {
            "content": "测试对象：Account system。原样复用 SYNTHETIC original valid-code login "
                       "这1条主流程，再新增1条验证码无效的异常缺口，共2条用例和2个测试点，组成新集合。",
            "source_collection_ids": [origin["id"]], "client_request_id": str(uuid4())}, 202)
        operation = turn["operation_plan"]["operations"][0]
        require(operation["payload"]["prepared_request"]["generation_strategy"] ==
                "select_and_generate", "short_reuse_strategy")
        endpoint = f"/conversation-operations/{operation['id']}/confirm-collection"
        blocked = await call("POST", endpoint, {"collection_id": origin["id"]}, 422)
        require(blocked["detail"] == "generation_new_collection_required", "short_reuse_destination")
        name = {"create_collection_name": "Synthetic mixed reuse schema"}
        confirmed = await call("POST", endpoint, name, 202)
        replay = await call("POST", endpoint, name, 202)
        require(replay["action"] == confirmed["action"], "short_reuse_replay")
        await asyncio.to_thread(tasks.draft_test_brief.run, confirmed["action"]["job_id"])
        state = await call("GET", f"/conversations/{cid}")
        brief = state["test_briefs"][-1]
        require(brief["content"]["asset_selection"]["status"] == "awaiting_confirmation",
                "short_reuse_asset_review")
        endpoint = f"/workspaces/{cid}/generation-assets/confirm"
        await call("POST", endpoint, {"version": brief["version"] + 999,
                                      "case_ids": [source["id"]]}, 409)
        await call("POST", endpoint, {"version": brief["version"],
                                      "case_ids": [foreign["id"]]}, 422)
        approved = await call("POST", endpoint, {"version": brief["version"],
                                                "case_ids": [source["id"]]})
    job_id = approved["action"]["job_id"]
    with factory() as db:
        job = db.get(GenerationJob, UUID(job_id))
        require(job.input_payload["asset_selection_confirmed"] is True, "short_reuse_asset_binding")
        require(str(job.collection_id) != origin["id"], "short_reuse_destination")
    report["checks"].append({"check": "deterministic_setup_real_approval_protocol", "passed": True})
    report["last_stage"] = "second_draft_worker_pending"
    set_stage("brief_worker")
    emit_json({"event": "short_schema_gate", "stage": report["last_stage"],
               "workspace_id": cid, "job_id": job_id, "live_nl_chain": False})
    from casepilot_agent.providers.safe_diagnostics import observe_structured_failures
    try:
        with ExitStack() as worker:
            worker.enter_context(observe_structured_failures(emit_structured_failure))
            if second_provider is not None:  # Explicit offline test seam only.
                worker.enter_context(patch.object(tasks, "create_provider", lambda *a, **kw: second_provider))
            await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        report["last_stage"] = "second_draft_worker_completed"
        state = await call("GET", f"/conversations/{cid}")
        plan = state["test_briefs"][-1]["content"]["planning"]
        if "pending_reserved_outputs" in plan:
            pending = safe_pending_clarification(plan["pending_reserved_outputs"],
                                                 generated_point_count=len(plan["test_points"]))
            report["last_stage"] = "second_draft_pending_clarification"
            report["pending_clarification"] = pending
            emit_json({"event": "pending_reserved_clarification", **pending})
            require(False, "short_reuse_pending_clarification")
        key = f"asset:{source['id']}"
        require([row["key"] for row in plan["approved_source_catalog"]] == [key], "short_reuse_catalog")
        require(plan["approved_source_catalog"][0]["revision"] == source["current_revision_id"],
                "short_reuse_source_revision")
        obligations = plan["output_obligations"]
        require(obligations["required_reuse_source_keys"] == [key] and
                obligations["output_case_count"] == 2 and obligations["new_case_count"] == 1,
                "short_reuse_quantity")
        require(len(plan["test_points"]) == 2, "short_reuse_decisions")
        reservations = plan.get("reserved_reuse_outputs", [])
        if reservations:
            require(len(reservations) == 1 and reservations[0]["action"] == "reuse"
                    and reservations[0]["source"]["key"] == key
                    and reservations[0]["source"]["revision"] == source["current_revision_id"],
                    "short_reuse_source_revision")
            reserved_points = set(reservations[0]["point_ids"])
            point_ids = {point["id"] for point in plan["test_points"]}
            require(bool(reserved_points) and reserved_points < point_ids,
                    "short_reuse_decisions")
            gap_decisions = [item for item in plan["reuse"]["decisions"]
                             if item["point_id"] not in reserved_points]
            require(len(gap_decisions) == 1 and gap_decisions[0]["action"] == "new",
                    "short_reuse_decisions")
        else:
            require(plan["reuse"]["summary"] == {"reuse": 1, "new": 1}, "short_reuse_decisions")
        require(not state["candidates"], "short_reuse_unapproved_candidates")
        with factory() as db:
            require(db.get(GenerationJob, UUID(job_id)).status == "completed", "short_reuse_worker_status")
            require(set(db.scalars(select(TestCase.id))) == original_ids and
                    set(db.scalars(select(TestCaseRevision.id))) == original_revisions,
                    "short_reuse_formal_write")
            require(set(db.scalars(select(AuditEvent.id).where(
                AuditEvent.resource_id.in_(original_ids)))) == original_audits,
                "short_reuse_asset_audit_write")
        report["checks"].append({"check": "second_draft_exact_source_and_gap_schema", "passed": True})
        if through_generation:
            brief = state["test_briefs"][-1]
            await call("POST", f"/workspaces/{cid}/test-briefs/confirm",
                       {"version": brief["version"] - 1}, 409)
            approved_points = await call("POST", f"/workspaces/{cid}/test-briefs/confirm",
                {"version": brief["version"],
                 "selected_test_point_ids": [point["id"] for point in plan["test_points"]]}, 202)
            job_id = approved_points["action"]["job_id"]
            with factory() as db:
                job = db.get(GenerationJob, UUID(job_id))
                confirmed_plan = job.input_payload["confirmed_plan"]
                receipt = confirmed_plan["point_review_receipt"]
                require(receipt["brief_id"] == brief["id"] and
                        receipt["version"] == brief["version"] and
                        set(receipt["point_ids"]) == {p["id"] for p in plan["test_points"]},
                        "short_reuse_point_receipt")
                require(set(db.scalars(select(TestCase.id))) == original_ids,
                        "short_reuse_formal_write")
            report["last_stage"] = "generation_worker_pending"
            set_stage("generation_worker")
            emit_json({"event": "short_schema_gate", "stage": report["last_stage"],
                       "job_id": job_id, "live_nl_chain": False})
            with ExitStack() as worker:
                worker.enter_context(observe_structured_failures(emit_structured_failure))
                if second_provider is not None:  # Explicit offline seam, never enabled by CLI.
                    worker.enter_context(patch.object(tasks, "create_provider",
                                                     lambda *a, **kw: second_provider))
                await asyncio.to_thread(tasks.generate_test_cases.run, job_id)
            state = await call("GET", f"/conversations/{cid}")
            candidates = state["candidates"]
            require(len(candidates) == 2, "short_reuse_candidate_count")
            reused = [c for c in candidates if c["snapshot"]["title"] == source["title"]]
            require(len(reused) == 1, "short_reuse_original_snapshot")
            snapshot = reused[0]["snapshot"]
            require(all(snapshot[field] == source[field] for field in
                        ("title", "module", "priority", "preconditions")) and
                    snapshot["steps"] == [{k: step[k] for k in ("action", "expected")}
                                          for step in source["steps"]],
                    "short_reuse_original_snapshot")
            gap = next(c for c in candidates if c["id"] != reused[0]["id"])
            approved_refs = [ref for point in confirmed_plan["test_points"]
                             if point["id"] not in {pid for row in reservations
                                                    for pid in row["point_ids"]}
                             for ref in point.get("source_refs", [])]
            gap_refs = gap["snapshot"].get("source_refs", [])
            require(bool(gap_refs) and all(ref in approved_refs for ref in gap_refs),
                    "short_reuse_gap_provenance")
            with factory() as db:
                require(db.get(GenerationJob, UUID(job_id)).status == "completed",
                        "short_reuse_worker_status")
                require(set(db.scalars(select(TestCase.id))) == original_ids,
                        "short_reuse_formal_write")
            exact = {"candidate_ids": [c["id"] for c in candidates],
                     "candidate_versions": {c["id"]: c["version"] for c in candidates}}
            endpoint = f"/workspaces/{cid}/candidates/commit"
            await call("POST", endpoint, {**exact, "candidate_versions": {
                c["id"]: c["version"] + 1 for c in candidates}}, 409)
            adopted = await call("POST", endpoint, exact)
            require(len(adopted) == 2 and source["id"] in {c["id"] for c in adopted},
                    "short_reuse_adoption_exact_source")
            # Existing commit protocol rejects a duplicate exact approval; it must not write again.
            await call("POST", endpoint, exact, 409)
            with factory() as db:
                require(len(set(db.scalars(select(TestCase.id))) - original_ids) == 1,
                        "short_reuse_adoption_exact_source")
                require(set(db.scalars(select(TestCaseRevision.id).where(
                    TestCaseRevision.test_case_id.in_(original_ids)))) == original_revisions,
                    "short_reuse_formal_write")
                require(set(db.scalars(select(AuditEvent.id).where(
                    AuditEvent.resource_id.in_(original_ids)))) == original_audits,
                    "short_reuse_asset_audit_write")
            report["last_stage"] = "generation_and_exact_adoption_completed"
            report["checks"].append({"check": "actual_generation_exact_source_plus_gap_adoption",
                                     "passed": True})
        return job_id
    except Exception as error:
        emit_domain_failure(error, emit_json, job_id=job_id)
        raise



def safe_pending_clarification(value, *, generated_point_count=0):
    pending = value if isinstance(value, dict) else {}
    reason = pending.get("reason")
    allowed = {"reserved_reuse_mapping_requires_clarification",
               "reserved_reuse_point_budget_requires_clarification"}
    sources = pending.get("required_sources")
    quantity = pending.get("quantity")
    quantity = quantity if isinstance(quantity, dict) else {}
    return {
        "reason": reason if type(reason) is str and reason in allowed else "unrecognized",
        "required_source_count": len(sources) if isinstance(sources, list) else 0,
        "reserved_source_count": len(sources) if isinstance(sources, list) else 0,
        "fixture_requested_total_points": 2,
        **({"interpreted_test_point_count": quantity["test_point_count"]}
           if type(quantity.get("test_point_count")) is int
           and 0 <= quantity["test_point_count"] <= 100000 else {}),
        **({"generated_point_count": generated_point_count}
           if type(generated_point_count) is int and 0 <= generated_point_count <= 100000 else {}),
        "quantity": {key: quantity[key] for key in
                     ("case_count", "test_point_count", "output_case_count", "new_case_count")
                     if type(quantity.get(key)) is int and 0 <= quantity[key] <= 100000},
    }


def emit_structured_failure(diagnostic):
    # Treat even the observer's attached mapping as untrusted at the log boundary.
    error = type("ModelBehaviorError", (Exception,), {})()
    error.casepilot_safe_diagnostic = diagnostic
    safe = safe_structured_failure(error)
    if safe is not None:
        emit_json({"event": "structured_attempt_failed", "diagnostic": safe,
                   "scope": "short_second_draft_worker_schema_only"})


async def execute(key, model, budget, report, storage, *, through_generation=False):
    from casepilot_agent import tasks
    from casepilot_agent.config import get_settings as worker_settings
    from casepilot_api import conversations
    from casepilot_api.config import get_settings as api_settings
    from casepilot_api.database import get_session_factory
    from casepilot_api.main import app
    from casepilot_api.models import Account
    from sqlalchemy import func, select
    from workbench_qa_checkpoint import database_identity

    # A marker plus an unused synthetic database is mandatory; never resume old fixtures.
    commit = (await asyncio.to_thread(
        subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)).strip()
    with get_session_factory()() as db:
        database_identity(db.connection(), commit)
        require(db.scalar(select(func.count()).select_from(Account)) == 0,
                "short_reuse_requires_fresh_database")
    with ExitStack() as stack:
        for settings, values in zip((api_settings(), worker_settings()),
                                   configuration_overrides(key, model, storage), strict=True):
            for name, value in values.items():
                stack.enter_context(patch.object(settings, name, value))
        stack.enter_context(patch.object(conversations, "enqueue_task", lambda *a, **kw: None))
        stack.enter_context(patch.object(tasks.celery_app, "send_task",
                                         side_effect=RuntimeError("external_dispatch_blocked")))
        async with bounded_clients(key, budget), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        ) as client:
            await protocol(client, report, through_generation=through_generation)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=16)
    arguments.add_argument("--storage-dir", default=str(Path(tempfile.gettempdir()) /
                                                        "casepilot-short-reuse-schema"))
    arguments.add_argument("--through-generation", action="store_true",
                           help="Also run actual generation and exact candidate approval/adoption")
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {"event": "summary", "scope": "short_second_draft_worker_schema_only",
              "passed": False, "checks": [], "workspace_ids": [], "live_nl_chain": False,
              "setup_scripted": True, "setup_provider": "deterministic",
              "continuous_chain_passed": False, "resume_allowed": False, "through_generation": args.through_generation}
    if args.through_generation:
        report["scope"] = "short_second_draft_through_generation_and_adoption"
    try:
        key = read_key(args)
        asyncio.run(execute(key, args.model, budget, report, args.storage_dir,
                            through_generation=args.through_generation))
        report["passed"] = len(report["checks"]) == (3 if args.through_generation else 2)
    except Exception as error:  # noqa: BLE001 -- No model text or exception messages.
        report["error_code"] = budget.stop_code or "short_reuse_schema_failed"
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
