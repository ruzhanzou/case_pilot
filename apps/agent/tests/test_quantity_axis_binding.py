"""Numeric identity is structural, never a semantic approval certificate."""
from copy import deepcopy

import pytest
from test_planning_boundary import fixture
from test_planning_boundary_flow import run

from casepilot_agent.planning_boundary import (
    BoundaryContract,
    BoundarySample,
    boundary_evidence_bindings,
    project_boundary_metadata,
    validate_boundary_contracts,
)


def test_alias_display_labels_survive_and_complete_coordinates_still_need_review():
    def alias(data, payload):
        data["coverage_obligations"][0]["boundary_contract"].update(
            axis="elapsed_time", time_origin="code_issuance", comparator="gte")

    result, _ = run(mutate=alias)
    batch = result["coverage_review"]["batches"][0]
    contract = batch["obligations"][0]["boundary_contract"]
    assert batch["uncovered_ids"] == []
    assert "boundary_semantics_requires_review" in batch["warnings"]
    assert contract["status"] == "model_proposed" and contract["comparator"] == "gte"
    assert (contract["axis"], contract["time_origin"]) == ("elapsed_time", "code_issuance")
    assert contract["quantity_axis_id"].startswith("qaxis:")
    for point in result["test_points"]:
        assert point["boundary_samples"][0]["quantity_axis_id"] == contract["quantity_axis_id"]


@pytest.mark.parametrize("field,value,code", [
    ("unit", "second", "binding_conflict"),
    ("source_slot", "source:999", "binding_conflict"),
    ("quantity_axis_id", "qaxis:" + "f" * 64, "binding_conflict"),
    ("sampling_step", 0.5, "sampling_invalid"),
    ("sampling_literal", "unprovided sample every 1 seconds", "sampling_invalid"),
])
def test_model_cannot_override_server_quantity_or_sampling(field, value, code):
    def mutate(data, payload):
        data["coverage_obligations"][0]["boundary_contract"][field] = value

    with pytest.raises(ValueError, match=f"planning_boundary_{code}"):
        run(target=1, mutate=mutate)


def test_sample_cannot_claim_other_quantity_identity():
    def mutate(data, payload):
        data["test_points"][0]["boundary_samples"][0]["quantity_axis_id"] = "qaxis:" + "f" * 64

    with pytest.raises(ValueError, match="planning_boundary_binding_conflict"):
        run(target=1, mutate=mutate)


def test_digest_is_stable_across_catalog_order_and_distinguishes_source_identity():
    sources = [dict(source_id=identity, label="rule", excerpt="elapsed < 7 seconds")
               for identity in ("one", "two")]
    original = boundary_evidence_bindings({"evidence": sources})
    reordered = boundary_evidence_bindings({"evidence": sources[::-1]})
    assert original[0]["quantity_axis_id"] == reordered[1]["quantity_axis_id"]
    assert original[1]["quantity_axis_id"] == reordered[0]["quantity_axis_id"]
    assert original[0]["quantity_axis_id"] != original[1]["quantity_axis_id"]


@pytest.mark.parametrize("unit", ["furlongs", "未知单位", "天"])
def test_unknown_unit_has_only_explicit_unresolved_path(unit):
    rule = f"elapsed < 7 {unit}"
    assert boundary_evidence_bindings({"user_input": rule}) == []

    def unresolved(data, payload):
        data["coverage_obligations"][0]["boundary_contract"] = dict(
            status="unresolved", reason="Unsupported unit")
        data["test_points"][0].pop("boundary_samples")

    result, _ = run(target=1, rule=rule, mutate=unresolved)
    batch = result["coverage_review"]["batches"][0]
    assert len(result["test_points"]) == 1 and batch["clarifications"] == ["Unsupported unit"]


def test_schema_has_no_free_unit_quantity_or_sampling_fields():
    def inspect(schema):
        numeric = schema["$defs"]["BatchBoundaryContract"]["properties"]
        assert not {"unit", "threshold", "source_slot", "source_literal", "quantity_axis_id",
                    "sampling_step", "sampling_literal"} & numeric.keys()
        assert "Proposed" in numeric["axis"]["description"]
        assert "Proposed" in numeric["time_origin"]["description"]

    run(target=1, inspect_schema=inspect)


