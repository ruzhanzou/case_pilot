from copy import deepcopy

import pytest

from casepilot_agent.contracts import RewriteCaseDraft, RewriteRequest, UsageMetadata
from casepilot_agent.pipeline import GenerationPipeline, rebase_rewrite_candidate


def original():
    return RewriteCaseDraft.model_validate(
        {
            "id": "login",
            "title": "登录",
            "module": "登录",
            "priority": "P1",
            "case_type": "功能",
            "tags": ["回归"],
            "status": "pending",
            "automated": False,
            "test_point_ids": ["TP-login"],
            "preconditions": ["账号存在", "网络可用"],
            "source_refs": [],
            "steps": [{"action": f"原操作{i}", "expected": f"原校验点{i}"} for i in range(3)],
        }
    )


class Provider:
    name = "openai_compatible"

    def __init__(self, changes, repaired=None):
        self.changes = changes
        self.repaired = repaired
        self.calls = []

    def complete(self, *, payload, result_type, **kwargs):
        self.calls.append(deepcopy(payload))
        changes = (
            self.repaired
            if payload.get("validation_feedback") and self.repaired is not None
            else self.changes
        )
        return result_type.model_validate(
            {
                "items": [
                    {"ref": item["ref"], "changes": changes, "reason": "测试改写"}
                    for item in payload["items"]
                ]
            }
        ), UsageMetadata(model="test")


@pytest.mark.parametrize("count", [1, 3])
def test_addition_never_drops_previous_steps_even_when_model_returns_only_delta(count):
    provider = Provider({"steps": [{"action": "断网重试", "expected": "恢复会话"}]})
    requests = {
        str(i): RewriteRequest(test_case=original(), instruction="补充断网重试验证，其他内容不变")
        for i in range(count)
    }
    results = GenerationPipeline(provider).rewrite_many(requests)
    assert len(results) == count
    assert len(provider.calls) == 2
    for ref, result in results.items():
        assert not result.quality.passed
        assert result.proposed == requests[ref].test_case
        assert result.diff == []


def test_invalid_delta_repairs_to_append_without_losing_old_content():
    addition = [{"action": "断网重试", "expected": "恢复会话"}]
    provider = Provider({"steps": addition}, {"append_steps": addition})
    result = GenerationPipeline(provider).rewrite_many(
        {"one": RewriteRequest(test_case=original(), instruction="补充断网重试验证")}
    )["one"]
    assert result.quality.passed
    assert result.proposed.steps[:3] == original().steps
    assert len(result.proposed.steps) == 4
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    "instruction",
    [
        "拆分操作步骤，预期结果保持不变",
        "保留预期结果，整理操作步骤",
        "修改标题，校验点不变",
        "预期不改，优化步骤",
    ],
)
def test_protected_expected_is_repaired_or_falls_back(instruction):
    provider = Provider({"expected_updates": [{"step_index": 0, "expected": "错误覆盖"}]})
    result = GenerationPipeline(provider).rewrite_many(
        {"one": RewriteRequest(test_case=original(), instruction=instruction)}
    )["one"]
    assert not result.quality.passed
    assert result.proposed == original()


def test_three_rounds_accumulate_append_then_targeted_edit_then_append():
    base = original()
    working = base
    rounds = [
        ("补充断网重试验证", {"append_steps": [{"action": "重试", "expected": "恢复会话"}]}),
        (
            "修改第2步操作为输入验证码，预期结果保持不变",
            {"step_updates": [{"step_index": 1, "action": "输入验证码"}]},
        ),
        ("增加注销验证", {"append_steps": [{"action": "注销", "expected": "会话失效"}]}),
    ]
    for instruction, changes in rounds:
        result = GenerationPipeline(Provider(changes)).rewrite_many(
            {"one": RewriteRequest(test_case=working, instruction=instruction)}
        )["one"]
        assert result.quality.passed
        working = result.proposed
    assert len(working.steps) == 5
    assert working.steps[1].action == "输入验证码"
    assert [s.expected for s in working.steps[:3]] == [s.expected for s in base.steps]
    assert working.steps[3].action == "重试"
    assert working.steps[4].action == "注销"
    assert rebase_rewrite_candidate(base, result).diff[0].before == base.model_dump()["steps"]
    assert len(base.steps) == 3


