import json

from pydantic import BaseModel, ConfigDict, ValidationError

from casepilot_agent.providers.safe_diagnostics import structured_failure


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int


def test_diagnostics_never_expose_inputs_error_messages_unknown_keys_or_context():
    secret = "SYNTHETIC_PRIVATE_SENTINEL_NEVER_EXPORT"
    try:
        Result.model_validate({"count": secret, secret: "private"})
    except ValidationError as cause:
        error = ValueError(secret)
        error.__cause__ = cause
        data = structured_failure(error, stage="test_point.planned", result_type=Result)
    serialized = json.dumps(data)
    assert secret not in serialized and "private" not in serialized
    assert data["stage"] == "test_point.planned"
    assert data["schema"] == "Result"
    assert data["exception_chain"] == ["ValueError", "ValidationError"]
    assert any(item["loc"] == ["unknown_field"] for item in data["validation_errors"])
    assert all(set(item) == {"type", "loc"} for item in data["validation_errors"])


def test_diagnostics_bound_cyclic_exception_chain_and_untrusted_labels():
    error = ValueError("never print me")
    error.__cause__ = error
    data = structured_failure(error, stage="bad label / body", result_type=Result)
    assert data["stage"] == "unrecognized"
    assert data["exception_chain"] == ["ValueError"]
