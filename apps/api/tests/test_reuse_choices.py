from copy import deepcopy

import pytest
from fastapi import HTTPException

from casepilot_api.reuse_choices import apply_reviewer_choices, reviewer_choices


def plan():
    return {"test_points": [{"id": "one", "title": "新测试点"}], "reuse": {
        "strategy": "change", "user_choices": {"one": "new"},
        "decisions": [{"point_id": "one", "action": "reuse", "source_key": "asset:1",
                       "source": {"snapshot": {"title": "原用例"}}, "point_snapshot": {"id": "one"}}]}}


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
