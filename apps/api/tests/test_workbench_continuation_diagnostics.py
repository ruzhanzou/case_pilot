import json

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from casepilot_api.workbench_continuation_diagnostics import continuation_failure


def test_continuation_failure_never_serializes_exception_body():
    secret = "synthetic-secret-sql-parameters"
    for error in [ValueError(secret), RuntimeError(secret), HTTPException(409, secret)]:
        result = continuation_failure(error, "segment")
        assert secret not in json.dumps(result)
        assert result["phase"] == "segment"
        assert result["error_code"] == "workbench_continuation_failed"
    result = continuation_failure(ValueError("unbound_workbench_job"), "observe")
    assert result["domain_code"] == "unbound_workbench_job"


def test_validation_paths_are_bounded_and_values_absent():
    class Shape(BaseModel):
        receipt_ids: list[int]

    try:
        Shape.model_validate({"receipt_ids": ["synthetic-secret"]})
    except ValidationError as error:
        result = continuation_failure(error, "commit")
    assert result["validation_errors"][0]["path"] == ["receipt_ids", 0]
    assert "synthetic-secret" not in json.dumps(result)
    assert continuation_failure(Exception("private"), "private")["phase"] == "unknown"
