"""Actual production reuse validator, deterministic outputs; no network or DB."""
import json
import re
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest
import workbench_agent_reuse_compare_probe as probe
from pydantic import ValidationError


class Provider:
    def __init__(self, fault=None):
        self.fault, self.calls = fault, []

    def complete(self, *, stage, payload, result_type, **kwargs):
        self.calls.append(stage)
        assert payload["asset_selection_confirmed"] is True
        assert len(payload["sources"]) == 1
        valid_id, invalid_id = [point["id"] for point in payload["test_points"]]
        assert all(re.fullmatch(r"TP-[0-9a-f]{16}", value)
                   for value in (valid_id, invalid_id))
        rows = [
            {"point_id": valid_id, "action": "reuse", "source_key": probe.SOURCE_KEY,
             "test_object_match": "same", "reason": "原样复用已确认有效验证码规则"},
            {"point_id": invalid_id, "action": "new", "source_key": None,
             "test_object_match": "same", "reason": "原用例不包含无效验证码异常"},
        ]
        if self.fault == "coverage":
            rows.pop()
        elif self.fault == "duplicate":
            rows[1]["point_id"] = valid_id
        elif self.fault == "unknown":
            rows[1]["point_id"] = "TP-ffffffffffffffff"
        elif self.fault == "action":
            rows[1]["source_key"] = probe.SOURCE_KEY
        elif self.fault == "source":
            rows[0]["source_key"] = "asset:33333333-3333-4333-8333-333333333333"
        assert result_type.__name__ == "ScopedDecisions"
        return result_type.model_validate({"decisions": rows}), None


def test_exact_real_reuse_contract_keeps_original_and_new_gap():
    model = Provider()
    result = probe.compare(model, "offline")
    assert result["passed"] is True
    assert model.calls == ["reuse.compared"]
    plan, sources = probe.fixture()
    assert len(plan["test_points"]) == 2
    assert all(re.fullmatch(r"TP-[0-9a-f]{16}", point["id"]) for point in plan["test_points"])
    assert plan == probe.fixture()[0]
    assert sources[0]["key"] == probe.SOURCE_KEY
    assert sources[0]["revision"] == probe.SOURCE_VERSION


@pytest.mark.parametrize("fault,code", [
    ("coverage", "too_short"),
    ("duplicate", "reuse_point_coverage_invalid"),
    ("unknown", "literal_error"),
    ("action", "reuse_source_action_invalid"),
    ("source", "literal_error"),
])
def test_actual_scoped_decisions_reject_each_invalid_contract(fault, code):
    from casepilot_agent.providers.safe_diagnostics import structured_failure
    from workbench_safe_diagnostics import safe_structured_failure

    with pytest.raises(ValidationError) as caught:
        probe.compare(Provider(fault), "offline")
    assert caught.value.errors(include_input=False)[0]["type"] == code
    error = type("ModelBehaviorError", (Exception,), {})("private-secret")
    error.__cause__ = caught.value
    error.casepilot_safe_diagnostic = structured_failure(
        error, stage="reuse.compared", result_type=type("ScopedDecisions", (), {}))
    diagnostic = safe_structured_failure(error)
    assert diagnostic["validation_errors"][0]["type"] == code
    assert "private-secret" not in json.dumps(diagnostic)


def test_no_opt_in_never_calls_provider_or_claims_full_chain():
    output = StringIO()
    with patch.object(probe, "execute") as execute, redirect_stdout(output):
        assert probe.main([]) == 1
    execute.assert_not_called()
    report = json.loads(output.getvalue())
    assert report["requests_attempted"] == 0
    assert report["setup_scripted"] is True
    for key in ("passed", "live_nl_chain", "continuous_chain_passed",
                "formal_approval_tested", "database_used"):
        assert report[key] is False
