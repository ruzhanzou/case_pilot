import pytest
from casepilot_agent.contracts import GenerationRequest, RewriteRequest, RewriteCaseDraft, RewriteBatch
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers.mock import MockProvider


def planned(count):
    provider = MockProvider()
    base = provider.generate(GenerationRequest(prompt="登录"))
    point = base.test_points[0]
    plan = dict(brief_version=1,
        feature_points=[f.model_dump(mode="json") for f in base.feature_points],
        test_points=[point.model_copy(update={"id": f"P-{i}", "title": f"测试点{i}"}).model_dump(mode="json") for i in range(count)])
    return provider, GenerationRequest(prompt=f"生成{count}条用例", confirmed_plan=plan)


@pytest.mark.parametrize("count,sizes", [(12, [12]), (25, [20, 5])])
def test_generation_batches_points_and_publishes_cumulative_normalized_results(count, sizes):
    provider, request = planned(count)
    calls, previews = [], []
    def execute(stage, instruction, payload, result_type, model_id):
        calls.append(payload["batch_count"])
        batch = provider.complete(stage=stage, instruction=instruction, payload=payload,
                                  result_type=result_type, model_id=model_id)[0]
        batch.test_cases.reverse()  # Never trust response order to bind point ownership.
        return batch
    result = GenerationPipeline(provider).run(request, context={}, answers={}, execute_stage=execute,
        on_batch=lambda cases, total: previews.append(([c.id for c in cases], total)))
    assert calls == sizes
    assert [len(ids) for ids, _ in previews] == ([12] if count == 12 else [20, 25])
    assert len(set(result.test_cases[i].id for i in range(count))) == count
    assert [c.test_point_ids for c in result.test_cases] == [[f"P-{i}"] for i in range(count)]
    assert all(total == count for _, total in previews)


def test_bad_generation_point_binding_is_not_published():
    provider, request = planned(2)
    def execute(stage, instruction, payload, result_type, model_id):
        batch = provider.complete(stage=stage, instruction=instruction, payload=payload,
                                  result_type=result_type, model_id=model_id)[0]
        batch.test_cases[-1].test_point_ids = ["unknown"]
        return batch
    previews = []
    with pytest.raises(ValueError, match="测试点"):
        GenerationPipeline(provider).run(request, context={}, answers={}, execute_stage=execute,
                                         on_batch=lambda *args: previews.append(args))
    assert previews == []


class BatchProvider:
    name = "openai_compatible"
    def __init__(self, corrupt=None):
        self.calls = []
        self.corrupt = corrupt
    def complete(self, **kwargs):
        self.calls.append(kwargs)
        items = []
        for item in reversed(kwargs["payload"]["items"]):
            proposed = dict(item["test_case"])
            proposed["steps"] = [*proposed["steps"], {"action": "断网后重试", "expected": "展示可重试状态"}]
            items.append(dict(ref=item["ref"], proposed=proposed, diff=[], reason="补充验证",
                              quality={"passed": True, "score": 100}))
        if self.corrupt == "missing": items.pop()
        if self.corrupt == "duplicate": items[-1] = items[0]
        if self.corrupt == "foreign": items[-1]["ref"] = "foreign"
        if self.corrupt == "identity": items[-1]["proposed"]["id"] = "foreign"
        return RewriteBatch.model_validate({"items": items}), None


def requests(count):
    draft = MockProvider().generate(GenerationRequest(prompt="登录")).test_cases[0]
    return {f"ref-{i}": RewriteRequest(
        test_case=RewriteCaseDraft.model_validate(draft.model_copy(update={"id": f"case-{i}"}).model_dump()),
        instruction="补充断网重试验证，其他内容不变",
    ) for i in range(count)}


@pytest.mark.parametrize("count,sizes", [(3, [3]), (21, [20, 1])])
def test_semantic_rewrite_is_one_call_per_batch_and_diffs_are_server_computed(count, sizes):
    provider = BatchProvider()
    previews = []
    result = GenerationPipeline(provider).rewrite_many(requests(count), on_batch=lambda items, total: previews.append((len(items), total)))
    assert previews == [(sum(sizes[:index + 1]), count) for index in range(len(sizes))]
    assert [len(c["payload"]["items"]) for c in provider.calls] == sizes
    assert set(result) == set(requests(count))
    assert all([diff.field for diff in case.diff] == ["steps"] for case in result.values())


@pytest.mark.parametrize("corrupt", ["missing", "duplicate", "foreign", "identity"])
def test_batch_rewrite_rejects_incomplete_or_changed_identity(corrupt):
    with pytest.raises(ValueError):
        GenerationPipeline(BatchProvider(corrupt)).rewrite_many(requests(2))


def test_cancel_before_second_rewrite_batch_does_not_call_model_again():
    provider = BatchProvider()
    checks = []
    def check():
        checks.append(1)
        if len(checks) == 2:
            raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        GenerationPipeline(provider).rewrite_many(requests(21), before_batch=check)
    assert len(provider.calls) == 1