def test_explicit_step_deletion_is_allowed_but_negation_is_not():
    changes = {"steps": [original().steps[0].model_dump()]}
    for instruction, passed in [("删除第2和第3步", True), ("不要删除旧步骤，整理表述", False)]:
        result = GenerationPipeline(Provider(changes)).rewrite_many(
            {"one": RewriteRequest(test_case=original(), instruction=instruction)}
        )["one"]
        assert result.quality.passed is passed


def test_step_delta_keeps_unspecified_action_and_expected_and_rejects_duplicate_indexes():
    changes = {"step_updates": [{"step_index": 1, "action": "明确操作"}]}
    result = GenerationPipeline(Provider(changes)).rewrite_many(
        {"one": RewriteRequest(test_case=original(), instruction="修改第2步操作")}
    )["one"]
    assert result.proposed.steps[1].expected == original().steps[1].expected
    assert result.proposed.steps[0] == original().steps[0]
    changes["expected_updates"] = [{"step_index": 1, "expected": "冲突修改"}]
    result = GenerationPipeline(Provider(changes)).rewrite_many(
        {"one": RewriteRequest(test_case=original(), instruction="修改第2步操作")}
    )["one"]
    assert not result.quality.passed
    assert result.proposed == original()


def test_failed_followup_preserves_previous_reviewable_diff():
    from casepilot_agent.tasks import _rewrite_review_payload

    base = original()
    first = GenerationPipeline(
        Provider(
            {
                "append_steps": [
                    {"action": "第一轮追加", "expected": "第一轮校验"},
                ]
            }
        )
    ).rewrite_many({"one": RewriteRequest(test_case=base, instruction="补充校验")})["one"]
    previous = {
        "status": "ready",
        "proposed_snapshot": first.proposed.model_dump(mode="json"),
        "field_diff": [d.model_dump() for d in first.diff],
    }
    second = GenerationPipeline(
        Provider(
            {
                "steps": [
                    {"action": "丢失旧步骤", "expected": "错误结果"},
                ]
            }
        )
    ).rewrite_many({"one": RewriteRequest(test_case=first.proposed, instruction="增加第二轮校验")})[
        "one"
    ]
    reviewed = _rewrite_review_payload(base, second, previous)
    assert not reviewed["quality"]["passed"]
    assert reviewed["proposed"] == first.proposed.model_dump(mode="json")
    assert reviewed["diff"] == [d.model_dump(mode="json") for d in first.diff]
    assert "保留上一轮" in reviewed["reason"]


def test_preserve_existing_steps_still_allows_explicit_append():
    result = GenerationPipeline(
        Provider(
            {
                "append_steps": [
                    {"action": "新增操作", "expected": "新增校验"},
                ]
            }
        )
    ).rewrite_many(
        {
            "one": RewriteRequest(
                test_case=original(),
                instruction="保留原有操作步骤和预期结果，补充一个新步骤，不要修改其他内容",
            )
        }
    )["one"]
    assert result.quality.passed
    assert result.proposed.steps[:3] == original().steps
    assert len(result.proposed.steps) == 4


def test_model_cannot_drop_confirmed_asset_provenance_when_reselecting_citations():
    from casepilot_agent.contracts import SourceRef
    import json
    case = original()
    source = SourceRef(label='修改参考 · 旧版用例.xlsx', locator='Sheet1 行2',
                       excerpt=json.dumps({'source_key': 'excel:doc:Sheet1:2', 'action': 'modify',
                                           'case_key': 'OLD-001', 'revision': 1}))
    case.source_refs.append(source)
    result = GenerationPipeline(Provider({'title': '登录成功校验', 'source_ref_indexes': []})).rewrite_many(
        {'one': RewriteRequest(test_case=case, instruction='只将标题改为登录成功校验')})['one']
    assert result.quality.passed
    assert source in result.proposed.source_refs


