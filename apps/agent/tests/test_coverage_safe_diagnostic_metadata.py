"""The provider and independent QA sink reject untrusted diagnostic payloads."""
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from casepilot_agent.planning_coverage import schema_coverage_guard
from casepilot_agent.providers.safe_diagnostics import structured_failure

SPEC = importlib.util.spec_from_file_location(
    "qa_safe_metadata",
    Path(__file__).resolve().parents[3] / "scripts/qa/workbench_safe_diagnostics.py")
QA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QA)

SECRET = "PRIVATE_RESPONSE_PROMPT_ACCOUNT_KEY"


def diagnostic(metadata, code="planning_boundary_axis_invalid"):
    class BatchTestPointPlan(BaseModel):
        @model_validator(mode="after")
        def reject(self):
            raise PydanticCustomError(code, SECRET, {"metadata": metadata, "input": SECRET})
    with pytest.raises(ValidationError) as caught:
        BatchTestPointPlan.model_validate({})
    return structured_failure(
        caught.value, stage="test_point.generated", result_type=BatchTestPointPlan)


def qa(value):
    error = type("ModelBehaviorError", (Exception,), {})(SECRET)
    error.casepilot_safe_diagnostic = value
    return QA.safe_structured_failure(error)


def test_provider_and_qa_retain_only_safe_coverage_metadata():
    expected = {"obligation_index": 2, "dimension": "boundary", "contract_present": True,
                "clarification_present": False, "point_count": 3, "source_slot": "source:0",
                "threshold": 120.0, "sampling_step": 1, "axis_matches": False}
    value = diagnostic({**expected, "axis": SECRET, "unit": SECRET, "source_literal": SECRET,
                        "reasoning": SECRET, "prompt": SECRET, "account_id": SECRET})
    assert value["validation_errors"][0]["metadata"] == expected
    assert qa(value)["validation_errors"][0]["metadata"] == expected
    assert SECRET not in json.dumps(value) + json.dumps(qa(value))


@pytest.mark.parametrize("metadata", [None, [], SECRET, {
    "obligation_index": 48, "dimension": SECRET, "contract_present": 1,
    "clarification_present": "true", "point_count": True, "source_slot": "source:0" + SECRET,
    "threshold": float("nan"), "sampling_step": float("inf"), "batch_index": -1,
    "attempt": 10001, "axis_matches": SECRET,
}])
def test_malformed_metadata_is_omitted_at_both_sinks(metadata):
    value = diagnostic(metadata)
    assert "metadata" not in value["validation_errors"][0]
    # Direct attachment is untrusted and must be filtered independently too.
    value["validation_errors"][0]["metadata"] = metadata
    assert "metadata" not in qa(value)["validation_errors"][0]


@pytest.mark.parametrize("code", ["value_error", "reuse_point_coverage_invalid", SECRET])
def test_noncoverage_error_cannot_smuggle_metadata(code):
    value = diagnostic({"obligation_index": 1}, code)
    assert "metadata" not in value["validation_errors"][0]
    value["validation_errors"][0]["metadata"] = {"obligation_index": 1}
    assert "metadata" not in qa(value)["validation_errors"][0]


def test_guard_preserves_structural_context_without_stringifying_object():
    error = ValueError("planning_boundary_axis_invalid")
    error.casepilot_safe_metadata = {"obligation_index": 1, "axis_matches": False}
    def fail():
        raise error
    with pytest.raises(PydanticCustomError) as caught:
        schema_coverage_guard(fail)
    assert caught.value.context == {"metadata": error.casepilot_safe_metadata}
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "number", [True, float("inf"), float("-inf"), float("nan"), 10**1000, -1e13])
def test_nonfinite_bool_or_unbounded_numbers_are_never_exported(number):
    value = diagnostic({"threshold": number, "sampling_step": number})
    assert "metadata" not in value["validation_errors"][0]
    value["validation_errors"][0]["metadata"] = {"threshold": number}
    assert "metadata" not in qa(value)["validation_errors"][0]


@pytest.mark.parametrize("code", [[], {}, None, True])
def test_qa_handles_malformed_error_codes_even_with_counts_and_metadata(code):
    value = {"validation_errors": [{"type": code, "metadata": {"point_count": 1},
                                    "counts": {"expected_count": 1}}]}
    assert qa(value)["validation_errors"] == [{"type": "other_validation_error", "loc": []}]


def test_diagnostic_loc_indices_are_bounded_at_provider_sink():
    error = ValidationError.from_exception_data("Synthetic", [
        {"type": "int_type", "loc": ("test_points", -1, 10001, "axis", SECRET), "input": SECRET}])
    value = structured_failure(error, stage="test_point.generated", result_type=BaseModel)
    assert value["validation_errors"][0]["loc"] == [
        "test_points", "unknown_field", "unknown_field", "axis", "unknown_field"]
    assert SECRET not in json.dumps(value)


def test_new_display_axis_alias_is_not_a_contract_failure():
    from test_planning_boundary_flow import run

    def mutate(data, payload):
        data["coverage_obligations"][0]["boundary_contract"]["axis"] = "elapsed_time"

    result, _ = run(target=1, mutate=mutate)
    batch = result["coverage_review"]["batches"][0]
    assert "boundary_semantics_requires_review" in batch["warnings"]
    assert batch["obligations"][0]["boundary_contract"]["axis"] == "elapsed_time"


def test_unresolved_contract_cannot_hide_hard_samples_and_reports_safe_context():
    from test_planning_boundary_flow import run

    def mutate(data, payload):
        data["coverage_obligations"][0]["boundary_contract"] = {
            "status": "unresolved", "reason": SECRET}

    with pytest.raises(ValidationError) as caught:
        run(mutate=mutate)
    value = structured_failure(caught.value, stage="test_point.generated",
                               result_type=type("BatchTestPointPlan", (), {}))
    failure = next(item for item in value["validation_errors"]
                   if item["type"] == "planning_boundary_contract_required")
    assert failure["metadata"] == {
        "obligation_index": 0, "dimension": "boundary", "contract_present": True,
        "clarification_present": False, "point_count": 1,
    }
    assert qa(value)["validation_errors"] == value["validation_errors"]
    assert SECRET not in json.dumps(value)