def test_sampling_choices_are_unit_bound_and_always_offer_none():
    context = dict(user_input="elapsed < 7 seconds; failure_count >= 3 attempts",
                   test_setup="Sample at integer seconds")
    choices = boundary_evidence_bindings(context)
    seconds = [entry for entry in choices if entry["unit"] == "seconds"]
    attempts = [entry for entry in choices if entry["unit"] == "attempts"]
    assert {entry["sampling_step"] for entry in seconds} == {None, 1.0}
    assert [entry["sampling_step"] for entry in attempts] == [None]
    assert len({entry["quantity_axis_id"] for entry in seconds}) == 1


def test_legacy_fields_and_validation_are_unchanged():
    obligations, points, context, slots = fixture()
    contract = BoundaryContract.model_validate(obligations[0]["boundary_contract"])
    sample = BoundarySample.model_validate(points[0]["boundary_samples"][0])
    assert "quantity_axis_id" not in contract.model_dump(mode="json")
    assert "quantity_axis_id" not in sample.model_dump(mode="json")
    before = deepcopy((obligations, points))
    projected = project_boundary_metadata(
        dict(coverage_obligations=obligations, test_points=points), context)
    assert "quantity_axis_id" not in str(projected)
    assert (obligations, points) == before
    obligations[0]["boundary_contract"]["axis"] = "elapsed_time"
    with pytest.raises(ValueError, match="planning_boundary_axis_invalid"):
        validate_boundary_contracts(obligations, points, context, slots)


def test_new_samples_derive_coordinates_without_model_values():
    def omit(data, payload):
        for point in data["test_points"]:
            for sample in point.get("boundary_samples", []):
                sample.pop("value", None)

    def inspect(schema):
        assert "value" not in schema["$defs"]["BatchBoundarySample"]["properties"]

    result, _ = run(mutate=omit, inspect_schema=inspect)
    assert {point["boundary_samples"][0]["value"] for point in result["test_points"]} == {6, 7, 8}


def test_missing_value_without_step_supports_at_only():
    def omit(data, payload):
        data["test_points"][0]["boundary_samples"][0].pop("value")

    result, _ = run(missing_setup=True, mutate=omit)
    assert result["test_points"][0]["boundary_samples"][0]["value"] == 7
    assert "coverage_unverified" in result["coverage_review"]["batches"][0]["warnings"]


@pytest.mark.parametrize("change,code", [
    ("position", "literal_error"),
    ("obligation", "planning_boundary_sample_link_invalid"),
    ("links", "planning_boundary_sample_link_invalid"),
    ("no_step", "planning_boundary_coordinate_invalid"),
    ("value", "planning_boundary_coordinate_invalid"),
])
def test_derivation_does_not_repair_conflicting_coordinates_or_links(change, code):
    def mutate(data, payload):
        sample = data["test_points"][0]["boundary_samples"][0]
        sample.pop("value")
        if change == "position":
            sample["position"] = "near"
        elif change == "obligation":
            sample["obligation_id"] = "foreign"
        elif change == "links":
            data["coverage_obligations"][0]["point_ids"] = []
        elif change == "no_step":
            none = next(entry for entry in payload["boundary_evidence_bindings"]
                        if entry["sampling_step"] is None)
            data["coverage_obligations"][0]["boundary_contract"]["evidence_binding"] = none["id"]
        else:
            sample["value"] = 99

    with pytest.raises(ValueError, match=code):
        run(target=1, mutate=mutate)


def test_legacy_missing_value_is_not_backfilled_and_failed_derivation_is_atomic():
    args = fixture()
    args[1][0]["boundary_samples"][0].pop("value")
    before = deepcopy(args)
    with pytest.raises(ValueError):
        validate_boundary_contracts(*args)
    assert args == before
    args[1][0]["boundary_samples"][1]["value"] = 99
    before = deepcopy(args)
    with pytest.raises(ValueError, match="planning_boundary_coordinate_invalid"):
        validate_boundary_contracts(*args, derive_missing_values=True)
    assert args == before
