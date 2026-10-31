from copy import deepcopy

import pytest
from fastapi import HTTPException

from casepilot_api.reuse_choices import (
    apply_reviewer_choices,
    confirm_asset_reuse,
    reviewer_choices,
)


def plan():
    return {
        "test_points": [{"id": "one", "title": "新测试点"}],
        "reuse": {
            "strategy": "change",
            "user_choices": {"one": "new"},
            "decisions": [
                {
                    "point_id": "one",
                    "action": "reuse",
                    "source_key": "asset:1",
                    "source": {"snapshot": {"title": "原用例"}},
                    "point_snapshot": {"id": "one"},
                }
            ],
        },
    }


def test_regeneration_choice_removes_original_body_without_mutating_review_history():
    original = plan()
    before = deepcopy(original)
    result = apply_reviewer_choices(original)
    assert original == before
    decision = result["reuse"]["decisions"][0]
    assert decision["action"] == "new" and decision["source_key"] is None
    assert "source" not in decision
    assert decision["point_snapshot"] == result["test_points"][0]
    assert result["reuse"]["summary"] == {"new": 1}


@pytest.mark.parametrize("choices", [{"missing": "new"}, {"one": "delete"}, {"one": []}, ["one"]])
def test_unknown_points_or_invalid_choices_cannot_be_persisted(choices):
    current = plan()
    current["reuse"]["user_choices"] = choices
    with pytest.raises(HTTPException) as error:
        reviewer_choices(current)
    assert error.value.status_code == 422


def test_restoring_suggestion_preserves_original_source_and_action():
    current = plan()
    current["reuse"]["user_choices"] = {}
    result = apply_reviewer_choices(current)
    assert result["reuse"]["decisions"][0]["action"] == "reuse"
    assert result["reuse"]["decisions"][0]["source_key"] == "asset:1"


@pytest.mark.parametrize(
    "action,kind,allowed",
    [
        ("reuse", "formal", True),
        ("modify", "formal", False),
        ("reuse", "excel", False),
        ("new", "formal", False),
    ],
)
def test_copy_choice_requires_reusable_formal_case(action, kind, allowed):
    current = plan()
    current["reuse"]["user_choices"] = {"one": "copy"}
    current["reuse"]["decisions"][0].update(action=action)
    current["reuse"]["decisions"][0]["source"]["kind"] = kind
    if allowed:
        result = apply_reviewer_choices(current)
        assert result["reuse"]["user_choices"] == {"one": "copy"}
        assert result["reuse"]["decisions"][0]["source_key"] == "asset:1"
    else:
        with pytest.raises(HTTPException) as error:
            reviewer_choices(current)
        assert error.value.status_code == 422


@pytest.mark.parametrize("action", ["reuse", "modify"])
def test_asset_reuse_requires_explicit_confirmation(action):
    current = plan()
    row = current["reuse"]["decisions"][0]
    row.update(action=action, test_object_match="same", source={"kind": "formal"})
    with pytest.raises(HTTPException) as error:
        confirm_asset_reuse(current, None)
    assert error.value.detail == "reuse_confirmation_required"
    assert confirm_asset_reuse(current, "reuse")["reuse"]["asset_confirmation"] == "reuse"


@pytest.mark.parametrize("match", ["different", "unknown", None])
def test_confirmation_cannot_override_test_object_mismatch(match):
    current = plan()
    current["reuse"]["decisions"][0].update(test_object_match=match, source={"kind": "formal"})
    with pytest.raises(HTTPException) as error:
        confirm_asset_reuse(current, "reuse")
    assert error.value.detail == "reuse_test_object_mismatch"


def test_declining_asset_reuse_removes_sources_without_mutating_draft():
    current = plan()
    current["reuse"]["decisions"][0]["source"]["kind"] = "formal"
    original = deepcopy(current)
    result = confirm_asset_reuse(current, "fresh")
    assert current == original
    assert result["reuse"]["summary"] == {"new": 1}
    assert "source" not in result["reuse"]["decisions"][0]


def test_draft_cannot_claim_prior_confirmation_without_server_keys():
    current = plan()
    row = current["reuse"]["decisions"][0]
    row.update(test_object_match="same", source={"kind": "formal"})
    current["reuse"].update(asset_confirmation="reuse", confirmed_asset_keys=[row["source_key"]])
    with pytest.raises(HTTPException) as error:
        confirm_asset_reuse(current, None)
    assert error.value.detail == "reuse_confirmation_required"
    assert (
        confirm_asset_reuse(current, None, confirmed_keys=[row["source_key"]])["reuse"][
            "asset_confirmation"
        ]
        == "reuse"
    )


def test_new_choice_invalidates_old_required_reuse_and_cannot_resurrect_it():
    from casepilot_agent.output_obligations import approved_catalog, bind_obligations
    from casepilot_agent.quantity import OutputQuantity

    current = plan()
    current["reuse"]["user_choices"] = {}
    current["reuse"]["decisions"][0]["source"]["key"] = "asset:1"
    current["approved_source_catalog"] = [{"key": "asset:1"}]
    bind_obligations(
        current,
        OutputQuantity(
            required_reuse_source_keys=["asset:1"], output_case_count=1, new_case_count=0
        ),
    )
    current["reuse"]["user_choices"] = {"one": "new"}
    changed = apply_reviewer_choices(current)
    assert changed["output_obligations"]["plan_fingerprint"] == "invalidated"
    assert changed["excluded_reuse_source_keys"] == ["asset:1"]
    assert approved_catalog(changed) == []
    with pytest.raises(ValueError, match="required_reuse_source_invalid"):
        bind_obligations(changed, OutputQuantity(required_reuse_source_keys=["asset:1"]))
