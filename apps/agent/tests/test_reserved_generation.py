"""Reserved exact-source candidates are independent of test-point cardinality."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from semantic_validation_fixture import with_point_semantics
from test_compact_generation import execute, request

from casepilot_agent.compact_generation import StageContractError, run_compact


def reservation(req, key="asset:a", point_ids=None):
    from casepilot_agent.contracts import GenerationRequest
    from casepilot_agent.providers.mock import MockProvider

    snapshot = (
        MockProvider()
        .generate(GenerationRequest(prompt="登录"))
        .test_cases[0]
        .model_dump(mode="json")
    )
    snapshot["title"] = "历史账号登录成功"
    snapshot["steps"] = [
        {"action": "输入已确认的历史账号并提交登录", "expected": "进入历史账号首页"}
    ]
    return {
        "action": "reuse",
        "reason": "用户明确原样保留",
        "point_ids": point_ids or ["P-0"],
        "point_snapshots": {
            p["id"]: deepcopy(p) for p in (req or request(2)).confirmed_plan["test_points"]
            if p["id"] in (point_ids or ["P-0"])
        },
        "source": {
            "key": key,
            "label": "原用例",
            "locator": "A",
            "revision": "r1",
            "snapshot": snapshot,
        },
    }


def test_reserved_source_plus_gap_is_exact_and_original_plan_unchanged():
    req = request(2)
    item = reservation(req)
    req.confirmed_plan["reserved_reuse_outputs"] = [item]
    original = deepcopy(req.confirmed_plan)
    calls = []

    def tracked(stage, instruction, payload, result_type, model_id):
        calls.append((stage, payload))
        return execute(stage, instruction, payload, result_type, model_id)

    result = run_compact(req, SimpleNamespace(name="test"), with_point_semantics(tracked), None, 2)
    assert len(result.test_cases) == 2
    assert result.test_cases[0].steps[0].model_dump() == item["source"]["snapshot"]["steps"][0]
    assert result.test_cases[0].title == item["source"]["snapshot"]["title"]
    assert result.test_cases[0].test_point_ids == ["P-0"]
    assert result.test_cases[1].test_point_ids == ["P-1"]
    assert req.confirmed_plan == original
    generated = [payload for stage, payload in calls if stage == "test_case.generated"]
    assert len(generated) == 1 and generated[0]["batch_count"] == 1
    assert generated[0]["reserved_outputs"][0]["title"] == item["source"]["snapshot"]["title"]
    assert [point.id for point in result.test_points] == ["P-0", "P-1"]
    assert result.quality.passed


def test_many_sources_one_point_no_model_or_synthetic_points():
    req = request(1)
    first, second = reservation(req), reservation(req, "asset:b")
    second["source"]["snapshot"]["title"] = "不同账号退出"
    second["source"]["snapshot"]["steps"] = [{"action": "点击退出", "expected": "返回登录页"}]
    req.confirmed_plan["reserved_reuse_outputs"] = [first, second]

    def unexpected(*args):
        pytest.fail("reserved-only outputs must not call the model")

    result = run_compact(req, SimpleNamespace(name="test"), unexpected, None, 2)
    assert len(result.test_cases) == 2
    assert [case.test_point_ids for case in result.test_cases] == [["P-0"], ["P-0"]]
    assert len(result.test_points) == 1
    assert result.quality.passed


def test_one_source_many_points_materializes_once():
    req = request(2)
    req.confirmed_plan["reserved_reuse_outputs"] = [reservation(req, point_ids=["P-0", "P-1"])]
    result = run_compact(
        req, SimpleNamespace(name="test"), lambda *args: pytest.fail("model"), None, 1
    )
    assert len(result.test_cases) == 1
    assert result.test_cases[0].test_point_ids == ["P-0", "P-1"]
    assert result.quality.passed


@pytest.mark.parametrize(
    "invalid", ["duplicate_source", "missing_point", "zero_budget", "uncovered"]
)
def test_invalid_reservations_fail_closed(invalid):
    req = request(2)
    item = reservation(req)
    req.confirmed_plan["reserved_reuse_outputs"] = [item]
    count = 2
    if invalid == "duplicate_source":
        req.confirmed_plan["reserved_reuse_outputs"].append(deepcopy(item))
    elif invalid == "missing_point":
        item["point_ids"] = ["foreign"]
    elif invalid == "zero_budget":
        count = 0
    else:
        count = 1
    with pytest.raises(StageContractError):
        run_compact(req, SimpleNamespace(name="test"), execute, None, count)


def test_duplicate_reserved_content_is_rejected_not_silently_dropped():
    req = request(1)
    req.confirmed_plan["reserved_reuse_outputs"] = [reservation(req), reservation(req, "asset:b")]
    with pytest.raises(StageContractError, match="reserved_reuse_duplicate_output"):
        run_compact(req, SimpleNamespace(name="test"), execute, None, 2)


def test_requested_budget_counts_reserved_source_once_not_as_point_count():
    from casepilot_agent.pipeline import requested_case_count
    from casepilot_agent.quantity import OutputQuantity

    req = request(2)
    item = reservation(req, point_ids=["P-0", "P-1"])
    req.confirmed_plan["reserved_reuse_outputs"] = [item]
    req.confirmed_plan["approved_source_catalog"] = [item["source"]]
    req.confirmed_plan["reuse"] = {
        "decisions": [{"action": "reuse", "point_id": "P-0", "source": item["source"]}]
    }
    quantity = OutputQuantity(
        case_count=1,
        count_includes_reuse=False,
        required_reuse_source_keys=["asset:a"],
        new_case_count=1,
    )
    assert requested_case_count(req, lambda *args: quantity) == 2
    assert len(req.confirmed_plan["test_points"]) == 2


def test_reserved_only_known_point_can_have_additional_distinct_gap_case():
    req = request(1)
    req.confirmed_plan["reserved_reuse_outputs"] = [reservation(req)]
    result = run_compact(
        req,
        SimpleNamespace(name="test"),
        with_point_semantics(execute),
        None,
        2,
    )
    assert len(result.test_cases) == 2
    assert [case.test_point_ids for case in result.test_cases] == [["P-0"], ["P-0"]]
    assert len(result.test_points) == 1
    assert result.quality.passed


def test_legacy_entry_uses_same_reserved_execution_and_exact_obligations():
    from casepilot_agent.pipeline import GenerationPipeline
    from casepilot_agent.quantity import OutputQuantity

    req = request(1)
    req.output_contract = "legacy"
    item = reservation(req)
    req.confirmed_plan["reserved_reuse_outputs"] = [item]
    req.confirmed_plan["approved_source_catalog"] = [item["source"]]
    calls = []

    def quantity_only(stage, instruction, payload, result_type, model_id):
        calls.append(stage)
        assert stage == "output_quantity.interpreted"
        return OutputQuantity(
            required_reuse_source_keys=["asset:a"],
            output_case_count=1,
            new_case_count=0,
        )

    result = GenerationPipeline(SimpleNamespace(name="test")).run(
        req,
        context={},
        answers={},
        execute_stage=quantity_only,
    )
    assert len(result.test_cases) == 1
    assert result.test_cases[0].title == item["source"]["snapshot"]["title"]
    assert calls == ["output_quantity.interpreted"]
    assert result.model_metadata["output_obligations"]["required_reuse_source_keys"] == ["asset:a"]


def test_unknown_reserved_output_budget_requests_input_without_model_call():
    from casepilot_agent.pipeline import AwaitingInput

    req = request(1)
    req.confirmed_plan["reserved_reuse_outputs"] = [reservation(req)]
    with pytest.raises(AwaitingInput):
        run_compact(
            req, SimpleNamespace(name="test"), lambda *args: pytest.fail("model"), None, None
        )


@pytest.mark.parametrize(
    "corruption", ["duplicate_point", "unknown_feature", "wrong_action", "point_changed"]
)
def test_reserved_execution_retains_planning_identity_guards(corruption):
    req = request(1)
    req.confirmed_plan["reserved_reuse_outputs"] = [reservation(req)]
    if corruption == "duplicate_point":
        req.confirmed_plan["test_points"].append(deepcopy(req.confirmed_plan["test_points"][0]))
    elif corruption == "unknown_feature":
        req.confirmed_plan["test_points"][0]["feature_point_ids"] = ["foreign"]
    elif corruption == "point_changed":
        req.confirmed_plan["test_points"][0]["title"] = "Changed after exact review"
    else:
        req.confirmed_plan["reserved_reuse_outputs"][0]["action"] = "modify"
    with pytest.raises(StageContractError):
        run_compact(req, SimpleNamespace(name="test"), lambda *a: pytest.fail("no model"), None, 1)


@pytest.mark.parametrize("revocation", ["new", "exclude", "source_key"])
def test_reserved_execution_refuses_revoked_sources_before_any_candidate_or_model(revocation):
    req = request(1)
    req.confirmed_plan["reserved_reuse_outputs"] = [reservation(req)]
    if revocation == "source_key":
        req.confirmed_plan["excluded_reuse_source_keys"] = ["asset:a"]
    else:
        req.confirmed_plan["reuse"] = {"user_choices": {"P-0": revocation}}
    with pytest.raises(StageContractError, match="reserved_reuse_source_revoked"):
        run_compact(req, SimpleNamespace(name="test"), lambda *a: pytest.fail("no model"),
                    lambda *a: pytest.fail("no candidate"), 1)
