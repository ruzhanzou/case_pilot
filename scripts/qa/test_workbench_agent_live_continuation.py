"""Offline-only safety and actual-read receipt contracts for root live harness."""
import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest
import workbench_agent_live_continuation as harness
from workbench_agent_live_journey import JourneyFailure


def test_explicit_stdin_and_live_permission_are_required_before_execution():
    output = StringIO()
    with patch.object(harness, "read_key") as key, patch.object(harness, "execute") as execute:
        with redirect_stdout(output):
            assert harness.main([]) == 1
        key.assert_not_called()
        execute.assert_not_called()
    report = json.loads(output.getvalue().splitlines()[-1])
    assert report["error_code"] == "explicit_stdin_required"
    assert report["requests_attempted"] == 0


def test_final_query_requires_actual_current_read_receipt_and_two_rows():
    run = {"plan": {"steps": [{"action": "CASE_QUERY"}]}}
    agent = {"receipts": [{"tool": "query_assets", "effect": "read"}], "events": [
        {"type": "tool_completed", "tool": "query_assets", "returned_count": 2},
    ]}
    harness.verify_final_query(run, {"context": {"workbench_agent": agent}})
    for invalid in (
        {**agent, "receipts": []},
        {**agent, "receipts": [{"tool": "query_assets", "effect": "prepare"}]},
        {**agent, "events": []},
        {**agent, "events": [{"type": "tool_completed", "tool": "query_assets", "returned_count": 1}]},
    ):
        with pytest.raises(JourneyFailure):
            harness.verify_final_query(run, {"context": {"workbench_agent": invalid}})
    with pytest.raises(JourneyFailure):
        harness.verify_final_query({"plan": {"steps": [{"action": "CASE_GENERATE"}]}},
                                   {"context": {"workbench_agent": agent}})


@pytest.mark.parametrize("driver", ["continuation", "crud", "journey"])
def test_top_level_structured_diagnostics_only_emit_fixed_fields(driver):
    import workbench_agent_live_crud as crud
    import workbench_agent_live_journey as journey

    module = {"continuation": harness, "crud": crud, "journey": journey}[driver]
    execute_name = "execute_crud" if driver == "crud" else "execute"
    ModelBehaviorError = type("ModelBehaviorError", (Exception,), {})
    error = ModelBehaviorError("private-secret-response")
    error.casepilot_safe_diagnostic = {
        "stage": "reuse.compared", "schema": "ScopedDecisions",
        "exception_chain": ["ModelBehaviorError", "ValidationError", "private-secret-class"],
        "validation_errors": [{"type": "value_error", "loc": ["decisions", 0],
                               "msg": "private-secret-message", "input": "private-secret-input"},
                              {"type": "private-secret-type",
                               "loc": ["private-secret-field", {"private-secret": True}, -1]}],
        "raw_response": "private-secret-raw", "key": "private-secret-key",
    }

    async def fail(*args, **kwargs):
        raise error

    output = StringIO()
    with (patch.object(module, "read_key", return_value="private-secret-key"),
          patch.object(module, execute_name, fail),
          patch.object(module.Path, "mkdir"), redirect_stdout(output)):
        assert module.main(["--allow-live", "--key-stdin"]) == 1
    assert "private-secret" not in output.getvalue()
    report = json.loads(output.getvalue().splitlines()[-1])
    assert not report["passed"]
    assert report["requests_attempted"] == 0
    diagnostic = report["structured_failure"]
    assert diagnostic["stage"] == "reuse.compared"
    assert diagnostic["schema"] == "ScopedDecisions"
    assert diagnostic["exception_chain"][-1] == "OtherError"
    assert diagnostic["validation_errors"][0] == {"type": "value_error",
                                                   "loc": ["decisions", 0]}
    assert diagnostic["validation_errors"][1] == {
        "type": "other_validation_error", "loc": ["unknown_field"] * 3}
    assert set(diagnostic) == {"stage", "schema", "exception_chain", "validation_errors"}


def test_structured_diagnostics_reject_unknown_labels_and_bound_collections():
    from workbench_safe_diagnostics import safe_structured_failure

    error = type("ModelBehaviorError", (Exception,), {})("private-secret")
    error.casepilot_safe_diagnostic = {
        "stage": "private-secret", "schema": "private-secret",
        "exception_chain": ["private-secret"] * 20,
        "validation_errors": [{"type": [], "loc": ["private-secret"] * 20}] * 20,
    }
    result = safe_structured_failure(error)
    assert result["stage"] == result["schema"] == "unrecognized"
    assert len(result["exception_chain"]) == 5
    assert len(result["validation_errors"]) == 12
    assert len(result["validation_errors"][0]["loc"]) == 8
    assert "private-secret" not in json.dumps(result)
    error.casepilot_safe_diagnostic = "private-secret"
    assert safe_structured_failure(error) is None
    assert safe_structured_failure(ValueError("private-secret")) is None


def test_real_provider_safe_diagnostic_retains_schema_stage_and_known_locations():
    from casepilot_agent.contracts import TestPointPlan
    from casepilot_agent.providers.safe_diagnostics import structured_failure
    from pydantic import ValidationError
    from workbench_safe_diagnostics import safe_structured_failure

    error = type("ModelBehaviorError", (Exception,), {})("private-secret-response")
    try:
        TestPointPlan.model_validate({"test_points": "private-secret-input"})
    except ValidationError as cause:
        error.__cause__ = cause
    error.casepilot_safe_diagnostic = structured_failure(
        error, stage="test_point.generated", result_type=TestPointPlan)
    result = safe_structured_failure(error)
    assert result == error.casepilot_safe_diagnostic
    assert result["stage"] == "test_point.generated"
    assert result["schema"] == "TestPointPlan"
    assert result["validation_errors"] == [{"type": "list_type", "loc": ["test_points"]}]
    assert "private-secret" not in json.dumps(result)
