import pytest
from pydantic import ValidationError

from casepilot_api.conversations import render_test_brief_markdown
from casepilot_api.schemas import TestBriefContent as BriefContent


def planning():
    return {
        "feature_points": [
            {"id": "F1", "name": "密码登录", "module": "账号", "description": "登录"}
        ],
        "test_points": [
            {
                "id": "P1",
                "title": "第三次失败锁定",
                "scenario": "连续失败",
                "feature_point_ids": ["F1"],
            }
        ],
    }


def test_brief_preserves_planning_and_renders_same_structure():
    brief = BriefContent(test_object="账号中心", planning=planning())
    payload = brief.model_dump(mode="json")
    assert payload["planning"] == planning()
    markdown = render_test_brief_markdown(1, payload)
    assert "账号 / 密码登录" in markdown
    assert "连续失败 / 第三次失败锁定（待生成）" in markdown


@pytest.mark.parametrize("corruption", ["duplicate", "foreign_feature", "empty_title"])
def test_invalid_planning_is_rejected(corruption):
    data = planning()
    if corruption == "duplicate":
        data["test_points"] *= 2
    elif corruption == "foreign_feature":
        data["test_points"][0]["feature_point_ids"] = ["another-workspace"]
    else:
        data["test_points"][0]["title"] = " "
    with pytest.raises(ValidationError):
        BriefContent(test_object="账号中心", planning=data)
