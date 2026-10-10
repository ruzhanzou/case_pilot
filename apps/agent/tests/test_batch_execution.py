import pytest
from casepilot_agent.contracts import (
    GenerationRequest,
    RewriteRequest,
    RewriteCaseDraft,
    RewritePatchBatch,
)
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers.mock import MockProvider


def planned(count):
    provider = MockProvider()
    base = provider.generate(GenerationRequest(prompt="登录"))
    point = base.test_points[0]
    plan = dict(
        brief_version=1,
        feature_points=[f.model_dump(mode="json") for f in base.feature_points],
        test_points=[
            point.model_copy(update={"id": f"P-{i}", "title": f"测试点{i}"}).model_dump(mode="json")
            for i in range(count)
        ],
    )
    return provider, GenerationRequest(prompt=f"生成{count}条用例", confirmed_plan=plan)


@pytest.mark.parametrize("count,sizes", [(12, [12]), (25, [20, 5])])
def test_generation_batches_points_and_publishes_cumulative_normalized_results(count, sizes):
    provider, request = planned(count)
    calls, previews = [], []

    def execute(stage, instruction, payload, result_type, model_id):
        calls.append(payload["batch_count"])
        batch = provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]
        batch.test_cases.reverse()  # Never trust response order to bind point ownership.
        return batch

    result = GenerationPipeline(provider).run(
        request,
        context={},
        answers={},
        execute_stage=execute,
        on_batch=lambda cases, total: previews.append(([c.id for c in cases], total)),
    )
    assert calls == sizes
    assert [len(ids) for ids, _ in previews] == ([12] if count == 12 else [20, 25])
    assert len(set(result.test_cases[i].id for i in range(count))) == count
    assert [c.test_point_ids for c in result.test_cases] == [[f"P-{i}"] for i in range(count)]
    assert all(total == count for _, total in previews)


def test_bad_generation_point_binding_is_not_published():
    provider, request = planned(2)

    def execute(stage, instruction, payload, result_type, model_id):
        batch = provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]
        batch.test_cases[-1].test_point_ids = ["unknown"]
        return batch

    previews = []
    with pytest.raises(ValueError, match="测试点"):
        GenerationPipeline(provider).run(
            request,
            context={},
            answers={},
            execute_stage=execute,
            on_batch=lambda *args: previews.append(args),
        )
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
            proposed["steps"] = [
                *proposed["steps"],
                {"action": "断网后重试", "expected": "展示可重试状态"},
            ]
            items.append(
                dict(
                    ref=item["ref"],
                    changes={"steps": proposed["steps"]},
                    reason="补充验证",
                    quality={"passed": True, "score": 100},
                )
            )
        if self.corrupt == "missing":
            items.pop()
        if self.corrupt == "duplicate":
            items[-1] = items[0]
        if self.corrupt == "foreign":
            items[-1]["ref"] = "foreign"
        if self.corrupt == "identity":
            items[-1]["changes"]["id"] = "foreign"
        if self.corrupt == "invalid_priority":
            items[-1]["changes"]["priority"] = "P99"
        if self.corrupt == "empty_steps":
            items[-1]["changes"]["steps"] = []
        return RewritePatchBatch.model_validate({"items": items}), None


def requests(count):
    draft = MockProvider().generate(GenerationRequest(prompt="登录")).test_cases[0]
    return {
        f"ref-{i}": RewriteRequest(
            test_case=RewriteCaseDraft.model_validate(
                draft.model_copy(update={"id": f"case-{i}"}).model_dump()
            ),
            instruction="补充断网重试验证，其他内容不变",
        )
        for i in range(count)
    }


@pytest.mark.parametrize("count,sizes", [(3, [3]), (21, [20, 1])])
def test_semantic_rewrite_is_one_call_per_batch_and_diffs_are_server_computed(count, sizes):
    provider = BatchProvider()
    previews = []
    result = GenerationPipeline(provider).rewrite_many(
        requests(count), on_batch=lambda items, total: previews.append((len(items), total))
    )
    assert previews == [(sum(sizes[: index + 1]), count) for index in range(len(sizes))]
    assert [len(c["payload"]["items"]) for c in provider.calls] == sizes
    assert set(result) == set(requests(count))
    assert all([diff.field for diff in case.diff] == ["steps"] for case in result.values())


