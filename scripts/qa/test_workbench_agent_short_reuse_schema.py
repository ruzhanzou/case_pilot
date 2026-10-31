"""No-provider CLI and redacted early diagnostic contracts for the short probe."""
import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import workbench_agent_short_reuse_schema as probe


def test_no_opt_in_never_executes_or_reads_provider_configuration():
    output = StringIO()
    with patch.object(probe, "execute") as execute, redirect_stdout(output):
        assert probe.main([]) == 1
    execute.assert_not_called()
    result = json.loads(output.getvalue())
    assert result["requests_attempted"] == 0
    assert result["passed"] is False
    assert result["continuous_chain_passed"] is False
    assert result["resume_allowed"] is False
    assert result["live_nl_chain"] is False
    assert result["setup_scripted"] is True
    assert result["setup_provider"] == "deterministic"


def test_immediate_observer_diagnostics_use_allowlist_and_flush_before_summary():
    output = StringIO()
    with redirect_stdout(output):
        probe.emit_structured_failure({
            "stage": "reuse.compared", "schema": "ScopedDecisions",
            "exception_chain": ["ModelBehaviorError", "private-secret"],
            "validation_errors": [{"type": "value_error", "loc": ["decisions", 0],
                                   "input": "private-secret", "msg": "private-secret"}],
            "raw_response": "private-secret", "key": "private-secret",
        })
        # Present immediately without any top-level summary or final exception.
        result = json.loads(output.getvalue())
        assert result["event"] == "structured_attempt_failed"
        assert result["diagnostic"]["stage"] == "reuse.compared"
        assert result["diagnostic"]["schema"] == "ScopedDecisions"
        assert result["diagnostic"]["validation_errors"] == [
            {"type": "value_error", "loc": ["decisions", 0]}]
    assert "private-secret" not in output.getvalue()


def test_pending_diagnostic_excludes_untrusted_data_and_does_not_invent_gap_budget():
    value = {
        "reason": "private-secret-reason", "required_sources": [{"key": "private-secret"}],
        "quantity": {"case_count": True, "test_point_count": "private-secret",
                     "output_case_count": -1, "new_case_count": 100001,
                     "extra": "private-secret"},
        "raw": "private-secret",
    }
    result = probe.safe_pending_clarification(value, generated_point_count=0)
    assert result == {"reason": "unrecognized", "required_source_count": 1,
                      "reserved_source_count": 1, "fixture_requested_total_points": 2,
                      "generated_point_count": 0, "quantity": {}}
    assert "generated_gap_budget" not in result
    assert "private-secret" not in json.dumps(result)
    for reason in ("reserved_reuse_mapping_requires_clarification",
                   "reserved_reuse_point_budget_requires_clarification"):
        assert probe.safe_pending_clarification({"reason": reason})["reason"] == reason


def test_through_generation_requires_opt_in_and_reports_distinct_scope():
    output = StringIO()
    with patch.object(probe, "execute") as execute, redirect_stdout(output):
        assert probe.main(["--through-generation"]) == 1
    execute.assert_not_called()
    report = json.loads(output.getvalue())
    assert report["scope"] == "short_second_draft_through_generation_and_adoption"
    assert report["through_generation"] is True
    assert report["requests_attempted"] == 0
    assert not report["continuous_chain_passed"] and not report["live_nl_chain"]


def test_through_generation_never_passes_on_only_draft_checks():
    async def incomplete(key, model, budget, report, storage, **kwargs):
        assert kwargs == {"through_generation": True}
        report["checks"] = [{"passed": True}, {"passed": True}]
    output = StringIO()
    with patch.object(probe, "read_key", return_value="unused"), \
         patch.object(probe, "execute", side_effect=incomplete), redirect_stdout(output):
        assert probe.main(["--allow-live", "--through-generation"]) == 1
    assert json.loads(output.getvalue())["passed"] is False


def test_source_scoped_diagnostic_preserves_fixed_schema_and_drops_private_identity():
    output = StringIO()
    with redirect_stdout(output):
        probe.emit_structured_failure({
            "stage": "feature.generated", "schema": "SourceScopedFeaturePlan",
            "exception_chain": ["ModelBehaviorError", "ValidationError"],
            "validation_errors": [{"type": "none_required",
                "loc": ["feature_points", 0, "source_refs", 0, "chunk_id"],
                "input": "private-secret-chunk", "ctx": {"key": "private-secret"}}],
        })
    value = json.loads(output.getvalue())["diagnostic"]
    assert value["schema"] == "SourceScopedFeaturePlan"
    assert value["validation_errors"] == [{"type": "none_required",
        "loc": ["feature_points", 0, "source_refs", 0, "chunk_id"]}]
    assert "private-secret" not in output.getvalue()
