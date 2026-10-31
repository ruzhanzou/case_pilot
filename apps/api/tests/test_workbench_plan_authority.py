"""Pure contracts for server-owned reservations and DB-backed review receipts."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from casepilot_agent.output_obligations import approved_catalog, has_point_review_receipt

from casepilot_api.workbench_plan_authority import (
    edited_plan,
    inherit_point_review,
    stamp_point_review,
)


def make_plan():
    source = {
        "key": "asset:case-1",
        "revision": "revision-1",
        "snapshot": {"title": "Login", "steps": [{"action": "Login", "expected": "Session"}]},
    }
    points = [
        {"id": "TP-1", "title": "Login", "feature_point_ids": ["FP-1"]},
        {"id": "TP-2", "title": "Logout", "feature_point_ids": ["FP-2"]},
    ]
    return {
        "test_points": points,
        "feature_points": [{"id": "FP-1"}, {"id": "FP-2"}],
        "approved_source_catalog": [deepcopy(source)],
        "excluded_reuse_source_keys": [],
        "reserved_reuse_outputs": [{
            "action": "reuse", "source": deepcopy(source),
            "point_ids": ["TP-1", "TP-2"],
            "point_snapshots": {p["id"]: deepcopy(p) for p in points},
        }],
        "output_obligations": {
            "required_reuse_source_keys": [source["key"]],
            "source_point_ids": {source["key"]: ["TP-1", "TP-2"]},
            "output_case_count": 1,
            "new_case_count": 0,
        },
        "reuse": {
            "decisions": [
                {"point_id": p["id"], "action": "reuse", "source": deepcopy(source)}
                for p in points
            ],
            "user_choices": {"TP-1": "reuse", "TP-2": "reuse"},
        },
    }


def confirmed_brief(**overrides):
    values = {
        "id": UUID("e8a89fb6-2bd0-4f68-bf20-036fe6f80765"),
        "version": 3,
        "status": "confirmed",
        "confirmed_by": "reviewer-1",
        "confirmed_at": datetime(2026, 10, 28, tzinfo=UTC),
    }
    return SimpleNamespace(**(values | overrides))


@pytest.mark.parametrize("field", [
    "reserved_reuse_outputs", "approved_source_catalog", "output_obligations",
    "excluded_reuse_source_keys",
])
def test_client_cannot_replace_or_remove_server_owned_fields(field):
    prior = make_plan()
    for remove in (False, True):
        incoming = deepcopy(prior)
        if remove:
            incoming.pop(field)
        else:
            incoming[field] = {"fabricated": True}
        with pytest.raises(ValueError, match="^reserved_reuse_authority_changed$"):
            edited_plan(incoming, prior, {})


def test_client_cannot_fabricate_a_reservation():
    incoming = make_plan()
    prior = deepcopy(incoming)
    prior.pop("reserved_reuse_outputs")
    with pytest.raises(ValueError, match="^reserved_reuse_authority_changed$"):
        edited_plan(incoming, prior, {})


@pytest.mark.parametrize("location", ["reservation", "catalog", "point_snapshot"])
def test_nested_source_or_point_snapshot_tampering_is_rejected(location):
    prior = make_plan()
    incoming = deepcopy(prior)
    if location == "reservation":
        incoming["reserved_reuse_outputs"][0]["source"]["snapshot"]["title"] = "Forged"
    elif location == "catalog":
        incoming["approved_source_catalog"][0]["snapshot"]["steps"][0]["expected"] = "Forged"
    else:
        incoming["reserved_reuse_outputs"][0]["point_snapshots"]["TP-1"]["title"] = "Forged"
    with pytest.raises(ValueError, match="^reserved_reuse_authority_changed$"):
        edited_plan(incoming, prior, {})


@pytest.mark.parametrize("change", ["omit", "edit"])
def test_reserved_point_partial_omission_or_edit_requires_explicit_revocation(change):
    prior = make_plan()
    incoming = deepcopy(prior)
    if change == "omit":
        incoming["test_points"].pop()
    else:
        incoming["test_points"][1]["title"] = "Changed scope"
    with pytest.raises(ValueError, match="^reserved_reuse_selection_conflict$"):
        edited_plan(incoming, prior, {})


@pytest.mark.parametrize("choice", ["new", "exclude"])
def test_explicit_choice_revokes_reservation_and_obligation_without_reviving_source(choice):
    prior = make_plan()
    untouched = deepcopy(prior)
    incoming = deepcopy(prior)
    incoming["test_points"].pop()
    result = edited_plan(incoming, prior, {"TP-2": choice})
    assert result["reserved_reuse_outputs"] == []
    assert "output_obligations" not in result
    assert result["excluded_reuse_source_keys"] == ["asset:case-1"]
    assert approved_catalog(result) == []
    assert approved_catalog(edited_plan(result, result, {})) == []
    assert prior == untouched


def test_client_receipt_is_stripped_even_when_other_data_is_unchanged():
    prior = make_plan()
    incoming = deepcopy(prior)
    stamp_point_review(incoming, confirmed_brief(), kind="points")
    assert has_point_review_receipt(incoming)
    result = edited_plan(incoming, prior, {})
    assert "point_review_receipt" not in result
    assert not has_point_review_receipt(result)
    assert "point_review_receipt" in incoming


@pytest.mark.parametrize("kind", ["points", "asset_points"])
def test_exact_db_confirmed_receipt_inherits_only_reviewed_subset(kind):
    plan = make_plan()
    brief = confirmed_brief()
    selected = {"test_points": [plan["test_points"][1]]}
    stamp_point_review(selected, brief, kind=kind)
    plan["point_review_receipt"] = selected["point_review_receipt"]
    original = deepcopy(plan)
    result = inherit_point_review(plan, brief)
    assert [p["id"] for p in result["test_points"]] == ["TP-2"]
    assert result["feature_points"] == [{"id": "FP-2"}]
    assert [d["point_id"] for d in result["reuse"]["decisions"]] == ["TP-2"]
    assert result["reuse"]["user_choices"] == {"TP-2": "reuse"}
    assert result["selection_context"] == {
        "original_test_point_ids": ["TP-1", "TP-2"], "selected_test_point_ids": ["TP-2"],
    }
    assert has_point_review_receipt(result)
    assert plan == original


@pytest.mark.parametrize("brief_changes,receipt_changes", [
    ({"status": "draft"}, {}),
    ({"confirmed_by": None}, {}),
    ({"confirmed_at": None}, {}),
    ({"version": 4}, {}),
    ({}, {"brief_id": "another-brief"}),
    ({}, {"version": 2}),
    ({}, {"kind": "sources"}),
    ({}, {"point_ids": ["unknown"]}),
    ({}, {"point_ids": ["TP-1", "unknown"]}),
    ({}, {"point_ids": ["TP-1", "TP-1"]}),
    ({}, {"point_ids": []}),
    ({}, {"point_ids": "TP-1"}),
    ({}, {"point_ids": [1]}),
])
def test_invalid_or_unconfirmed_receipts_do_not_carry_authority(brief_changes, receipt_changes):
    plan = make_plan()
    stamp_point_review(plan, confirmed_brief(), kind="points")
    plan["point_review_receipt"].update(receipt_changes)
    result = inherit_point_review(plan, confirmed_brief(**brief_changes))
    assert "point_review_receipt" not in result
    assert not has_point_review_receipt(result)
    assert result["test_points"] == plan["test_points"]
    assert "selection_context" not in result


def test_source_only_confirmation_does_not_imply_point_review():
    plan = make_plan()
    result = inherit_point_review(plan, confirmed_brief())
    assert result == plan
    assert not has_point_review_receipt(result)
    assert "selection_context" not in result


def test_empty_point_set_cannot_receive_review_receipt():
    plan = {"test_points": [], "point_review_receipt": {"forged": True}}
    stamp_point_review(plan, confirmed_brief(), kind="points")
    assert "point_review_receipt" not in plan


def test_later_client_edit_cannot_clear_revoked_source_exclusion():
    prior = make_plan()
    revoked = edited_plan(prior, prior, {"TP-1": "new"})
    incoming = deepcopy(revoked)
    incoming["excluded_reuse_source_keys"] = []
    with pytest.raises(ValueError, match="^reserved_reuse_authority_changed$"):
        edited_plan(incoming, revoked, {})


def pending_plan():
    plan = make_plan()
    source = deepcopy(plan["approved_source_catalog"][0])
    plan["reserved_reuse_outputs"] = []
    plan["pending_reserved_outputs"] = {
        "reason": "reserved_reuse_mapping_requires_clarification",
        "required_sources": [source],
        "quantity": {"output_case_count": 1, "required_reuse_source_keys": [source["key"]]},
    }
    return plan


@pytest.mark.parametrize("change", ["omit", "empty", "reason", "snapshot", "quantity"])
def test_client_cannot_remove_or_tamper_with_pending_reserved_outputs(change):
    prior = pending_plan()
    incoming = deepcopy(prior)
    if change == "omit":
        incoming.pop("pending_reserved_outputs")
    elif change == "empty":
        incoming["pending_reserved_outputs"] = {}
    elif change == "reason":
        incoming["pending_reserved_outputs"]["reason"] = "resolved"
    elif change == "snapshot":
        incoming["pending_reserved_outputs"]["required_sources"][0]["snapshot"]["title"] = "Forged"
    else:
        incoming["pending_reserved_outputs"]["quantity"]["required_reuse_source_keys"] = []
    with pytest.raises(ValueError, match="^reserved_reuse_authority_changed$"):
        edited_plan(incoming, prior, {})


@pytest.mark.parametrize("field", [
    "approved_source_catalog", "output_obligations", "excluded_reuse_source_keys",
])
def test_pending_reservation_protects_authority_fields_without_active_reservations(field):
    prior = pending_plan()
    incoming = deepcopy(prior)
    incoming[field] = {"fabricated": True}
    with pytest.raises(ValueError, match="^reserved_reuse_authority_changed$"):
        edited_plan(incoming, prior, {})


def test_unchanged_pending_reservation_survives_a_client_edit():
    prior = pending_plan()
    incoming = deepcopy(prior)
    incoming["test_points"][0]["title"] = "Clarified login coverage"
    result = edited_plan(incoming, prior, {})
    assert result["pending_reserved_outputs"] == prior["pending_reserved_outputs"]
    assert result["test_points"][0]["title"] == "Clarified login coverage"
    assert prior["test_points"][0]["title"] == "Login"


def test_boolean_receipt_version_cannot_inherit_integer_version_one_authority():
    plan = make_plan()
    brief = confirmed_brief(version=1)
    stamp_point_review(plan, brief, kind="points")
    plan["point_review_receipt"]["version"] = True
    result = inherit_point_review(plan, brief)
    assert "point_review_receipt" not in result
    assert "selection_context" not in result
    assert not has_point_review_receipt(result)
    assert result["test_points"] == plan["test_points"]


def quantity_plan():
    identity = "qaxis:" + "1" * 64
    return {
        "test_points": [{"id": "p", "feature_point_ids": ["f"], "boundary_samples": [
            {"obligation_id": "o", "quantity_axis_id": identity, "value": 7}]}],
        "coverage_review": {"batches": [{"obligations": [
            {"id": "o", "feature_point_ids": ["f"], "point_ids": ["p"],
             "boundary_contract": {"quantity_axis_id": identity, "threshold": 7}}
        ]}]},
    }


def quantity_metadata(plan):
    return (plan["coverage_review"]["batches"][0]["obligations"][0]["boundary_contract"],
            plan["test_points"][0]["boundary_samples"][0])


@pytest.mark.parametrize("which", ["contract", "sample", "both"])
@pytest.mark.parametrize("identity", [None, "qaxis:" + "2" * 64])
def test_retained_numeric_metadata_cannot_drop_or_replace_stored_identity(which, identity):
    prior = quantity_plan()
    incoming = deepcopy(prior)
    contract, sample = quantity_metadata(incoming)
    for row in ([contract, sample] if which == "both" else
                [contract] if which == "contract" else [sample]):
        if identity is None:
            row.pop("quantity_axis_id")
        else:
            row["quantity_axis_id"] = identity
    with pytest.raises(ValueError, match="^planning_boundary_quantity_identity_changed$"):
        edited_plan(incoming, prior, {})
    assert prior == quantity_plan()


def test_dropping_point_links_cannot_downgrade_retained_contract():
    prior = quantity_plan()
    incoming = deepcopy(prior)
    obligation = incoming["coverage_review"]["batches"][0]["obligations"][0]
    obligation["point_ids"] = []
    obligation["boundary_contract"].pop("quantity_axis_id")
    incoming["test_points"][0].pop("boundary_samples")
    with pytest.raises(ValueError, match="^planning_boundary_quantity_identity_changed$"):
        edited_plan(incoming, prior, {})


def test_entire_numeric_metadata_removal_and_point_selection_are_allowed():
    prior = quantity_plan()
    incoming = deepcopy(prior)
    incoming["test_points"][0].pop("boundary_samples")
    incoming["coverage_review"]["batches"][0]["obligations"][0].pop("boundary_contract")
    assert edited_plan(incoming, prior, {}) == incoming
    incoming["test_points"] = []
    assert edited_plan(incoming, prior, {}) == incoming


def test_genuine_legacy_metadata_is_not_upgraded_or_blocked():
    prior = quantity_plan()
    for row in quantity_metadata(prior):
        row.pop("quantity_axis_id")
    incoming = deepcopy(prior)
    incoming["test_points"][0]["title"] = "Edited draft"
    assert edited_plan(incoming, prior, {}) == incoming
    assert "quantity_axis_id" not in str(prior)


def test_same_ids_with_reordered_batches_and_display_edits_preserve_identity():
    prior = quantity_plan()
    incoming = deepcopy(prior)
    incoming["coverage_review"]["batches"].insert(0, {"obligations": []})
    incoming["test_points"][0]["boundary_samples"][0]["axis"] = "Proposed description"
    assert edited_plan(incoming, prior, {}) == incoming


def test_changing_obligation_owners_cannot_disguise_retained_numeric_contract_as_legacy():
    prior = quantity_plan()
    incoming = deepcopy(prior)
    obligation = incoming["coverage_review"]["batches"][0]["obligations"][0]
    obligation["feature_point_ids"] = ["other-feature"]
    obligation["point_ids"] = []
    obligation["boundary_contract"].pop("quantity_axis_id")
    incoming["test_points"][0].pop("boundary_samples")
    with pytest.raises(ValueError, match="^planning_boundary_quantity_identity_changed$"):
        edited_plan(incoming, prior, {})


def test_changing_sample_obligation_cannot_disguise_retained_numeric_sample_as_legacy():
    prior = quantity_plan()
    incoming = deepcopy(prior)
    sample = incoming["test_points"][0]["boundary_samples"][0]
    sample["obligation_id"] = "different-obligation"
    sample.pop("quantity_axis_id")
    incoming["coverage_review"] = {"batches": []}
    with pytest.raises(ValueError, match="^planning_boundary_quantity_identity_changed$"):
        edited_plan(incoming, prior, {})


@pytest.mark.parametrize("field,value", [
    ("sampling_step", 2), ("sampling_literal", "Unapproved sampling instruction"),
])
def test_existing_quantity_contract_sampling_authority_cannot_be_edited(field, value):
    prior = quantity_plan()
    contract, _ = quantity_metadata(prior)
    contract.update(sampling_step=1, sampling_literal="Sample at integer seconds")
    incoming = deepcopy(prior)
    quantity_metadata(incoming)[0][field] = value
    with pytest.raises(ValueError, match="^planning_boundary_quantity_identity_changed$"):
        edited_plan(incoming, prior, {})


def test_existing_quantity_sampling_cannot_change_by_relabeling_owners_and_dropping_links():
    prior = quantity_plan()
    contract, _ = quantity_metadata(prior)
    contract.update(sampling_step=1, sampling_literal="Sample at integer seconds")
    incoming = deepcopy(prior)
    obligation = incoming["coverage_review"]["batches"][0]["obligations"][0]
    obligation.update(feature_point_ids=["other-feature"], point_ids=[])
    obligation["boundary_contract"]["sampling_step"] = 2
    with pytest.raises(ValueError, match="^planning_boundary_quantity_identity_changed$"):
        edited_plan(incoming, prior, {})


def test_legacy_quantity_sampling_retains_existing_edit_behavior():
    prior = quantity_plan()
    for row in quantity_metadata(prior):
        row.pop("quantity_axis_id")
    incoming = deepcopy(prior)
    quantity_metadata(incoming)[0].update(sampling_step=2, sampling_literal="Edited legacy setup")
    assert edited_plan(incoming, prior, {}) == incoming