@pytest.mark.parametrize("corrupt", ["missing", "duplicate", "foreign", "identity", "invalid_priority", "empty_steps"])
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


def test_real_generation_audits_original_sources_before_publishing():
    provider, request = planned(2)
    request.conversation_memory = [{"role": "user", "content": "登录成功建立会话，不规定页面跳转"}]

    class RealProvider:
        name = "openai_compatible"

    stages, previews = [], []

    def execute(stage, instruction, payload, result_type, model_id):
        stages.append(stage)
        if stage == "test_case.grounded":
            assert payload["user_requirements"] == request.conversation_memory
            batch = result_type.model_validate({"test_cases": payload["test_cases"]})
            for case in batch.test_cases:
                case.steps[0].expected = "建立会话"
            return batch
        result = provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]
        for case in result.test_cases:
            case.steps[0].expected = "建立会话并跳转首页"
        return result

    result = GenerationPipeline(RealProvider()).run(
        request,
        context={},
        answers={},
        execute_stage=execute,
        on_batch=lambda cases, total: previews.extend(case.steps[0].expected for case in cases),
    )
    assert stages == ["test_case.generated", "test_case.grounded"]
    assert previews == ["建立会话", "建立会话"]
    assert len(result.test_cases) == 2


def test_grounding_cannot_silently_drop_cases_or_publish_partial_batch():
    provider, request = planned(2)

    class RealProvider:
        name = "openai_compatible"

    previews = []

    def execute(stage, instruction, payload, result_type, model_id):
        if stage == "test_case.grounded":
            return result_type.model_validate({"test_cases": payload["test_cases"][:1]})
        return provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]

    with pytest.raises(ValueError, match="身份或数量"):
        GenerationPipeline(RealProvider()).run(
            request,
            context={},
            answers={},
            execute_stage=execute,
            on_batch=lambda *args: previews.append(args),
        )
    assert previews == []


def test_malformed_later_batch_splits_without_repeating_completed_points():
    from agents.exceptions import ModelBehaviorError

    provider, request = planned(45)
    calls, previews = [], []

    def execute(stage, instruction, payload, result_type, model_id):
        start, size = payload["batch_start_index"], payload["batch_count"]
        calls.append((start, size))
        if start == 21 and size == 20:
            raise ModelBehaviorError("invalid JSON")
        return provider.complete(stage=stage, instruction=instruction, payload=payload,
                                 result_type=result_type, model_id=model_id)[0]

    result = GenerationPipeline(provider).run(
        request, context={}, answers={}, execute_stage=execute,
        on_batch=lambda cases, total: previews.append(len(cases)),
    )
    assert calls == [(1, 20), (21, 20), (21, 5), (26, 5), (31, 5), (36, 5), (41, 5)]
    assert previews == [20, 25, 30, 35, 40, 45]
    assert [c.test_point_ids for c in result.test_cases] == [[f"P-{i}"] for i in range(45)]
    assert len({c.id for c in result.test_cases}) == 45


def test_malformed_small_batch_stops_with_no_partial_preview():
    from agents.exceptions import ModelBehaviorError

    provider, request = planned(10)
    calls, previews = [], []

    def execute(stage, instruction, payload, result_type, model_id):
        calls.append(payload["batch_count"])
        raise ModelBehaviorError("invalid JSON")

    with pytest.raises(ModelBehaviorError):
        GenerationPipeline(provider).run(
            request, context={}, answers={}, execute_stage=execute,
            on_batch=lambda *args: previews.append(args),
        )
    assert calls == [10, 5]
    assert previews == []


