"""Rendered model planning is context, never independent original evidence."""
import pytest
from casepilot_agent.compact_generation import requirement_source_texts
from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.tasks import generation_markdown_origin

from casepilot_api.conversations import render_test_brief_markdown


def test_actual_brief_renderer_cannot_launder_a_model_scenario_into_source_evidence():
    content = {"test_object": "输入校验", "business_rules": ["非法格式返回错误"],
               "planning": {"feature_points": [{"id": "f", "module": "输入", "name": "格式"}],
                   "test_points": [{"id": "p", "feature_point_ids": ["f"],
                                    "title": "非法格式", "scenario": "模型推断的未核环境"}]}}
    rendered = render_test_brief_markdown(1, content)
    assert "模型推断的未核环境" in rendered
    payload = {"confirmed_test_brief": content, "confirmed_plan": content["planning"],
               "markdown_content": rendered}
    request = GenerationRequest(prompt="按原规范生成", markdown_content=rendered,
                                markdown_origin=generation_markdown_origin(payload))
    assert requirement_source_texts(request, [], []) == ["按原规范生成"]
    assert request.markdown_content == rendered  # Context is retained, not erased.


@pytest.mark.parametrize("payload,expected", [
    ({"markdown_content": "外部原文"}, "provided"),
    ({"confirmed_plan": {"test_points": []}}, "unknown"),
    ({"confirmed_test_brief": {}, "confirmed_plan": {}}, "derived_brief"),
])
def test_job_origin_uses_server_structure_not_claims_in_markdown(payload, expected):
    assert generation_markdown_origin(payload) == expected


def test_user_original_material_and_explicit_instruction_remain_available():
    request = GenerationRequest(prompt="用户明确前提", markdown_content="原文条件")
    assert requirement_source_texts(request, [{"role": "assistant", "content": "模型推断"},
        {"role": "user", "content": "用户后续要求"}], []) == [
            "原文条件", "用户明确前提", "用户后续要求"]


def test_only_actual_user_edits_become_sources_and_model_revisions_cannot_erase_them():
    from casepilot_api.brief_user_sources import KEY, capture_user_edits, resolve_user_sources

    original = {"test_object": "输入", "test_objective": "模型目标",
                "business_rules": ["模型推断条件"]}
    saved = {**original, "business_rules": ["模型推断条件", "用户明确条件"]}
    saved[KEY] = capture_user_edits(original, saved, 2)
    model_revision = {**original, "business_rules": ["另一个模型条件"]}
    records = [(1, original), (2, saved), (3, model_revision)]
    assert [s["text"] for s in resolve_user_sources(records, model_revision)] == ["用户明确条件"]
    assert capture_user_edits(original, {**original, KEY: {"forged": True}}, 2) == {}


def test_user_removal_is_a_tombstone_and_copied_metadata_does_not_create_new_authority():
    from casepilot_api.brief_user_sources import KEY, capture_user_edits, resolve_user_sources

    original = {"test_object": "输入", "business_rules": []}
    added = {**original, "business_rules": ["用户条件"]}
    added[KEY] = capture_user_edits(original, added, 2)
    removed = {**original, KEY: capture_user_edits(added, original, 3)}
    restored_by_model = {**added}
    assert resolve_user_sources([(2, added), (3, removed), (4, restored_by_model)],
                                restored_by_model) == []
    assert resolve_user_sources([(4, added)], added) == []
    assert resolve_user_sources([(2, added)], {**added, "test_object": "其他对象"}) == []


def test_list_reordering_does_not_promote_unchanged_model_fields():
    from casepilot_api.brief_user_sources import capture_user_edits

    original = {"test_object": "输入", "business_rules": ["模型甲", "模型乙"]}
    reordered = {**original, "business_rules": ["模型乙", "模型甲"]}
    assert capture_user_edits(original, reordered, 2) == {}


def test_user_point_evidence_is_limited_to_selected_batch():
    request = GenerationRequest(prompt="模型目标", prompt_origin="unknown", explicit_user_sources=[
        {"text": "第一点用户要求", "point_id": "p1", "source_version": 2},
        {"text": "第二点用户要求", "point_id": "p2", "source_version": 2},
        {"text": "通用用户要求", "source_version": 2},
    ])
    assert requirement_source_texts(request, [], [], point_ids={"p1"}, feature_ids=set()) == [
        "第一点用户要求", "通用用户要求"]


@pytest.mark.asyncio
async def test_real_api_user_save_confirm_preserves_only_changed_user_sources():
    from copy import deepcopy
    from uuid import UUID

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select
    from test_planning_review_lifecycle import PLAN
    from test_workbench_bridge_integration import setup

    from casepilot_api.brief_user_sources import KEY
    from casepilot_api.database import get_session_factory
    from casepilot_api.main import app
    from casepilot_api.models import GenerationJob, WorkspaceTestBrief

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        original = {"test_object": "Synthetic", "test_objective": "模型目标",
                    "business_rules": ["模型推断条件"], "planning": deepcopy(PLAN)}
        # Existing model-produced draft fixture: no user-origin edit markers.
        with get_session_factory()() as db:
            db.add(WorkspaceTestBrief(conversation_id=UUID(workspace["id"]), version=1,
                                      content=original, status="draft"))
            db.commit()
        edited = {**original, "business_rules": ["模型推断条件", "用户明确条件"],
                  KEY: {"forged": True}}
        url = f"/api/v1/workspaces/{workspace['id']}/test-briefs"
        saved = await client.post(url, json={"base_version": 1, "content": edited})
        assert saved.status_code == 201, saved.text
        assert KEY not in saved.json()["content"]
        confirmed = await client.post(url + "/confirm", json={"version": 2})
        assert confirmed.status_code == 202, confirmed.text
        with get_session_factory()() as db:
            job = db.scalar(select(GenerationJob).where(
                GenerationJob.input_payload["conversation_id"].astext == workspace["id"]))
            payload = job.input_payload
            assert payload["prompt_origin"] == "unknown"
            assert [item["text"] for item in payload["explicit_user_sources"]] == ["用户明确条件"]
            request = GenerationRequest(prompt=payload["prompt"],
                prompt_origin=payload["prompt_origin"],
                markdown_content=payload["markdown_content"],
                markdown_origin=generation_markdown_origin(payload),
                explicit_user_sources=payload["explicit_user_sources"])
            assert requirement_source_texts(request, [], []) == ["用户明确条件"]
