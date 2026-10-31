"""Canonical quantity identity is structural, never a semantic quality certificate."""
from copy import deepcopy

import pytest
from casepilot_agent.planning_boundary import boundary_evidence_bindings
from pydantic import ValidationError

from casepilot_api.schemas import TestBriefContent as BriefContent


def content():
    source = {"label": "Synthetic rule", "locator": "fixture",
              "excerpt": "elapsed seconds since issuance < 7 seconds is valid."}
    rows = boundary_evidence_bindings({"evidence": [source],
                                      "test_setup": "Sample elapsed in integer seconds."})
    binding = next(row for row in rows if row["sampling_step"] == 1)
    contract = {key: binding[key] for key in (
        "source_literal", "threshold", "unit", "quantity_axis_id",
        "sampling_step", "sampling_literal")}
    contract.update(source_ref=source, axis="elapsed_time", time_origin="code issuance",
                    comparator="lt", status="model_proposed")
    sample = {"obligation_id": "o", "position": "before", "value": 6,
              "unit": "seconds", "axis": "elapsed_time", "time_origin": "code issuance",
              "quantity_axis_id": binding["quantity_axis_id"],
              "initial_state": "Fresh code", "assertion": "Given rule applies",
              "assertion_role": "primary", "assertion_feature_id": "f",
              "assertion_source_ref": source}
    return {"test_object": "Synthetic rule", "planning": {
        "feature_points": [{"id": "f", "name": "Rule", "module": "Rules"}],
        "test_points": [{"id": "p", "title": "Boundary", "feature_point_ids": ["f"],
                         "boundary_samples": [sample]}],
        "coverage_review": {"batches": [{"obligations": [{
            "id": "o", "point_ids": ["p"], "boundary_contract": contract}]}]}}}


def test_valid_bound_quantity_preserves_proposed_display_labels():
    data = content()
    assert BriefContent.model_validate(data).planning == data["planning"]


@pytest.mark.parametrize("change", [
    "sample_unit", "sample_value", "sample_id", "contract_id", "missing_sample_id",
    "missing_contract_id", "contract_unit", "contract_literal", "no_step_before",
])
def test_bound_quantity_rejects_canonical_crossfield_tampering(change):
    data = content()
    sample = data["planning"]["test_points"][0]["boundary_samples"][0]
    contract = data["planning"]["coverage_review"]["batches"][0]["obligations"][0][
        "boundary_contract"]
    if change == "sample_unit":
        sample["unit"] = "days"
    elif change == "sample_value":
        sample["value"] = 9999
    elif change == "sample_id":
        sample["quantity_axis_id"] = "qaxis:" + "0" * 64
    elif change == "contract_id":
        contract["quantity_axis_id"] = "qaxis:" + "0" * 64
    elif change == "missing_sample_id":
        sample.pop("quantity_axis_id")
    elif change == "missing_contract_id":
        contract.pop("quantity_axis_id")
    elif change == "contract_unit":
        contract["unit"] = "attempts"
    elif change == "contract_literal":
        contract["source_literal"] = "Unknown rule < 7 seconds"
    else:
        contract.update(sampling_step=None, sampling_literal="")
    with pytest.raises(ValidationError, match="planning_boundary_"):
        BriefContent.model_validate(data)


def test_true_legacy_without_new_identity_is_not_backfilled():
    data = content()
    data["planning"]["test_points"][0]["boundary_samples"][0].pop("quantity_axis_id")
    data["planning"]["coverage_review"]["batches"][0]["obligations"][0][
        "boundary_contract"].pop("quantity_axis_id")
    old = deepcopy(data)
    assert BriefContent.model_validate(data).planning == old["planning"]


@pytest.mark.parametrize("mode", ["add", "replace", "remove", "overwrite"])
def test_incremental_plan_preserves_only_retained_quantity_contracts(mode):
    from casepilot_agent.planning import PlanningAnalysis, reconcile_planning

    prior = content()["planning"]
    untouched = deepcopy(prior)
    incoming = content()["planning"]
    incoming["test_points"][0]["id"] = "new"
    incoming["coverage_review"]["batches"][0]["obligations"][0]["point_ids"] = ["new"]
    new_contract = incoming["coverage_review"]["batches"][0]["obligations"][0]["boundary_contract"]
    new_contract.update(sampling_step=None, sampling_literal="")
    incoming["test_points"][0]["boundary_samples"][0].update(position="at", value=7)
    kwargs = {}
    if mode == "replace":
        kwargs["planning_update_mode"] = "replace"
    elif mode == "remove":
        kwargs["superseded_test_point_ids"] = ["p"]
    elif mode == "overwrite":
        incoming["test_points"][0]["id"] = "p"
        incoming["coverage_review"]["batches"][0]["obligations"][0]["point_ids"] = ["p"]
    result = reconcile_planning(prior, incoming, [PlanningAnalysis(summary="New run", **kwargs)])
    BriefContent.model_validate({"test_object": "Synthetic rule", "planning": result})
    assert prior == untouched
    batches = result["coverage_review"]["batches"]
    assert batches[0]["obligations"][0]["boundary_contract"]["sampling_step"] is None
    if mode == "add":
        assert len(batches) == 2
        assert batches[1]["obligations"][0] == (
            prior["coverage_review"]["batches"][0]["obligations"][0])
        assert batches[1]["batch_index"] > batches[0].get("batch_index", 0)
        assert "retained_previous_point_coverage" in batches[1]["warnings"]
    else:
        assert len(batches) == 1


def test_prepublication_guard_rejects_orphan_without_mutating_input():
    from casepilot_agent.planning_boundary import validate_persisted_quantity_links

    plan = content()["planning"]
    validate_persisted_quantity_links(plan)
    plan["coverage_review"]["batches"] = []
    before = deepcopy(plan)
    with pytest.raises(ValueError, match="planning_boundary_binding_conflict"):
        validate_persisted_quantity_links(plan)
    assert plan == before
