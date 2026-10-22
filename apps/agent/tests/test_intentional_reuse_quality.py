from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import GenerationRequest, QualityIssue
from casepilot_agent.providers.mock import MockProvider


@pytest.mark.parametrize(
    "confirmed,changed,warning", [(True, False, False), (False, False, True), (True, True, True)]
)
def test_only_confirmed_unchanged_reuse_is_exempt_from_existing_duplicate_warning(
    confirmed, changed, warning
):
    result = MockProvider().generate(GenerationRequest(prompt="account login"))
    case = result.test_cases[0]
    result.test_cases = [case]
    snapshot = case.model_dump(mode="json")
    snapshot["case_key"] = "CASE-ORIGINAL"
    decisions = [
        {
            "point_id": point,
            "action": "reuse",
            "test_object_match": "same",
            "source_key": "asset:original",
            "source": {"snapshot": deepcopy(snapshot)},
        }
        for point in case.test_point_ids
    ]
    reuse = {
        "asset_confirmation": "reuse" if confirmed else None,
        "confirmed_asset_keys": ["asset:original"],
        "decisions": decisions,
    }
    if changed:
        case.preconditions = ["Changed condition"]
    result.quality.issues = [QualityIssue(code="manual_review_required", message="Review")]
    store = SimpleNamespace(
        connection=lambda: nullcontext(None),
        load_existing_case_titles=lambda *a: [{"case_key": "CASE-ORIGINAL", "title": case.title}],
    )
    tasks._apply_persisted_asset_quality(
        store,
        {"collection_id": "collection", "input_payload": {"confirmed_plan": {"reuse": reuse}}},
        None,
        {},
        result,
    )
    assert (
        any(i.code == "possible_existing_case_duplicate" for i in result.quality.issues) == warning
    )