def reference_request():
    return RewriteRequest(
        test_case=original(), instruction="参考Excel只改写操作步骤，预期结果保持不变",
        context={
            "approved_reference_assets": [{"key": "excel:book:2", "kind": "excel"}],
            "evidence": [{"label": "历史.xlsx", "excerpt": "记录签发时刻"}],
            "confirmed_reference_refs": [{
                "label": "修改参考 · 历史.xlsx",
                "excerpt": '{"source_key":"excel:book:2","action":"modify"}',
            }],
        },
    )


@pytest.mark.parametrize("changes", [{}, {"source_ref_indexes": [0]}, {"title": "换个标题"}, {
    "step_updates": [{"step_index": 0, "action": " 原操作0 "}],
}])
def test_reference_step_rewrite_retries_then_retains_original_without_false_provenance(changes):
    request = reference_request()
    provider = Provider(changes)
    result = GenerationPipeline(provider).rewrite_many({"one": request})["one"]
    assert len(provider.calls) == 2
    assert "未改变操作步骤" in provider.calls[1]["validation_feedback"]["one"]
    assert not result.quality.passed
    assert result.proposed == request.test_case
    assert result.diff == []
    assert not result.proposed.source_refs


def test_reference_retry_changes_actions_preserves_expected_and_point_links():
    request = reference_request()
    provider = Provider({}, {"step_updates": [
        {"step_index": 0, "action": "记录签发时刻并推进服务端时钟至300秒"}]})
    result = GenerationPipeline(provider).rewrite_many({"one": request})["one"]
    assert result.quality.passed
    assert result.quality.repair_rounds == 1
    assert result.proposed.steps[0].action != request.test_case.steps[0].action
    assert [s.expected for s in result.proposed.steps] == [
        s.expected for s in request.test_case.steps]
    assert result.proposed.steps[1:] == request.test_case.steps[1:]
    assert result.proposed.test_point_ids == request.test_case.test_point_ids
    assert result.proposed.source_refs[0].label == "修改参考 · 历史.xlsx"
    assert {d.field for d in result.diff} == {"steps", "source_refs"}
    assert not request.test_case.source_refs


def test_reference_title_rewrite_does_not_require_step_changes():
    request = reference_request().model_copy(update={
        "instruction": "参考Excel优化标题，步骤保持不变"})
    result = GenerationPipeline(Provider({"title": "验证码过期校验"})).rewrite_many(
        {"one": request})["one"]
    assert result.quality.passed
    assert result.proposed.steps == request.test_case.steps


def test_ordinary_review_may_legitimately_have_no_changes():
    request = RewriteRequest(test_case=original(), instruction="核对用例内容，正确的保持不变")
    result = GenerationPipeline(Provider({})).rewrite_many({"one": request})["one"]
    assert result.quality.passed
    assert result.diff == []


def test_reference_rewrite_repairs_full_source_row_to_local_step_update():
    request = reference_request()
    provider = Provider(
        {"steps": [{"action": "参考表合并为一个操作", "expected": "原校验点2"}]},
        {"step_updates": [{"step_index": 0, "action": "记录签发时刻，供推进时钟使用"}]},
    )
    result = GenerationPipeline(provider).rewrite_many({"one": request})["one"]
    assert result.quality.passed
    assert result.quality.repair_rounds == 1
    assert len(result.proposed.steps) == len(request.test_case.steps)
    assert [s.expected for s in result.proposed.steps] == [
        s.expected for s in request.test_case.steps]
    assert result.proposed.test_point_ids == request.test_case.test_point_ids
