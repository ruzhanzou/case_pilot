from copy import deepcopy

import pytest
from pydantic import ValidationError

from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.planning_coverage import (
    COVERAGE_INSTRUCTION,
    CoverageObligation,
    validate_coverage,
)


def point(identifier="p1", owner="f1", scenario="below threshold"):
    return Point(
        id=identifier, title="Threshold verification", scenario=scenario,
        objective="Verify supplied rule", category="boundary", priority="P1",
        priority_reason="Explicit requirement", feature_point_ids=[owner],
    )


def obligation(**changes):
    return {
        "id": "o1", "feature_point_ids": ["f1"], "dimension": "boundary",
        "basis": "The supplied threshold rule states the inclusive comparison.",
        "point_ids": ["p1"], **changes,
    }


def test_covered_uncovered_and_ambiguous_are_distinct_without_modifying_points():
    points = [point()]
    before = deepcopy(points)
    report = validate_coverage([
        obligation(), obligation(id="o2", point_ids=[]),
        obligation(id="o3", point_ids=[], clarification="The unit is not supplied."),
    ], points, {"f1"})
    assert [item.id for item in report.uncovered] == ["o2"]
    assert [item.id for item in report.clarifications] == ["o3"]
    assert points == before


@pytest.mark.parametrize("changes,code", [
    ({"id": " "}, "obligation_id_invalid"),
    ({"basis": " "}, "basis_invalid"),
    ({"feature_point_ids": ["foreign"]}, "feature_reference_invalid"),
    ({"feature_point_ids": ["f1", "f1"]}, "feature_reference_invalid"),
    ({"point_ids": ["foreign"]}, "point_reference_invalid"),
    ({"point_ids": ["p1", "p1"]}, "point_reference_invalid"),
    ({"clarification": "Unknown rule"}, "ambiguous_claim"),
])
def test_invalid_obligation_relationships_rejected(changes, code):
    with pytest.raises(ValueError, match=code):
        validate_coverage([obligation(**changes)], [point()], {"f1"})


def test_point_cannot_claim_coverage_for_unrelated_owner():
    with pytest.raises(ValueError, match="point_ownership_invalid"):
        validate_coverage([obligation()], [point(owner="f2")], {"f1", "f2"})


def test_duplicate_obligation_ids_rejected():
    with pytest.raises(ValueError, match="obligation_id_invalid"):
        validate_coverage([obligation(), obligation()], [point()], {"f1"})


def test_duplicate_point_ids_rejected_before_coverage_claims():
    with pytest.raises(ValueError, match="point_id_duplicate"):
        validate_coverage([obligation()], [point(), point()], {"f1"})


def test_suggested_duplicates_do_not_merge_distinct_boundaries():
    points = [point(), point("p2", scenario="equal threshold")]
    before = deepcopy(points)
    report = validate_coverage(
        [obligation(point_ids=["p1", "p2"])], points, {"f1"},
        [{"point_ids": ["p1", "p2"], "reason": "Similar titles; review required."}],
    )
    assert len(report.duplicate_suggestions) == 1
    assert points == before
    assert points[0].scenario != points[1].scenario


@pytest.mark.parametrize("ids", [["p1", "missing"], ["p1", "p1"]])
def test_duplicate_suggestions_require_distinct_real_points(ids):
    with pytest.raises(ValueError, match="duplicate_suggestion_invalid"):
        validate_coverage([], [point()], {"f1"}, [{"point_ids": ids, "reason": "review"}])


def test_bounded_obligation_count_and_dimension():
    with pytest.raises(ValueError, match="obligation_limit"):
        validate_coverage([obligation(id=f"o{i}") for i in range(49)], [point()], {"f1"})
    with pytest.raises(ValidationError):
        CoverageObligation.model_validate(obligation(dimension="invented-rule"))


def test_instruction_is_generic_and_preserves_unspecified_rule_clarification():
    assert "小于、等于、大于" in COVERAGE_INSTRUCTION
    assert "clarification" in COVERAGE_INSTRUCTION
    assert "不同阈值边界或状态" in COVERAGE_INSTRUCTION
    assert "120" not in COVERAGE_INSTRUCTION
    assert "600" not in COVERAGE_INSTRUCTION
