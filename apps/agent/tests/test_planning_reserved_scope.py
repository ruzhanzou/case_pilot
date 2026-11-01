"""A narrow gap budget must not force unrelated coverage claims."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_parallel_planning import features
from test_planning_quality_flow import bind_scripted_points, point
from test_reserved_generation import reservation

from casepilot_agent.contracts import RequirementAnalysis
from casepilot_agent.output_obligations import append_reserved_source_point
from casepilot_agent.planning import build_planning, validate_point_batch
from casepilot_agent.planning_coverage import CoverageObligation


def test_one_gap_point_keeps_other_feature_explicitly_uncovered_and_reserved_context():
    reserved = [{"source_key": "asset:kept", "source_revision": "revision-1",
                 "snapshot": {"title": "Existing normal path", "steps": []},
                 "coverage_status": "pending_independent_review"}]
    before = deepcopy(reserved)
    calls = []

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            return features(2)
        calls.append(payload)
        assert payload["reserved_outputs"] == reserved
        assert "不得为凑全功能关联" in instruction
        first, second = [f["id"] for f in payload["feature_points"]["feature_points"]]
        value = point(1)
        value.update(category="exception", feature_point_ids=[second])
        obligations = [
            dict(id="retained-rule", feature_point_ids=[first], dimension="normal",
                 basis="Original source requires independent coverage review", point_ids=[]),
            dict(id="gap-rule", feature_point_ids=[second], dimension="exception",
                 basis="Explicit exception rule", point_ids=["p0"]),
        ]
        return schema.model_validate({
            "test_points": bind_scripted_points(payload, [value]),
            "coverage_obligations": obligations,
        })

    plan = build_planning(RequirementAnalysis(summary="Existing normal rule and exception gap"),
                          {"user_input": "Keep the original source; add only the exception gap"},
                          complete, target_count=1, reserved_outputs=reserved)
    assert len(calls) == 1 and reserved == before
    assert len(plan["test_points"][0]["feature_point_ids"]) == 1
    report = plan["coverage_review"]
    assert report["status"] == "pending_independent_review"
    batch = report["batches"][0]
    assert batch["uncovered_ids"] == ["retained-rule"]
    assert "coverage_budget_limited" in batch["warnings"]
    assert batch["obligations"][0]["point_ids"] == []


@pytest.mark.parametrize("kind", ["missing", "foreign", "false_link"])
def test_unrepresented_feature_still_requires_explicit_valid_uncovered_obligation(kind):
    obligations = [] if kind == "missing" else [CoverageObligation(
        id="gap", dimension="normal", basis="Explicit rule",
        feature_point_ids=["foreign" if kind == "foreign" else "normal"],
        point_ids=["exception-point"] if kind == "false_link" else [],
    )]
    plan = SimpleNamespace(test_points=[SimpleNamespace(
        id="exception-point", feature_point_ids=["exception"], scenario="Rejected", title="Reject",
    )], coverage_obligations=obligations)
    with pytest.raises(ValueError, match="planning_(feature_uncovered|coverage_feature_reference)"):
        validate_point_batch(plan, {"normal", "exception"}, 1, exact=True)


def test_reserved_source_point_does_not_inherit_unrelated_gap_requirements():
    source = reservation(None)["source"]
    plan = {"feature_points": [{"id": "unrelated", "requirement_refs": ["OTHER-RULE"]}],
            "test_points": []}
    append_reserved_source_point(plan, [source])
    added = plan["feature_points"][-1]
    assert added["requirement_refs"] == []
    assert source["revision"] in added["source_refs"][0]["excerpt"]
    assert plan["feature_points"][0]["requirement_refs"] == ["OTHER-RULE"]
