#!/usr/bin/env python3
"""Opt-in direct reuse.compared schema probe; no DB, NL chain or approval claim.

Two synthetic typed test points and one immutable source are prepared locally.
Only actual plan_reuse's structured comparison calls the selected provider.
Default transport cap is two requests (initial response plus bounded correction).
"""
from __future__ import annotations

import asyncio
import sys
from copy import deepcopy

from workbench_agent_live_acceptance import (
    BASE_URL,
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
from workbench_agent_live_journey import require
from workbench_agent_short_reuse_schema import emit_structured_failure
from workbench_domain_diagnostics import safe_domain_failure
from workbench_safe_diagnostics import safe_structured_failure

sys.path[:0] = [str(ROOT / "apps/agent/src")]
SOURCE_KEY = "asset:11111111-1111-4111-8111-111111111111"
SOURCE_VERSION = "22222222-2222-4222-8222-222222222222"


def fixture():
    from casepilot_agent.contracts import FeaturePoint, TestPoint
    from casepilot_agent.planning import merge_planning
    from casepilot_agent.reuse import normalize_sources

    points = []
    for identifier, title, objective in [
        ("TP-valid", "有效验证码登录主流程", "已注册账户使用有效验证码登录成功"),
        ("TP-invalid", "无效验证码登录异常缺口", "已注册账户使用无效验证码被拒绝并显示验证码错误"),
    ]:
        points.append(TestPoint(id=identifier, title=title, objective=objective,
            category="functional", priority="P1", priority_reason="明确的合成登录规则",
            feature_point_ids=["FEATURE-login"]))
    snapshot = {
        "id": SOURCE_KEY.split(":", 1)[1], "current_revision_id": SOURCE_VERSION,
        "title": "Account system 有效验证码登录主流程", "module": "Account system",
        "priority": "P1", "case_type": "functional", "preconditions": ["账户已注册"],
        "steps": [{"action": "输入有效验证码并提交登录", "expected": "登录成功"}],
    }
    # Use the production normalizer, not a hand-written source contract.
    sources = normalize_sources([{
        "ref": SOURCE_KEY.split(":", 1)[1], "snapshot": snapshot,
        "current_revision_id": SOURCE_VERSION, "target_type": "formal",
    }], [])
    require(len(sources) == 1 and sources[0]["key"] == SOURCE_KEY, "probe_source_fixture")
    feature = FeaturePoint(id="FEATURE-login", name="验证码登录", module="Account system",
        description="有效验证码成功，无效验证码拒绝", requirement_refs=["SYNTHETIC-login"])
    plan = merge_planning([feature], points, {"evidence": []}, processed_batches=1)
    return plan, sources


def compare(provider, model):
    from casepilot_agent.providers.safe_diagnostics import observe_structured_failures
    from casepilot_agent.reuse import plan_reuse

    plan, sources = fixture()
    before = deepcopy((plan, sources))
    observed = []

    def complete(stage, instruction, payload, result_type):
        require(stage == "reuse.compared", "probe_unexpected_provider_stage")
        observed.append(stage)
        result, _ = provider.complete(stage=stage, instruction=instruction, payload=payload,
                                      result_type=result_type, model_id=model)
        return result

    with observe_structured_failures(emit_structured_failure):
        result = plan_reuse(plan, "regression", sources, complete,
            "测试对象：Account system。有效验证码登录成功，无效验证码登录被拒绝并显示验证码错误。"
            "原样复用已提供的有效验证码主流程，再为无效验证码生成一条新增缺口；"
            "两条独立测试点已明确，不修改原用例任何字段。",
            test_object="Account system", assets_confirmed=True)
    require((plan, sources) == before, "probe_input_mutation")
    require(observed == ["reuse.compared"], "probe_unexpected_stage_count")
    valid_id, invalid_id = [point["id"] for point in plan["test_points"]]
    rows = {row["point_id"]: row for row in result["decisions"]}
    require(set(rows) == {valid_id, invalid_id}, "probe_point_coverage")
    require(result["summary"] == {"reuse": 1, "new": 1}, "probe_reuse_gap_count")
    require(rows[valid_id]["action"] == "reuse" and
            rows[valid_id]["source_key"] == SOURCE_KEY and
            rows[valid_id]["source"] == sources[0], "probe_original_source")
    require(rows[invalid_id]["action"] == "new" and
            rows[invalid_id]["source_key"] is None, "probe_new_gap")
    return {"check": "actual_reuse_compare_exact_source_plus_new_gap", "passed": True}


async def execute(key, model, budget):
    from casepilot_agent.providers.agents_sdk import AgentsSdkProvider

    provider = AgentsSdkProvider(base_url=BASE_URL, api_key=key, model=model, pro_model=model,
        local_model=model, timeout=120, generation_timeout=120, api_type="responses",
        tracing_enabled=False)
    set_stage("asset_reuse")
    async with bounded_clients(key, budget):
        return await asyncio.to_thread(compare, provider, model)


def main(argv=None):
    arguments = parser(__doc__)
    arguments.set_defaults(max_requests=2)
    args = arguments.parse_args(argv)
    disable_sensitive_logging()
    budget = RequestBudget(args.max_requests, emit_json)
    report = {"event": "summary", "scope": "direct_reuse_compare_schema_only", "passed": False,
              "setup_scripted": True, "database_used": False, "live_nl_chain": False,
              "continuous_chain_passed": False, "formal_approval_tested": False, "checks": []}
    try:
        key = read_key(args)
        report["checks"] = [asyncio.run(execute(key, args.model, budget))]
        report["passed"] = True
    except Exception as error:  # noqa: BLE001 -- no provider text or exception messages.
        report["error_code"] = budget.stop_code or "reuse_compare_probe_failed"
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
