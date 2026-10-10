from types import SimpleNamespace

import pytest
from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

from casepilot_agent.compact_generation import BatchAudit, CaseContent, ContentBatch, StageContractError, AuditStageError
from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers.mock import MockProvider


@pytest.fixture(autouse=True)
def serial_contract_tests(monkeypatch):
    # Keep retry-contract assertions deterministic; dedicated tests below turn
    # on production concurrency and force reversed completion order.
    monkeypatch.setattr("casepilot_agent.compact_generation.BATCH_CONCURRENCY", 1)


def request(count=12):
    base = MockProvider().generate(GenerationRequest(prompt="登录"))
    point = base.test_points[0]
    return GenerationRequest(prompt=f"生成{count}条用例", output_contract="case_batch_v2", confirmed_plan={
        "feature_points": [f.model_dump(mode="json") for f in base.feature_points],
        "test_points": [point.model_copy(update={"id": f"P-{i}", "title": f"登录场景{i}"}).model_dump(mode="json") for i in range(count)],
    })


def execute(stage, instruction, payload, result_type, model_id):
    if result_type is BatchAudit:
        return BatchAudit(reviews=[{"slot": c["slot"], "verdict": "supported", "replacement": None, "reason": ""} for c in payload["test_cases"]])
    return MockProvider().complete(stage=stage, instruction=instruction, payload=payload,
                                   result_type=result_type, model_id=model_id)[0]


def run(req, executor=execute, on_batch=None):
    return GenerationPipeline(SimpleNamespace(name="real")).run(req, context={}, answers={}, execute_stage=executor, on_batch=on_batch)


def test_compact_batches_audit_each_slot_and_derive_complete_coverage():
    calls, previews = [], []
    def tracked(*args):
        calls.append((args[0], args[2]["batch_count"]))
        return execute(*args)
    result = run(request(), tracked, lambda cases, total: previews.append((len(cases), total)))
    assert calls == [(stage, size) for size in [5, 5, 2] for stage in ["test_case.generated", "test_case.grounded"]]
    assert previews == [(5, 12), (10, 12), (12, 12)]
    assert len({c.id for c in result.test_cases}) == 12
    assert result.quality.passed
    assert not any(i.code == "requirement_coverage_gap" for i in result.quality.issues)
    assert all(c.source_refs and c.module for c in result.test_cases)


def test_model_cannot_emit_system_fields_or_unbounded_citations():
    with pytest.raises(ValidationError):
        CaseContent(slot=1, title="登录", preconditions=["账号有效"],
                    steps=[{"action": "登录", "expected": "建立会话"}], source_refs=[{"excerpt": "x" * 10000}])


def test_invalid_large_batch_splits_and_reuses_stage_checkpoints_on_retry():
    cache, calls, previews = {}, [], []
    def cached(stage, instruction, payload, result_type, model_id):
        key = (stage, payload["batch_start_index"], payload["batch_count"])
        if key in cache:
            return result_type.model_validate(cache[key])
        calls.append(key)
        if payload["batch_count"] > 2:
            raise ModelBehaviorError("invalid JSON")
        result = execute(stage, instruction, payload, result_type, model_id)
        cache[key] = result.model_dump(mode="json")
        return result
    first = run(request(5), cached, lambda cases, total: previews.append(len(cases)))
    assert previews == [2, 4, 5]
    calls.clear()
    second = run(request(5), cached)
    assert calls == [("test_case.generated", 1, 5)]
    assert first.model_dump() == second.model_dump()


def test_missing_audit_or_wrong_replacement_never_publishes():
    previews = []
    def broken(stage, instruction, payload, result_type, model_id):
        if result_type is BatchAudit:
            return BatchAudit(reviews=[{"slot": 999, "verdict": "supported", "replacement": None, "reason": ""}])
        return execute(stage, instruction, payload, result_type, model_id)
    with pytest.raises(AuditStageError):
        run(request(2), broken, lambda *args: previews.append(args))
    assert previews == []


def test_audit_changes_only_requested_slot():
    def corrected(stage, instruction, payload, result_type, model_id):
        result = execute(stage, instruction, payload, result_type, model_id)
        if result_type is BatchAudit:
            original = payload["test_cases"][0]
            replacement = CaseContent.model_validate(original)
            replacement.steps[0].expected = "建立有效登录会话"
            result.reviews[0].verdict = "revise"
            result.reviews[0].replacement = replacement
            result.reviews[0].reason = "删除无依据的页面跳转"
        return result
    result = run(request(2), corrected)
    assert result.test_cases[0].steps[0].expected == "建立有效登录会话"
    assert result.test_cases[1].steps[0].expected != "建立有效登录会话"


