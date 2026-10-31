"""Fixed scope error types improve diagnostics without relaxing reuse validation."""
import importlib.util
import json
from pathlib import Path

import pytest
from agents import ModelBehaviorError
from pydantic import ValidationError
from test_compact_generation import request
from test_reuse import source

from casepilot_agent.providers.safe_diagnostics import structured_failure
from casepilot_agent.reuse import plan_reuse


def qa_diagnostic(error):
    path = Path(__file__).resolve().parents[3] / "scripts/qa/workbench_safe_diagnostics.py"
    spec = importlib.util.spec_from_file_location("qa_safe_diagnostics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.safe_structured_failure(error)


@pytest.mark.parametrize("bad,code", [
    ("missing_point", "too_short"),
    ("duplicate_point", "too_long"),
    ("foreign_point", "literal_error"),
    ("new_with_source", "reuse_source_action_invalid"),
    ("reuse_without_source", "reuse_source_action_invalid"),
    ("foreign_source", "literal_error"),
])
def test_exact_reuse_guards_keep_fixed_codes_without_private_context(bad, code):
    private = "PRIVATE_MALICIOUS_SOURCE_OR_BODY"
    row = {"point_id": "P-0", "action": "reuse", "source_key": "asset:one",
           "test_object_match": "same", "reason": private}
    rows = [row]
    if bad == "missing_point":
        rows = []
    elif bad == "duplicate_point":
        rows = [row, row]
    elif bad == "foreign_point":
        row["point_id"] = private
    elif bad == "new_with_source":
        row["action"] = "new"
    elif bad == "reuse_without_source":
        row["source_key"] = None
    else:
        row["source_key"] = private
    schemas = []

    def complete(stage, instruction, payload, result_type):
        schemas.append(result_type)
        return result_type.model_validate({"decisions": rows})

    with pytest.raises(ValidationError) as caught:
        plan_reuse(request(1).confirmed_plan, "change", [source()], complete, "登录规则")
    errors = caught.value.errors(include_input=False, include_context=False, include_url=False)
    assert len(errors) == 1 and errors[0]["type"] == code
    error = ModelBehaviorError(private)
    error.__cause__ = caught.value
    diagnostic = structured_failure(error, stage="reuse.compared", result_type=schemas[0])
    error.casepilot_safe_diagnostic = diagnostic
    exported = qa_diagnostic(error)
    assert len(exported["validation_errors"]) == 1
    assert exported["validation_errors"][0]["type"] == code
    assert private not in json.dumps([diagnostic, exported])
    assert "ctx" not in json.dumps(exported)


def test_valid_reuse_decision_unchanged():
    row = {"point_id": "P-0", "action": "reuse", "source_key": "asset:one",
           "test_object_match": "same", "reason": "Current rule unchanged"}

    def complete(stage, instruction, payload, result_type):
        return result_type.model_validate({"decisions": [row]})

    result = plan_reuse(request(1).confirmed_plan, "change", [source()], complete, "登录规则")
    actual = result["decisions"][0]
    assert {key: actual[key] for key in row} == row


def scoped_schema():
    schemas = []

    def complete(stage, instruction, payload, result_type):
        schemas.append(result_type)
        return result_type.model_validate({"decisions": [
            {"point_id": point["id"], "action": "new", "source_key": None, "reason": "New"}
            for point in payload["test_points"]]})

    plan_reuse(request(2).confirmed_plan, "change", [source()], complete, "登录规则")
    return schemas[0]


def test_actual_reuse_output_schema_exposes_exact_real_ids_and_length():
    schema = scoped_schema().model_json_schema()
    decisions = schema["properties"]["decisions"]
    assert decisions["minItems"] == decisions["maxItems"] == 2
    decision = schema["$defs"][decisions["items"]["$ref"].rsplit("/", 1)[-1]]
    assert decision["properties"]["point_id"]["enum"] == ["P-0", "P-1"]
    allowed_source = decision["properties"]["source_key"]["anyOf"]
    assert any(item.get("const") == "asset:one" for item in allowed_source)
    assert any(item.get("type") == "null" for item in allowed_source)


def test_same_length_duplicate_still_fails_counter_with_safe_counts():
    schema = scoped_schema()
    row = {"point_id": "P-0", "action": "reuse", "source_key": "asset:one", "reason": "private"}
    with pytest.raises(ValidationError) as caught:
        schema.model_validate({"decisions": [row, row]})
    expected = {"expected_count": 2, "actual_count": 2, "missing_count": 1,
                "extra_count": 1, "duplicate_count": 1}
    error = ModelBehaviorError("PRIVATE")
    error.__cause__ = caught.value
    error.casepilot_safe_diagnostic = structured_failure(
        error, stage="reuse.compared", result_type=schema)
    exported = qa_diagnostic(error)
    assert exported["validation_errors"] == [{"type": "reuse_point_coverage_invalid",
                                               "loc": [], "counts": expected}]
    assert "P-0" not in json.dumps(exported) and "private" not in json.dumps(exported)


@pytest.mark.parametrize("bad,code", [
    ("source", "reuse_source_not_in_scope"),
    ("action", "reuse_source_action_invalid"),
    ("coverage", "reuse_point_coverage_invalid"),
])
def test_root_guards_remain_even_after_field_schema_narrowing(bad, code):
    from pydantic_core import PydanticCustomError

    from casepilot_agent.reuse import ReuseDecision

    schema = scoped_schema()
    rows = [ReuseDecision(point_id=f"P-{index}", action="reuse", source_key="asset:one",
                          reason="Rule") for index in range(2)]
    if bad == "source":
        rows[0].source_key = "untrusted-private-source"
    elif bad == "action":
        rows[0].action = "new"
    else:
        rows[1].point_id = "P-0"
    # Directly exercise the retained root guards; normal JSON rejects illegal
    # enums earlier and cannot bypass those field validators.
    with pytest.raises(PydanticCustomError) as caught:
        schema.model_construct(decisions=rows).check_scope()
    assert caught.value.type == code


def test_provider_and_qa_counts_allow_only_fixed_bounded_integers():
    from pydantic import BaseModel, model_validator
    from pydantic_core import PydanticCustomError

    class ScopedDecisions(BaseModel):
        @model_validator(mode="after")
        def reject(self):
            raise PydanticCustomError("reuse_point_coverage_invalid", "safe", {
                "expected_count": 2, "actual_count": True, "missing_count": -1,
                "extra_count": 10001, "duplicate_count": "PRIVATE", "input": "PRIVATE"})

    with pytest.raises(ValidationError) as caught:
        ScopedDecisions.model_validate({})
    error = ModelBehaviorError("PRIVATE")
    error.__cause__ = caught.value
    error.casepilot_safe_diagnostic = structured_failure(
        error, stage="reuse.compared", result_type=ScopedDecisions)
    assert error.casepilot_safe_diagnostic["validation_errors"][0]["counts"] == {
        "expected_count": 2}
    # QA independently rechecks attached data, including forged observer input.
    error.casepilot_safe_diagnostic["validation_errors"][0]["counts"].update({
        "actual_count": False, "extra_count": 10001, "private_key": "PRIVATE"})
    result = qa_diagnostic(error)
    assert result["validation_errors"][0]["counts"] == {"expected_count": 2}
    assert "PRIVATE" not in json.dumps(result) and "ctx" not in json.dumps(result)
