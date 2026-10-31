#!/usr/bin/env python3
"""Opt-in synthetic OTP planning artifact probe; no NL, DB, approval or quality PASS.

Runs production build_planning, without an explicit point quota. Default hard cap:
8 HTTP attempts across feature/test-point calls and retries. Artifact generation
only supplies material for independent manual/oracle review, not proof of quality.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from workbench_agent_live_acceptance import (
    BASE_URL,
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
from workbench_agent_short_reuse_schema import emit_structured_failure
from workbench_domain_diagnostics import emit_domain_failure, safe_domain_failure
from workbench_planning_quality import RULES, SOURCE
from workbench_safe_diagnostics import safe_structured_failure

sys.path[:0] = [str(ROOT / "apps/agent/src")]

from casepilot_agent.contracts import (
    FeaturePoint,
    RequirementAnalysis,
    SourceRef,
    TestPoint,
)
from casepilot_agent.planning_boundary import BoundaryContract, BoundarySample


class ArtifactSource(SourceRef):
    model_config = ConfigDict(extra="forbid")


class ArtifactFeature(FeaturePoint):
    model_config = ConfigDict(extra="forbid")
    source_refs: list[ArtifactSource] = Field(default_factory=list)


class ArtifactBoundaryContract(BoundaryContract):
    @model_validator(mode="after")
    def canonical_only(self):
        if (self.source_ref is None or "source_slot" in self.model_fields_set
                or not self.source_ref.label.strip() or not self.source_ref.excerpt.strip()):
            raise ValueError("artifact_boundary_source_required")
        return self


class ArtifactBoundarySample(BoundarySample):
    @model_validator(mode="after")
    def canonical_only(self):
        if (self.assertion_source_ref is None
                or "assertion_source_slot" in self.model_fields_set
                or not self.assertion_source_ref.label.strip()
                or not self.assertion_source_ref.excerpt.strip()
                or not all(value.strip() for value in (self.unit, self.axis, self.time_origin))):
            raise ValueError("artifact_boundary_source_required")
        return self


class ArtifactPoint(TestPoint):
    model_config = ConfigDict(extra="forbid")
    source_refs: list[ArtifactSource] = Field(default_factory=list)
    boundary_samples: list[ArtifactBoundarySample] | None = None


class CoverageObligationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    feature_point_ids: list[str]
    dimension: Literal["normal", "boundary", "exception", "state"]
    basis: str
    point_ids: list[str]
    clarification: str = ""
    boundary_contract: ArtifactBoundaryContract | None = None

    @model_serializer(mode="wrap")
    def serialize_legacy_compatible(self, handler):
        data = handler(self)
        if self.boundary_contract is None:
            data.pop("boundary_contract", None)
        return data


class DuplicateSuggestionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point_ids: list[str]
    reason: str


class CoverageBatchArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_index: int = Field(ge=1)
    obligations: list[CoverageObligationArtifact]
    uncovered_ids: list[str]
    clarifications: list[str]
    duplicate_suggestions: list[DuplicateSuggestionArtifact]
    completion_attempted: bool
    warnings: list[str]


class CoverageLimitsArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_points: int = Field(ge=1)
    max_batches: int = Field(ge=1)
    max_completion_rounds: Literal[1]
    max_model_calls: int = Field(ge=1, le=96)


class CoverageArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending_independent_review"]
    source: Literal["model_proposed"]
    batches: list[CoverageBatchArtifact]
    limits: CoverageLimitsArtifact
    warnings: list[str]


class PlanningArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_points: list[ArtifactFeature]
    test_points: list[ArtifactPoint]
    coverage_review: CoverageArtifact


FIXTURE_VERSION = "otp-controlled-clock-v2"
# Test infrastructure assumptions, not additional product behavior or precision rules.
TEST_SETUP = (
    "测试设置：使用可控时钟按整数秒采样；这不是产品时间精度限制。",
    ("测试设置：可预置任意 issued_at 的新鲜 OTP 以隔离边界；这不是发送或重发能力，"
     "预置不会重置失败计数。"),
)
RULES_SHA256 = hashlib.sha256(json.dumps(
    RULES, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")).hexdigest()


def fixture():
    requirement = RequirementAnalysis(
        test_object="Synthetic OTP validation", test_object_specified=True,
        summary="只依据给定规则规划 OTP 正常、边界和异常测试点；保留准确依据，未知规则不得推测。",
        business_rules=[f"{key}: {value}" for key, value in RULES.items()],
        constraints=["不新增短信发送、重发冷却等未给定产品规则；不指定测试点数量。",
                     *TEST_SETUP],
    )
    context = {
        "test_setup": list(TEST_SETUP),
        "evidence": [{"source_id": key, "document_id": "synthetic-otp-rules",
                      "label": key, "locator": key, "excerpt": value}
                     for key, value in RULES.items()],
        "historical_cases": [deepcopy(SOURCE["snapshot"])],
    }
    return requirement, context


def plan(provider, model):
    from casepilot_agent.planning import build_planning
    from casepilot_agent.providers.safe_diagnostics import observe_structured_failures

    requirement, context = fixture()
    before = deepcopy((requirement, context))

    def complete(stage, instruction, payload, result_type):
        if stage not in {"feature.generated", "test_point.generated"}:
            raise SafetyStop("unexpected_planning_stage")
        call_stage = ("planning_coverage_completion"
                      if payload.get("coverage_completion") is True else stage)
        set_stage(call_stage)
        try:
            result, _ = provider.complete(stage=stage, instruction=instruction, payload=payload,
                                          result_type=result_type, model_id=model)
            # Revalidate at the production seam; never retain transport/raw output.
            return result_type.model_validate(result.model_dump(mode="json"))
        except Exception as error:
            emit_domain_failure(error, lambda event: emit_json({**event, "stage": call_stage}))
            raise

    try:
        with observe_structured_failures(emit_structured_failure):
            result = build_planning(requirement, context, complete, target_count=None)
        if (requirement, context) != before:
            raise SafetyStop("synthetic_fixture_mutated")
        return PlanningArtifact.model_validate({key: result[key]
                                               for key in PlanningArtifact.model_fields})
    except Exception as error:
        # Includes local coverage/provenance checks AFTER a successful model call.
        # Do not attribute these to a particular concurrent model stage.
        emit_domain_failure(error, lambda event: emit_json({**event, "phase": "planning_validation"}))
        raise


def artifact_path(value):
    path = Path(value)
    if path.suffix != ".json" or not path.name.isascii():
        raise SafetyStop("artifact_path_invalid")
    parent = path.absolute().parent
    resolved = parent.resolve(strict=True)
    if parent != resolved or not any(resolved.is_relative_to(root) for root in (ROOT, Path("/tmp"))):
        raise SafetyStop("artifact_path_invalid")
    path = resolved / path.name
    if path.exists() or path.is_symlink():
        raise SafetyStop("artifact_exists")
    return path


def write_artifact(path, artifact):
    validated = PlanningArtifact.model_validate(artifact)
    data = validated.model_dump_json(indent=2).encode()
    if len(data) > 2_000_000:
        raise SafetyStop("artifact_size_limit")
    path = artifact_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return path


async def execute(key, model, budget):
    from casepilot_agent.providers.agents_sdk import AgentsSdkProvider

    provider = AgentsSdkProvider(base_url=BASE_URL, api_key=key, model=model, pro_model=model,
        local_model=model, timeout=120, generation_timeout=120, api_type="responses",
        tracing_enabled=False)
    set_stage("generation_contract")
    async with bounded_clients(key, budget):
        return await asyncio.to_thread(plan, provider, model)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=8)
    arguments.add_argument("--artifact-path", required=True,
                           help="New .json under checkout or /tmp; no overwrite or symlink parent")
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {"event": "summary", "scope": "synthetic_planning_only",
              "fixture_version": FIXTURE_VERSION, "rules_sha256": RULES_SHA256,
              "same_input_ab_comparison": False,
              "setup_scripted": True, "database_used": False, "live_nl_chain": False,
              "formal_approval_tested": False, "continuous_chain_passed": False,
              "quality_status": "quality_pending_manual", "artifact_saved": False}
    try:
        if not 1 <= args.max_requests <= 8:
            raise SafetyStop("planning_probe_budget_invalid")
        path = artifact_path(args.artifact_path)
        key = read_key(args)
        artifact = asyncio.run(execute(key, args.model, budget))
        path = write_artifact(path, artifact)
        report.update(artifact_saved=True, artifact_path=str(path),
                      feature_count=len(artifact.feature_points), point_count=len(artifact.test_points))
    except Exception as error:  # noqa: BLE001 -- never expose messages or model bodies.
        emit_domain_failure(error, lambda event: emit_json({**event, "phase": "probe"}))
        report["domain_failure"] = safe_domain_failure(error)
        report["error_code"] = budget.stop_code or "planning_quality_probe_failed"
        report["exception_class"] = exception_name(error)
        diagnostic = safe_structured_failure(error)
        if diagnostic is not None:
            report["structured_failure"] = diagnostic
    finally:
        key = ""
    report.update(budget.summary())
    emit_json(report)
    return 0 if report["artifact_saved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
