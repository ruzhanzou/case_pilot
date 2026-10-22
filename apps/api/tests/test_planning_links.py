from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from casepilot_api.planning_links import inherit_unchanged_links, link_committed_candidate


def brief():
    return SimpleNamespace(
        id=uuid4(),
        content={
            "business_rules": ["验证码2分钟过期"],
            "planning": {
                "test_points": [{"id": "P1", "title": "过期拒绝登录"}],
                "reuse": {"user_choices": {}},
            },
        },
    )


@pytest.mark.parametrize("change", ["choices", "rules", "point"])
def test_only_choice_edits_inherit_versioned_links(change):
    old = brief()
    current = deepcopy(old)
    current.id = uuid4()
    if change == "choices":
        current.content["planning"]["reuse"]["user_choices"] = {"P1": "exclude"}
    elif change == "rules":
        current.content["business_rules"] = ["验证码10分钟过期"]
    else:
        current.content["planning"]["test_points"][0]["title"] = "正常登录"
    original = deepcopy(current.content)
    db = Mock()
    link = SimpleNamespace(
        test_point_id="P1", test_case_id=uuid4(), revision_id=uuid4(), origin="manual"
    )
    db.scalars.return_value = [link]
    inherit_unchanged_links(db, old, current)
    assert current.content == original
    if change == "choices":
        saved = db.add.call_args.args[0]
        assert saved.brief_id == current.id
        assert saved.revision_id == link.revision_id
    else:
        db.add.assert_not_called()


def test_commit_links_only_valid_points_and_reuses_brief_lookup_per_job():
    db = Mock()
    db.scalars.return_value = []
    db.get.return_value = SimpleNamespace(input_payload={"confirmed_test_brief_version": 2})
    db.scalar.return_value = brief()
    conversation = SimpleNamespace(id=uuid4())
    candidate = SimpleNamespace(
        generation_job_id=uuid4(), snapshot={"test_point_ids": ["P1", "P1", "foreign"]}
    )
    cache = {}
    for _ in range(3):
        case = SimpleNamespace(id=uuid4(), current_revision_id=uuid4())
        link_committed_candidate(db, conversation, candidate, case, cache)
    assert db.get.call_count == db.scalar.call_count == 1
    assert db.add.call_count == 3
    assert all(call.args[0].test_point_id == "P1" for call in db.add.call_args_list)


def test_legacy_candidate_without_points_does_not_query_or_create_links():
    db = Mock()
    link_committed_candidate(
        db, SimpleNamespace(), SimpleNamespace(snapshot={}), SimpleNamespace(), {}
    )
    db.get.assert_not_called()
    db.add.assert_not_called()


def test_empty_model_module_does_not_break_workspace_recovery():
    from casepilot_api.schemas import TestBriefContent
    content = TestBriefContent(planning={
        'feature_points': [{'id': 'F1', 'name': '验证码过期', 'module': ''}],
        'test_points': [{'id': 'P1', 'title': '过期拒绝', 'feature_point_ids': ['F1']}],
    })
    assert content.planning['feature_points'][0]['module'] == '验证码过期'