def test_malformed_audit_splits_and_only_publishes_audited_batches():
    from agents.exceptions import ModelBehaviorError

    provider, request = planned(10)
    class RealProvider:
        name = "openai_compatible"

    pipeline = GenerationPipeline(RealProvider())
    calls, previews = [], []

    def execute(stage, instruction, payload, result_type, model_id):
        size = payload["batch_count"]
        calls.append((stage, size))
        if stage == "test_case.grounded":
            if size > 5:
                raise ModelBehaviorError("invalid JSON")
            return result_type.model_validate({"test_cases": payload["test_cases"]})
        return provider.complete(stage=stage, instruction=instruction, payload=payload,
                                 result_type=result_type, model_id=model_id)[0]

    result = pipeline.run(
        request, context={}, answers={}, execute_stage=execute,
        on_batch=lambda cases, total: previews.append(len(cases)),
    )
    assert calls == [(stage, size) for size in [10, 5, 5]
                     for stage in ["test_case.generated", "test_case.grounded"]]
    assert previews == [5, 10]
    assert len({c.id for c in result.test_cases}) == 10


def test_patch_rewrite_preserves_untouched_fields_and_does_not_request_full_output():
    provider = BatchProvider()
    source = requests(1)
    result = GenerationPipeline(provider).rewrite_many(source)
    before = source["ref-0"].test_case.model_dump()
    after = result["ref-0"].proposed.model_dump()
    assert {k: v for k, v in before.items() if k != "steps"} == {
        k: v for k, v in after.items() if k != "steps"
    }
    schema = provider.calls[0]["result_type"].model_json_schema()
    fields = schema["$defs"]["RewritePatchItem"]["properties"]
    assert "changes" in fields
    assert "proposed" not in fields and "diff" not in fields


def test_malformed_rewrite_splits_only_failed_batch_and_publishes_progress():
    from agents.exceptions import ModelBehaviorError

    class TruncatedProvider(BatchProvider):
        def complete(self, **kwargs):
            if len(kwargs["payload"]["items"]) > 2:
                self.calls.append(kwargs)
                raise ModelBehaviorError("truncated output")
            return super().complete(**kwargs)

    provider = TruncatedProvider()
    previews = []
    result = GenerationPipeline(provider).rewrite_many(
        requests(5), on_batch=lambda items, total: previews.append((list(items), total))
    )
    assert [len(call["payload"]["items"]) for call in provider.calls] == [5, 2, 3, 1, 2]
    assert [len(items) for items, _ in previews] == [2, 3, 5]
    assert set(result) == set(requests(5))
    assert all(total == 5 for _, total in previews)


def test_persistent_malformed_single_rewrite_has_bounded_retry():
    from agents.exceptions import ModelBehaviorError

    class BrokenProvider(BatchProvider):
        def complete(self, **kwargs):
            self.calls.append(kwargs)
            raise ModelBehaviorError("malformed output")

    provider = BrokenProvider()
    previews = []
    with pytest.raises(ModelBehaviorError):
        GenerationPipeline(provider).rewrite_many(
            requests(1), on_batch=lambda *args: previews.append(args)
        )
    assert len(provider.calls) == 2
    assert previews == []


def test_cancel_during_rewrite_recovery_stops_before_next_call():
    from agents.exceptions import ModelBehaviorError

    provider = BatchProvider()
    def broken(**kwargs):
        provider.calls.append(kwargs)
        raise ModelBehaviorError("truncated")
    provider.complete = broken
    checks = []
    def check():
        checks.append(True)
        if len(checks) == 2:
            raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        GenerationPipeline(provider).rewrite_many(requests(5), before_batch=check)
    assert len(provider.calls) == 1


def test_explicit_rewrites_publish_before_semantic_model_call():
    source = requests(2)
    source["ref-0"] = source["ref-0"].model_copy(update={"instruction": "优先级改为P0"})
    previews = []

    class PreviewProvider(BatchProvider):
        def complete(self, **kwargs):
            assert previews == [(1, 2)]
            return super().complete(**kwargs)

    provider = PreviewProvider()
    result = GenerationPipeline(provider).rewrite_many(
        source, on_batch=lambda items, total: previews.append((len(items), total))
    )
    assert previews == [(1, 2), (2, 2)]
    assert result["ref-0"].proposed.priority == "P0"
    assert len(provider.calls) == 1
