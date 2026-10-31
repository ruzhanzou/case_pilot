"""Formal-asset fresh confirmation revokes server reservations, not reference text.

These pure contracts exercise the API's actual reviewer-choice transformation.
`fresh` here means no formal case-management reuse; uploaded/Excel reservation
semantics are intentionally outside this test's authorization claim.
"""

from copy import deepcopy

import pytest

from casepilot_api.reuse_choices import confirm_asset_reuse


def plan(*, inherited=False):
    sources = [
        {
            "key": f"asset:{name}",
            "kind": "formal",
            "revision": f"rev-{name}",
            "snapshot": {"title": name},
        }
        for name in ("reserved", "legacy")
    ]
    points = [{"id": "P-reserved"}, {"id": "P-legacy"}]
    return {
        "test_points": points,
        "feature_points": [],
        "approved_source_catalog": deepcopy(sources),
        "excluded_reuse_source_keys": ["asset:already-excluded"],
        "reserved_reuse_outputs": [
            {
                "action": "reuse",
                "source": deepcopy(sources[0]),
                "point_ids": ["P-reserved"],
                "point_snapshots": {"P-reserved": deepcopy(points[0])},
            }
        ],
        "output_obligations": {
            "required_reuse_source_keys": [sources[0]["key"]],
            "output_case_count": 2,
            "new_case_count": 1,
            "plan_fingerprint": "previous-mandatory-output",
            "source_point_ids": {sources[0]["key"]: ["P-reserved"]},
        },
        "reuse": {
            "strategy": "change",
            "asset_confirmation": "reuse",
            "confirmed_asset_keys": [source["key"] for source in sources],
            "decisions": [
                {"point_id": "P-reserved", "action": "new", "source_key": None},
                (
                    {
                        "point_id": "P-legacy",
                        "action": "reuse",
                        "source_key": sources[1]["key"],
                        "source": deepcopy(sources[1]),
                        "test_object_match": "same",
                    }
                    if inherited
                    else {"point_id": "P-legacy", "action": "new", "source_key": None}
                ),
            ],
            "user_choices": {},
        },
    }


@pytest.mark.parametrize("inherited", [False, True])
def test_fresh_revokes_formal_reservation_even_without_inherited_decisions(inherited):
    from casepilot_agent.output_obligations import approved_catalog

    original = plan(inherited=inherited)
    before = deepcopy(original)
    result = confirm_asset_reuse(original, "fresh")
    assert original == before  # No mutation of persisted/client-owned input aliases.
    assert result.get("reserved_reuse_outputs", []) == []
    assert result["reuse"]["asset_confirmation"] == "fresh"
    assert result["reuse"]["user_choices"]["P-reserved"] == "new"
    expected = {"asset:reserved", "asset:already-excluded"}
    if inherited:
        expected.add("asset:legacy")
        assert result["reuse"]["user_choices"]["P-legacy"] == "new"
    assert expected <= set(result["excluded_reuse_source_keys"])
    assert not result.get("output_obligations")
    assert "asset:reserved" not in {source["key"] for source in approved_catalog(result)}
    assert all(d["action"] == "new" and not d.get("source") for d in result["reuse"]["decisions"])


@pytest.mark.parametrize("confirmation", [None, "reuse"])
def test_nonfresh_does_not_silently_revoke_formal_reservations(confirmation):
    original = plan()
    before = deepcopy(original)
    result = confirm_asset_reuse(original, confirmation)
    assert original == before
    assert result["reserved_reuse_outputs"] == before["reserved_reuse_outputs"]
    assert result["output_obligations"] == before["output_obligations"]
    assert result["reuse"]["user_choices"] == {}


def test_legacy_formal_reuse_still_requires_human_confirmation():
    from fastapi import HTTPException

    original = plan(inherited=True)
    with pytest.raises(HTTPException) as error:
        confirm_asset_reuse(original, None)
    assert error.value.status_code == 409
    assert error.value.detail == "reuse_confirmation_required"
    result = confirm_asset_reuse(original, "reuse")
    assert result["reserved_reuse_outputs"] == original["reserved_reuse_outputs"]
    assert result["reuse"]["decisions"][1]["action"] == "reuse"


def reference_plan():
    import json

    result = plan()
    references = [
        {
            "label": "Withdrawn",
            "excerpt": json.dumps({"source_key": "asset:reserved", "action": "reuse"}),
        },
        {
            "label": "Retained evidence",
            "excerpt": json.dumps({"source_key": "document:other", "action": "reference"}),
        },
        {"label": "Plain evidence", "excerpt": "not a JSON instruction"},
    ]
    for point in result["test_points"]:
        point.update(
            title=f"Reviewed {point['id']}",
            scenario="Original scenario",
            objective="Original expected behavior",
            module="Reviewed module",
            feature_point_ids=["F-1"],
            source_refs=deepcopy(references),
        )
    result["feature_points"] = [
        {
            "id": "F-1",
            "name": "Reviewed feature",
            "module": "Reviewed module",
            "description": "Original feature body",
            "source_refs": deepcopy(references),
        }
    ]
    result["reuse"]["feature_snapshots"] = deepcopy(result["feature_points"])
    result["reuse"]["brief_snapshot"] = {"test_object": "Reviewed object"}
    for decision, point in zip(result["reuse"]["decisions"], result["test_points"], strict=True):
        decision["point_snapshot"] = deepcopy(point)
    result["reserved_reuse_outputs"][0]["point_snapshots"] = {
        "P-reserved": deepcopy(result["test_points"][0])
    }
    return result


def test_fresh_reference_withdrawal_matches_comparison_snapshots_only():
    from casepilot_api.conversations import validate_reuse_confirmation

    original = reference_plan()
    before = deepcopy(original)
    result = confirm_asset_reuse(original, "fresh")
    assert original == before
    old_rows = [
        *before["test_points"],
        *before["feature_points"],
        *before["reuse"]["feature_snapshots"],
        *(d["point_snapshot"] for d in before["reuse"]["decisions"]),
    ]
    new_rows = [
        *result["test_points"],
        *result["feature_points"],
        *result["reuse"]["feature_snapshots"],
        *(d["point_snapshot"] for d in result["reuse"]["decisions"]),
    ]
    for old, actual in zip(old_rows, new_rows, strict=True):
        expected = {**deepcopy(old), "source_refs": deepcopy(old["source_refs"][1:])}
        assert actual == expected  # IDs/business fields/other citations exactly preserved.
    validate_reuse_confirmation({"test_object": "Reviewed object"}, result)


@pytest.mark.parametrize("change", ["feature_title", "feature_module", "point_body"])
def test_fresh_reference_cleanup_does_not_disable_business_snapshot_guards(change):
    from fastapi import HTTPException

    from casepilot_api.conversations import validate_reuse_confirmation

    result = confirm_asset_reuse(reference_plan(), "fresh")
    if change == "feature_title":
        result["feature_points"][0]["name"] = "Unapproved replacement"
    elif change == "feature_module":
        result["feature_points"][0]["module"] = "Unapproved module"
    else:
        # P-legacy was not revoked: its approved comparison still binds its body.
        result["test_points"][1]["scenario"] = "Unapproved business behavior"
    with pytest.raises(HTTPException) as error:
        validate_reuse_confirmation({"test_object": "Reviewed object"}, result)
    assert error.value.status_code == 409
    assert error.value.detail == "reuse_plan_changed_reanalyze_required"