def test_worker_releases_transaction_during_model_and_honors_cancel_before_save(monkeypatch):
    from contextlib import contextmanager
    from uuid import uuid4
    from unittest.mock import MagicMock
    from casepilot_agent import tasks

    req = request(2)
    job_id = uuid4()
    job = {"id": job_id, "status": "running", "input_payload": req.model_dump(), "output_payload": {}}
    store = MagicMock()
    active = 0

    @contextmanager
    def connection():
        nonlocal active
        active += 1
        try:
            yield object()
        finally:
            active -= 1

    store.connection.side_effect = connection
    store.claim_job.return_value = job
    store.get_job_for_update.return_value = job
    store.is_cancelled.side_effect = lambda *args: job["status"] == "cancelled"
    store.load_completed_stage.return_value = None

    def complete(**kwargs):
        assert active == 0, "Model call must not hold a database transaction"
        result = MockProvider().complete(**kwargs)
        job["status"] = "cancelled"
        return result

    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: SimpleNamespace(name="mock", complete=complete))
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    result = tasks.generate_test_cases.run(str(job_id))
    assert result["status"] == "cancelled"
    store.record_stage.assert_not_called()
    store.persist_workspace_previews.assert_not_called()
    store.persist_workspace_candidates.assert_not_called()


def test_transient_connection_loss_retries_same_batch_once_without_duplicates():
    import httpx
    from openai import APIConnectionError
    calls, previews = [], []
    def unstable(stage, instruction, payload, result_type, model_id):
        if stage == "test_case.generated":
            calls.append((payload["batch_start_index"], payload["batch_count"], payload["retry_attempt"]))
            if len(calls) == 1:
                raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(request(5), unstable, lambda cases, total: previews.append(len(cases)))
    assert calls == [(1, 5, 0), (1, 5, 1)]
    assert previews == [5] and len({c.id for c in result.test_cases}) == 5


def test_persistent_connection_loss_is_bounded_and_publishes_nothing():
    import httpx
    from openai import APIConnectionError
    calls, previews = [], []
    def unavailable(stage, instruction, payload, result_type, model_id):
        calls.append(payload["batch_count"])
        raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    with pytest.raises(APIConnectionError):
        run(request(5), unavailable, lambda *args: previews.append(args))
    assert calls == [5, 5]
    assert previews == []


