"""Scripted structural contracts, never an independent semantic quality verdict."""

from copy import deepcopy

import pytest
from test_parallel_planning import features
from test_planning_quality_flow import point

from casepilot_agent.contracts import RequirementAnalysis
from casepilot_agent.contracts import TestPoint as Point
from casepilot_agent.planning import build_planning
from casepilot_agent.store import render_test_brief_markdown

RULE = "elapsed seconds since issuance < 7 seconds is valid."
SETUP = "Sample elapsed in integer seconds."


def run(*, target=None, missing_setup=False, mutate=None, fill=True, rule=RULE,
        inspect_schema=None):
    calls = []

    def complete(stage, instruction, payload, schema):
        if stage == "feature.generated":
            return features(1)
        calls.append(deepcopy(payload))
        if inspect_schema:
            inspect_schema(schema.model_json_schema())
        binding = payload["primary_bindings"][0]
        owner = binding["feature_id"]
        values = deepcopy(payload.get("existing_plan", {}).get("test_points", []))
        positions = [("before", 6)] if not values else ([("at", 7), ("after", 8)] if fill else [])
        if missing_setup:
            positions = [("at", 7)]
        for position, value in positions:
            p = point(value, position)
            p.update(primary_binding=binding["id"], feature_point_ids=[])
            p["boundary_samples"] = [
                dict(
                    obligation_id="threshold",
                    position=position,
                    value=value,
                    initial_state="fresh token issued at origin",
                    assertion="given validity comparison",
                    assertion_role="primary",
                    assertion_binding=binding["id"],
                )
            ]
            values.append(p)
        contract = dict(
            evidence_binding=(payload["boundary_evidence_bindings"][0]["id"]
                              if payload["boundary_evidence_bindings"] else "unavailable"),
            comparator="lt",
            axis="elapsed",
            time_origin="issuance",
        )
        obligation = dict(
            id="threshold",
            feature_point_ids=[owner],
            dimension="boundary",
            basis=RULE,
            point_ids=[p["id"] for p in values],
            boundary_contract=contract,
        )
        data = dict(test_points=values, coverage_obligations=[obligation])
        if mutate:
            mutate(data, payload)
        result = schema.model_validate(data)
        # Stage cache must retain selectors and reconstruct exactly, without an
        # extra model call or reinterpretation of another catalog's pair index.
        assert schema.model_validate(result.model_dump(mode="json")).model_dump(
            mode="json"
        ) == result.model_dump(mode="json")
        return result

    context = {"user_input": rule}
    if not missing_setup:
        context["test_setup"] = SETUP
    result = build_planning(
        RequirementAnalysis(summary="Explicit rule"), context, complete, target_count=target
    )
    return result, calls


def test_partial_linked_samples_receive_one_completion_and_canonical_projection():
    result, calls = run()
    assert len(calls) == 2
    batch = result["coverage_review"]["batches"][0]
    assert batch["uncovered_ids"] == []
    assert batch["completion_attempted"]
    contract = batch["obligations"][0]["boundary_contract"]
    assert "source_slot" not in contract and contract["source_ref"]["excerpt"] == RULE
    points = result["test_points"]
    assert len(points) == 3
    for p in points:
        s = p["boundary_samples"][0]
        assert s["unit"] == "seconds" and s["axis"] == "elapsed" and s["time_origin"] == "issuance"
        assert s["assertion_feature_id"] == p["primary_feature_id"]
        assert s["assertion_source_ref"]["excerpt"] == RULE
        assert "assertion_binding" not in s and "assertion_source_slot" not in s
    assert {p["boundary_samples"][0]["value"] for p in points} == {6, 7, 8}


def test_exact_budget_does_not_inflate_to_fill_missing_samples():
    result, calls = run(target=1)
    assert len(calls) == 1 and len(result["test_points"]) == 1
    batch = result["coverage_review"]["batches"][0]
    assert batch["uncovered_ids"] == ["threshold"]
    assert "coverage_unverified" in batch["warnings"]
    assert "coverage_budget_limited" in batch["warnings"]
    assert batch["obligations"][0]["point_ids"] == [result["test_points"][0]["id"]]


def test_missing_sampling_stays_unverified_without_completion_guess():
    result, calls = run(missing_setup=True)
    assert len(calls) == 1
    assert result["coverage_review"]["batches"][0]["uncovered_ids"] == ["threshold"]


@pytest.mark.parametrize(
    "change,code",
    [
        ("number", "planning_boundary_binding_conflict"),
        ("coordinate", "planning_boundary_coordinate_invalid"),
        ("contract", "Field required"),
        ("owner", "planning_boundary_binding_conflict"),
    ],
)
def test_dynamic_schema_rejects_plausible_fabrications_before_persistence(change, code):
    def mutate(data, payload):
        contract = data["coverage_obligations"][0]["boundary_contract"]
        sample = data["test_points"][0]["boundary_samples"][0]
        if change == "number":
            contract["threshold"] = 17
        elif change == "coordinate":
            sample["value"] = 7
        elif change == "contract":
            data["coverage_obligations"][0].pop("boundary_contract")
        else:
            sample["assertion_feature_id"] = "foreign"

    with pytest.raises(ValueError, match=code):
        run(mutate=mutate)


