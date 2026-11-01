import json
from uuid import uuid4

from casepilot_agent.failure_diagnostics import worker_failure


def test_worker_diagnostic_never_contains_exception_text_or_untrusted_task_id():
    secret = "PRIVATE KEY SQL_PARAMETERS"
    error = ValueError(secret)
    result = worker_failure(error, secret, secret)
    assert result == {"phase": "unknown", "error_code": "domain_job_failed",
                      "exception_class": "ValueError", "frames": []}
    assert secret not in json.dumps(result)


def test_worker_diagnostic_correlates_only_uuid_job_and_static_phase():
    job = uuid4()
    result = worker_failure(RuntimeError("not retained"), "rewrite.failed", job)
    assert result["job_id"] == str(job) and result["phase"] == "rewrite"
    assert "not retained" not in json.dumps(result)
