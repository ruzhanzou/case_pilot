#!/usr/bin/env python3
"""Opt-in fresh synthetic NL -> actual SDK/API -> one draft worker planning probe.

No test_setup injection, approval, generation/adoption or continuous-chain claim.
Hard cap: 16 provider transport attempts, including retries; larger budgets are rejected.
Use a fresh rootless DB with CASEPILOT_QA_MARK_SYNTHETIC=1. Never resumes a database.
Artifact saved means only typed planning evidence; quality requires independent review.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from pydantic import Field
from workbench_agent_live_acceptance import (
    ROOT,
    RequestBudget,
    SafetyStop,
    bounded_clients,
    disable_sensitive_logging,
    emit_json,
    exception_name,
    parser,
    read_key,
    set_stage,
)
from workbench_agent_live_journey import configuration_overrides
from workbench_domain_diagnostics import emit_domain_failure, safe_domain_failure
from workbench_planning_quality_probe import (
    FIXTURE_VERSION,
    RULES,
    RULES_SHA256,
    TEST_SETUP,
    PlanningArtifact,
    artifact_path,
)
from workbench_safe_diagnostics import safe_structured_failure

sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "apps/agent/src")]

PROMPT = ("请为以下合成 OTP 验证需求生成测试规划（功能点和测试点），"
          "准确覆盖正常、边界、异常及跨规则场景；保留依据，不推测未知规则。"
          "本次仅到测试规划草稿供人审，不生成或采纳正式用例，不指定测试点数量。\n"
          + "\n".join(f"{key}: {value}" for key, value in RULES.items())
          + "\n" + "\n".join(TEST_SETUP))
PROMPT_SHA256 = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
CODES = frozenset({"sampling_probe_protocol_status", "sampling_probe_fresh_database_required",
    "sampling_probe_single_draft_required", "sampling_probe_prompt_changed",
    "sampling_probe_worker_not_completed", "sampling_probe_samples_missing",
    "sampling_probe_sampling_not_from_user", "sampling_probe_formal_write",
    "sampling_probe_plan_missing", "sampling_probe_artifact_size"})


class ProbeFailure(Exception):
    def __init__(self, code):
        if code not in CODES:
            raise ValueError("invalid_probe_failure_code")
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise ProbeFailure(code)


class SamplingArtifact(PlanningArtifact):
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    original_prompt_fixture_sha256: Literal[PROMPT_SHA256] = PROMPT_SHA256
    fixture_version: Literal[FIXTURE_VERSION] = FIXTURE_VERSION
    rules_sha256: Literal[RULES_SHA256] = RULES_SHA256


def write_artifact(path, artifact):
    validated = SamplingArtifact.model_validate(artifact)
    data = validated.model_dump_json(indent=2).encode("utf-8")
    require(len(data) <= 2_000_000, "sampling_probe_artifact_size")
    path = artifact_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return path


def emit_structured_failure(value):
    error = type("ModelBehaviorError", (Exception,), {})()
    error.casepilot_safe_diagnostic = value
    safe = safe_structured_failure(error)
    if safe:
        emit_json({"event": "structured_attempt_failed", "diagnostic": safe,
                   "scope": "nl_planning_only"})


def has_user_sampling_sample(artifact):
    points = {point.id: point for point in artifact.test_points}
    for batch in artifact.coverage_review.batches:
        for obligation in batch.obligations:
            contract = obligation.boundary_contract
            if (contract is None or contract.sampling_step != 1
                    or not contract.sampling_literal.strip()
                    or contract.sampling_literal not in PROMPT):
                continue
            for point_id in obligation.point_ids:
                point = points.get(point_id)
                if point is not None and any(
                    sample.obligation_id == obligation.id
                    and (sample.unit, sample.axis, sample.time_origin)
                    == (contract.unit, contract.axis, contract.time_origin)
                    for sample in point.boundary_samples or []
                ):
                    return True
    return False


async def protocol(client, report, source_commit):
    from casepilot_agent import tasks
    from casepilot_agent.planning_boundary import sampling_instruction_sources
    from casepilot_agent.providers.safe_diagnostics import observe_structured_failures
    from casepilot_api import conversations
    from casepilot_api.database import get_session_factory
    from casepilot_api.models import GenerationJob, TestCase, TestCaseRevision
    from sqlalchemy import select

    async def call(method, path, body=None, status=200):
        response = await client.request(method, "/api/v1" + path, json=body)
        require(response.status_code == status, "sampling_probe_protocol_status")
        return response.json()

    queue = []

    def enqueue(db, name, args, **kwargs):
        require(name == "casepilot.agent.draft_brief" and len(args) == 1,
                "sampling_probe_single_draft_required")
        queue.append((name, str(args[0])))

    job_id = None
    try:
        account = await call("POST", "/auth/register", {
            "email": f"sampling-synthetic-{uuid4().hex}@casepilot.test",
            "display_name": "Synthetic sampling probe", "password": "CasePilot123!"}, 201)
        collection = await call("POST", f"/spaces/{account['spaces'][0]['id']}/collections",
                                {"name": "Synthetic OTP planning only"}, 201)
        workspace = await call("POST", "/conversations", {"collection_id": collection["id"]}, 201)
        cid = workspace["id"]
        report["workspace_id"] = cid
        factory = get_session_factory()
        with factory() as db:
            original_cases = set(db.scalars(select(TestCase.id)))
            original_revisions = set(db.scalars(select(TestCaseRevision.id)))
            original_jobs = set(db.scalars(select(GenerationJob.id)))
        set_stage("nl_sampling_submit")
        report["last_stage"] = "nl_submit"
        with patch.object(conversations, "enqueue_task", enqueue):
            turn = await call("POST", f"/conversations/{cid}/messages", {
                "content": PROMPT, "client_request_id": str(uuid4())}, 202)
        job_id = turn.get("action", {}).get("job_id")
        require(job_id and queue == [("casepilot.agent.draft_brief", job_id)],
                "sampling_probe_single_draft_required")
        with factory() as db:
            job = db.get(GenerationJob, UUID(job_id))
            require(job.input_payload["prompt"] == PROMPT, "sampling_probe_prompt_changed")
            require(not job.input_payload.get("test_setup"), "sampling_probe_prompt_changed")
            require(sampling_instruction_sources(job.input_payload["prompt"]) == [
                {"origin": "user_input", "text": PROMPT}], "sampling_probe_sampling_not_from_user")
        emit_json({"event": "sampling_probe_gate", "stage": "actual_nl_job_prepared"})
        report["last_stage"] = "draft_worker"
        set_stage("sampling_draft_worker")
        with observe_structured_failures(emit_structured_failure):
            await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        view = await call("GET", f"/conversations/{cid}")
        require(bool(view.get("test_briefs")), "sampling_probe_plan_missing")
        plan = view["test_briefs"][-1]["content"].get("planning") or {}
        require(all(key in plan for key in PlanningArtifact.model_fields),
                "sampling_probe_plan_missing")
        artifact = SamplingArtifact.model_validate({
            **{key: plan[key] for key in PlanningArtifact.model_fields},
            "source_commit": source_commit})
        samples = [sample for point in artifact.test_points for sample in point.boundary_samples or []]
        require(bool(samples), "sampling_probe_samples_missing")
        require(has_user_sampling_sample(artifact), "sampling_probe_sampling_not_from_user")
        with factory() as db:
            require(db.get(GenerationJob, UUID(job_id)).status == "completed",
                    "sampling_probe_worker_not_completed")
            require(set(db.scalars(select(GenerationJob.id))) - original_jobs == {UUID(job_id)},
                    "sampling_probe_single_draft_required")
            require(set(db.scalars(select(TestCase.id))) == original_cases and
                    set(db.scalars(select(TestCaseRevision.id))) == original_revisions,
                    "sampling_probe_formal_write")
        require(not view.get("candidates"), "sampling_probe_formal_write")
        report.update(protocol_passed=True, worker_count=1,
                      feature_count=len(artifact.feature_points), point_count=len(artifact.test_points),
                      sample_count=len(samples), last_stage="typed_planning_ready")
        emit_json({"event": "sampling_probe_gate", "stage": "typed_planning_ready",
                   "sample_count": len(samples)})
        return artifact
    except Exception as error:
        emit_domain_failure(error, emit_json, job_id=job_id)
        raise


async def execute(key, model, budget, report, storage):
    from casepilot_agent import tasks
    from casepilot_agent.config import get_settings as worker_settings
    from casepilot_api.config import get_settings as api_settings
    from casepilot_api.database import get_session_factory
    from casepilot_api.main import app
    from casepilot_api.models import Account
    from sqlalchemy import func, select
    from workbench_qa_checkpoint import database_identity

    commit = (await asyncio.to_thread(
        subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)).strip()
    with get_session_factory()() as db:
        database_identity(db.connection(), commit)
        require(db.scalar(select(func.count()).select_from(Account)) == 0,
                "sampling_probe_fresh_database_required")
    with ExitStack() as stack:
        for settings, values in zip((api_settings(), worker_settings()),
                                   configuration_overrides(key, model, storage), strict=True):
            for name, value in values.items():
                stack.enter_context(patch.object(settings, name, value))
        stack.enter_context(patch.object(tasks.celery_app, "send_task",
                                         side_effect=RuntimeError("external_dispatch_blocked")))
        async with bounded_clients(key, budget), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://synthetic.test"
        ) as client:
            return await protocol(client, report, commit)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=16)
    arguments.add_argument("--artifact-path", required=True, help="New .json only; exclusive private write")
    arguments.add_argument("--storage-dir", default=str(Path(tempfile.gettempdir()) /
                                                        "casepilot-nl-sampling-probe"))
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {"event": "summary", "scope": "nl_planning_only", "protocol_passed": False,
              "setup_collection_scripted": True, "no_formal_adoption": True,
              "continuous_chain_passed": False, "resume_allowed": False, "quality_status": "quality_pending_manual",
              "artifact_saved": False, "fixture_version": FIXTURE_VERSION,
              "rules_sha256": RULES_SHA256, "original_prompt_fixture_sha256": PROMPT_SHA256}
    try:
        if not 1 <= args.max_requests <= 16:
            raise SafetyStop("planning_probe_budget_invalid")
        path = artifact_path(args.artifact_path)
        key = read_key(args)
        artifact = asyncio.run(execute(key, args.model, budget, report, args.storage_dir))
        path = write_artifact(path, artifact)
        report.update(artifact_saved=True, artifact_path=str(path), source_commit=artifact.source_commit)
    except Exception as error:  # noqa: BLE001 -- no model/body/key/error text.
        emit_domain_failure(error, emit_json)
        report["error_code"] = (budget.stop_code or
                                (error.code if isinstance(error, ProbeFailure)
                                 else "nl_sampling_probe_failed"))
        report["exception_class"] = exception_name(error)
        report["domain_failure"] = safe_domain_failure(error)
        diagnostic = safe_structured_failure(error)
        if diagnostic:
            report["structured_failure"] = diagnostic
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["artifact_saved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
