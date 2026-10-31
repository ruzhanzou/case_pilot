from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import create_model
from pydantic_core import PydanticCustomError

from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.planning_coverage import (
    COVERAGE_INSTRUCTION,
    COVERAGE_VALIDATION_CODES,
    CoverageObligation,
    schema_coverage_guard,
    validate_completion_ownership,
)

OwnedPoint = create_model("OwnedPoint", __base__=Point, primary_feature_id=(str, ...))


def point(identifier="old", primary="f1", *, legacy=False, owners=None):
    data = dict(
        id=identifier, title="Rule check", objective="Observe the supplied rule",
        scenario="explicit state", category="boundary", priority="P1",
        priority_reason="Requirement", feature_point_ids=owners or [primary],
    )
    if not legacy:
        data["primary_feature_id"] = primary
    return (Point if legacy else OwnedPoint).model_validate(data)


def obligation(identifier="gap", *, refs=(), owners=("f1",), clarification=""):
    return CoverageObligation(
        id=identifier, feature_point_ids=list(owners), dimension="boundary",
        basis="Explicit threshold rule", point_ids=list(refs), clarification=clarification,
    )


def plans(*, primary="f1", legacy=False):
    original = SimpleNamespace(test_points=[point()], coverage_obligations=[obligation()])
    candidate = deepcopy(original)
    candidate.test_points.append(point("new", primary, legacy=legacy))
    candidate.coverage_obligations[0].point_ids = ["new"]
    return original, candidate


@pytest.mark.parametrize("legacy", [False, True])
def test_exact_original_owner_may_fill_gap_without_mutating_inputs(legacy):
    original, candidate = plans(legacy=legacy)
    before = deepcopy((original, candidate))
    validate_completion_ownership(original, candidate)
    assert (original, candidate) == before


def test_unlinked_new_point_is_not_a_gap_completion():
    original, candidate = plans()
    candidate.coverage_obligations[0].point_ids = []
    with pytest.raises(ValueError, match="completion_unlinked_point"):
        validate_completion_ownership(original, candidate)


def test_secondary_feature_does_not_authorize_wrong_primary_observable_goal():
    original, candidate = plans(primary="f2")
    candidate.test_points[-1].feature_point_ids = ["f1", "f2"]
    with pytest.raises(ValueError, match="completion_owner_invalid"):
        validate_completion_ownership(original, candidate)


def test_legacy_fallback_uses_first_owner_not_any_secondary_owner():
    original, candidate = plans(primary="f2", legacy=True)
    candidate.test_points[-1].feature_point_ids = ["f2", "f1"]
    with pytest.raises(ValueError, match="completion_owner_invalid"):
        validate_completion_ownership(original, candidate)


def test_explicit_empty_primary_is_not_repaired_by_feature_list():
    original, candidate = plans()
    candidate.test_points[-1].primary_feature_id = ""
    with pytest.raises(ValueError, match="completion_owner_invalid"):
        validate_completion_ownership(original, candidate)


@pytest.mark.parametrize("change", ["add", "remove", "duplicate"])
def test_completion_cannot_invent_or_replace_original_obligations(change):
    original, candidate = plans()
    if change == "add":
        candidate.coverage_obligations.append(obligation("new-goal", refs=["new"]))
    elif change == "remove":
        candidate.coverage_obligations = []
    else:
        candidate.coverage_obligations.append(deepcopy(candidate.coverage_obligations[0]))
    with pytest.raises(ValueError, match="completion_goal_invalid"):
        validate_completion_ownership(original, candidate)


@pytest.mark.parametrize("clarification", ["", "Initial state unspecified"])
def test_already_covered_or_ambiguous_obligations_do_not_authorize_new_points(clarification):
    original, candidate = plans()
    original.coverage_obligations[0].clarification = clarification
    if not clarification:
        original.coverage_obligations[0].point_ids = ["old"]
    with pytest.raises(ValueError, match="completion_unlinked_point"):
        validate_completion_ownership(original, candidate)


def test_original_clarification_can_remain_unchanged_while_other_gap_is_filled():
    original, candidate = plans()
    unclear = obligation("unclear", clarification="Unit unspecified")
    original.coverage_obligations.append(unclear)
    candidate.coverage_obligations.append(deepcopy(unclear))
    validate_completion_ownership(original, candidate)
    assert candidate.coverage_obligations[1] == unclear


def test_link_to_uncovered_and_already_covered_goal_is_not_exclusively_gap_filling():
    original, candidate = plans()
    original.coverage_obligations.append(obligation("covered", refs=["old"]))
    candidate.coverage_obligations.append(obligation("covered", refs=["old", "new"]))
    with pytest.raises(ValueError, match="completion_unlinked_point"):
        validate_completion_ownership(original, candidate)


def test_each_original_obligation_must_authorize_primary_when_one_point_fills_several():
    original, candidate = plans()
    original.coverage_obligations.append(obligation("gap2", owners=["f2"]))
    candidate.coverage_obligations.append(obligation("gap2", refs=["new"], owners=["f2"]))
    with pytest.raises(ValueError, match="completion_owner_invalid"):
        validate_completion_ownership(original, candidate)


def test_fixed_failure_type_survives_schema_guard_without_point_content():
    original, candidate = plans(primary="private-owner")
    with pytest.raises(PydanticCustomError) as caught:
        schema_coverage_guard(validate_completion_ownership, original, candidate)
    assert caught.value.type == "planning_coverage_completion_owner_invalid"
    assert caught.value.type in COVERAGE_VALIDATION_CODES
    assert "private-owner" not in str(caught.value)


def test_instruction_requires_known_granularity_origin_state_and_observable_primary():
    for phrase in ["时间起点", "初始状态", "primary_feature_id", "主要可观察结果", "clarification"]:
        assert phrase in COVERAGE_INSTRUCTION
    assert "120" not in COVERAGE_INSTRUCTION
    assert "600" not in COVERAGE_INSTRUCTION