def test_legacy_point_serialization_absent_samples_unchanged():
    old = point(6)
    old.pop("source_refs")
    old["feature_point_ids"] = ["f"]
    restored = Point.model_validate(old).model_dump(mode="json")
    assert "boundary_samples" not in restored
    assert "primary_feature_id" not in restored


def test_markdown_appends_only_explicit_samples():
    result, _ = run(target=1)
    content = {"planning": result}
    text = render_test_brief_markdown(1, content)
    assert "before = 6.0 seconds" in text
    assert "initial state: fresh token issued at origin" in text


def test_structured_diagnostic_retains_safe_numeric_field_not_value_or_text():
    from pydantic import ValidationError

    from casepilot_agent.planning_boundary import BoundarySample
    from casepilot_agent.providers.safe_diagnostics import structured_failure

    with pytest.raises(ValidationError) as failure:
        BoundarySample.model_validate(
            dict(
                obligation_id="private-obligation",
                position="at",
                value=float("inf"),
                initial_state="PRIVATE_STATE",
                assertion="PRIVATE_EXPECTED",
                assertion_role="primary",
                assertion_feature_id="private-feature",
            )
        )
    diagnostic = structured_failure(
        failure.value, stage="test_point.generated", result_type=BoundarySample
    )
    assert diagnostic["validation_errors"] == [{"type": "finite_number", "loc": ["value"]}]
    assert "PRIVATE" not in str(diagnostic) and "private-" not in str(diagnostic)


def test_explicit_unresolved_contract_keeps_draft_without_certified_links():
    def unresolved(data, payload):
        item = data["coverage_obligations"][0]
        item["boundary_contract"] = dict(
            status="unresolved", reason="Qualitative boundary; numerical relation unavailable"
        )
        data["test_points"][0].pop("boundary_samples")

    result, calls = run(target=1, mutate=unresolved)
    assert len(calls) == 1
    assert len(result["test_points"]) == 1
    batch = result["coverage_review"]["batches"][0]
    assert batch["obligations"][0]["point_ids"] == []
    assert "boundary_contract" not in batch["obligations"][0]
    assert batch["clarifications"] == ["Qualitative boundary; numerical relation unavailable"]
    assert "coverage_unverified" in batch["warnings"]
    assert "evidence_binding" not in str(result)


def test_unresolved_does_not_discard_fabricated_hard_coordinates():
    def unresolved(data, payload):
        data["coverage_obligations"][0]["boundary_contract"] = dict(
            status="unresolved", reason="Unknown"
        )

    with pytest.raises(ValueError, match="planning_boundary_contract_required"):
        run(target=1, mutate=unresolved)


def test_unresolved_does_not_hide_foreign_point_ids():
    def unresolved(data, payload):
        item = data["coverage_obligations"][0]
        item.update(
            boundary_contract=dict(status="unresolved", reason="Unknown"), point_ids=["foreign"]
        )
        data["test_points"][0].pop("boundary_samples")

    with pytest.raises(ValueError, match="planning_coverage_point_reference_invalid"):
        run(target=1, mutate=unresolved)


def test_model_schema_exposes_evidence_binding_and_unresolved_alternative():
    def inspect(schema):
        definitions = schema["$defs"]
        numeric = definitions["BatchBoundaryContract"]
        assert "evidence_binding" in numeric["required"]
        assert not {"source_slot", "source_literal", "threshold"} & numeric["properties"].keys()
        boundary = definitions["BatchBoundaryObligation"]
        assert "boundary_contract" in boundary["required"]
        assert {"type": "null"} not in boundary["properties"]["boundary_contract"]["anyOf"]
        unresolved = definitions["UnresolvedBoundaryContract"]
        assert unresolved["properties"]["status"]["const"] == "unresolved"

    result, _ = run(target=1, inspect_schema=inspect)
    assert "evidence_binding" not in str(result)


@pytest.mark.parametrize("rule", ["Transition from pending to active", "0≤t<120秒"])
def test_qualitative_source_without_numeric_selector_retains_unverified_draft(rule):
    def unresolved(data, payload):
        assert payload["boundary_evidence_bindings"] == []
        data["coverage_obligations"][0]["boundary_contract"] = dict(
            status="unresolved", reason="Qualitative boundary has no numerical relation")
        data["test_points"][0].pop("boundary_samples")

    result, calls = run(target=1, rule=rule, mutate=unresolved)
    assert len(calls) == 1 and len(result["test_points"]) == 1
    batch = result["coverage_review"]["batches"][0]
    assert batch["obligations"][0]["point_ids"] == []
    assert batch["clarifications"] and "coverage_unverified" in batch["warnings"]


def test_legacy_clarification_with_claimed_links_is_not_silently_normalized():
    def contradictory(data, payload):
        data["coverage_obligations"][0].update(boundary_contract=None, clarification="Uncertain")
        data["test_points"][0].pop("boundary_samples")

    with pytest.raises(ValueError):
        run(target=1, mutate=contradictory)