def test_parallel_batches_publish_fast_batch_first_with_stable_checkpoints(monkeypatch):
    from threading import Event, Lock
    monkeypatch.setattr("casepilot_agent.compact_generation.BATCH_CONCURRENCY", 2)
    second_published = Event()
    first_started = Event()
    lock = Lock()
    active = peak = 0
    inputs, previews = [], []

    def concurrent(stage, instruction, payload, result_type, model_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            inputs.append((stage, payload["batch_start_index"], payload["completed_count"]))
        try:
            if payload["batch_start_index"] == 1 and stage == "test_case.generated":
                first_started.set()
                assert second_published.wait(5), "A slow first batch must not block later previews"
            if payload["batch_start_index"] == 6 and stage == "test_case.generated":
                assert first_started.wait(5)
            return execute(stage, instruction, payload, result_type, model_id)
        finally:
            with lock:
                active -= 1

    def preview(cases, total):
        previews.append([c.id for c in cases])
        second_published.set()

    result = run(request(15), concurrent, preview)
    assert peak == 2
    assert previews[0] == [f"TC-P-{i}-1" for i in range(5, 10)]
    assert [len(p) for p in previews] == [5, 10, 15]
    assert all(len(p) == len(set(p)) for p in previews)
    assert [c.id for c in result.test_cases] == [f"TC-P-{i}-1" for i in range(15)]
    assert all(completed == start - 1 for _, start, completed in inputs)


def test_parallel_fatal_error_stops_new_batches_and_joins_inflight(monkeypatch):
    from threading import Barrier, Event, Timer
    monkeypatch.setattr("casepilot_agent.compact_generation.BATCH_CONCURRENCY", 2)
    started = Barrier(2)
    finished = Event()
    calls = []
    def fail(stage, instruction, payload, result_type, model_id):
        calls.append(payload["batch_start_index"])
        if stage == "test_case.generated":
            started.wait(timeout=5)
            if payload["batch_start_index"] == 1:
                raise RuntimeError("fatal")
            timer = Timer(0.05, finished.set)
            timer.start()
            assert finished.wait(5)
            timer.join()
        return execute(stage, instruction, payload, result_type, model_id)
    with pytest.raises(RuntimeError, match="fatal"):
        run(request(20), fail)
    assert finished.is_set()
    assert set(calls) <= {1, 6}


def test_case_checkpoints_are_not_required_for_every_action():
    from casepilot_agent.contracts import TestStep
    def independent(stage, instruction, payload, result_type, model_id):
        result = execute(stage, instruction, payload, result_type, model_id)
        if result_type is ContentBatch:
            for case in result.test_cases:
                case.steps = [TestStep(action='Open login', expected='Session is established'), TestStep(action='Submit credentials', expected='')]
        return result
    result = run(request(1), independent)
    assert result.quality.passed
    assert result.test_cases[0].steps[1].expected == ''


def test_count_does_not_recycle_confirmed_points():
    req = request(2)
    req.prompt = "大概生成50条用例"
    result = GenerationPipeline(MockProvider()).run(req, context={}, answers={}, execute_stage=execute)
    assert len(result.test_cases) == 2
    assert any(i.code == "independent_scenarios_below_target" for i in result.quality.issues)


def test_duplicate_content_is_rejected_even_when_titles_differ():
    from casepilot_agent.pipeline import validate_generation
    base = MockProvider().generate(GenerationRequest(prompt="登录"))
    first = base.test_cases[0]
    base.test_cases = [first, first.model_copy(update={"id": "other", "title": "同义改写", "module": "另一个模块"})]
    assert any(i.code == "duplicate_case_content" for i in validate_generation(base).issues)


def test_cross_batch_duplicate_merge_retains_both_point_links():
    from casepilot_agent.compact_generation import DuplicateResolution, reconcile_duplicates
    req = request(2)
    base = MockProvider().generate(GenerationRequest(prompt="登录"))
    first = base.test_cases[0]
    first.test_point_ids = ["one"]
    duplicate = first.model_copy(deep=True, update={"id": "duplicate", "test_point_ids": ["two"]})
    base.test_cases = [first, duplicate]
    calls = []
    def resolve(stage, instruction, payload, result_type, model):
        calls.append(payload)
        return DuplicateResolution(equivalent=True, reason="同一场景", replacement=CaseContent(
            slot=1, title=first.title, preconditions=first.preconditions, steps=first.steps))
    assert reconcile_duplicates(base, req, resolve) == 1
    assert len(base.test_cases) == len(calls) == 1
    assert base.test_cases[0].test_point_ids == ["one", "two"]


def test_same_title_distinct_scenarios_are_repaired_not_dropped():
    from casepilot_agent.compact_generation import DuplicateResolution, reconcile_duplicates
    from casepilot_agent.contracts import TestStep
    from casepilot_agent.pipeline import validate_generation
    req = request(2)
    base = MockProvider().generate(GenerationRequest(prompt="登录"))
    first = base.test_cases[0]
    second = first.model_copy(deep=True, update={"id": "second", "preconditions": ["二维码已过期"]})
    base.test_cases = [first, second]
    def resolve(*args):
        return DuplicateResolution(equivalent=False, reason="不同前置状态与结果", replacement=CaseContent(
            slot=1, title="过期二维码无法登录", preconditions=second.preconditions,
            steps=[TestStep(action="扫描过期码", expected="不建立登录会话")]))
    assert reconcile_duplicates(base, req, resolve) == 0
    assert len(base.test_cases) == 2
    assert not any(i.code.startswith('duplicate_case') for i in validate_generation(base).issues)


def test_audit_retry_reuses_generation_and_never_republishes():
    calls, previews = [], []
    def unstable(stage, instruction, payload, result_type, model):
        calls.append(stage)
        if stage == "test_case.grounded" and payload["audit_attempt"] == 0:
            raise ModelBehaviorError("malformed audit")
        return execute(stage, instruction, payload, result_type, model)
    result = run(request(5), unstable, lambda cases, total: previews.append(len(cases)))
    assert result.quality.passed
    assert calls == ["test_case.generated", "test_case.grounded", "test_case.grounded"]
    assert previews == [5]


def test_compact_payload_shares_features_and_preserves_evidence():
    inputs = []
    def capture(stage, instruction, payload, result_type, model):
        inputs.append(payload)
        return execute(stage, instruction, payload, result_type, model)
    assert run(request(5), capture).quality.passed
    assert inputs[0]["features"]
    assert all("features" not in point for point in inputs[0]["points"])
    assert "confirmed_brief" in inputs[0] and "evidence" in inputs[0]


def test_failed_audit_does_not_leak_partial_replacements_into_retry():
    inputs = []

    def audit(stage, instruction, payload, result_type, model_id):
        result = execute(stage, instruction, payload, result_type, model_id)
        if result_type is BatchAudit:
            inputs.append(payload["test_cases"])
            if len(inputs) == 1:
                replacement = CaseContent.model_validate(payload["test_cases"][0])
                replacement.title = "不应保留的未通过审核修改"
                result.reviews[0].verdict = "revise"
                result.reviews[0].replacement = replacement
                result.reviews[0].reason = "修订"
                result.reviews[1].verdict = "revise"
                # Invalid later review rejects the entire audit attempt.
                result.reviews[1].replacement = None
        return result

    result = run(request(2), audit)
    assert len(inputs) == 2
    assert inputs[0] == inputs[1]
    assert result.test_cases[0].title == inputs[0][0]["title"]
