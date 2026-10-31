import pytest
from workbench_run_terminal_guard import require_live_run, safe_failure


@pytest.mark.parametrize("status", ["failed", "cancelled", "invalidated", "budget_exhausted"])
def test_no_confirmation_after_terminal_failure(status):
    report = {}
    with pytest.raises(AssertionError, match="durable_run_terminal_failure"):
        require_live_run({"status": status, "failure_diagnostic": {
            "error_code": "workbench_continuation_failed", "phase": "commit",
            "exception_class": "IntegrityError", "headers": "secret", "sql": "secret",
        }}, report, "query")
    assert report["terminal_failure"]["diagnostic"]["phase"] == "commit"
    assert "secret" not in str(report)


@pytest.mark.parametrize("status", ["active", "waiting_job", "waiting_approval", "completed"])
def test_gate_does_not_confuse_human_docking_with_failure(status):
    report = {}
    require_live_run({"status": status}, report, "query")
    assert not report


def test_unknown_error_text_never_saved():
    assert safe_failure({"error_code": "private-value", "exception_class": "private"}) == {
        "error_code": "unknown", "phase": "unknown", "exception_class": "unknown", "frames": [],
    }


def test_unknown_paths_and_non_scalar_values_are_filtered():
    result = safe_failure({"error_code": {}, "frames": None, "validation_errors": [
        {"type": "literal_error", "path": ["receipt_ids", 0, "private-value"], "input": "secret"},
    ]})
    assert result["validation_errors"] == [{"type": "literal_error",
                                            "path": ["receipt_ids", 0, "unknown"]}]
    assert "secret" not in str(result) and "private-value" not in str(result)


def test_known_domain_error_survives_repeated_projection():
    value = {"error_code": "workbench_continuation_failed", "phase": "observe",
             "exception_class": "ValueError", "domain_code": "unbound_workbench_job"}
    assert safe_failure(safe_failure(value))["domain_code"] == "unbound_workbench_job"
    assert safe_failure({"domain_code": "private"})["domain_code"] == "unknown"
