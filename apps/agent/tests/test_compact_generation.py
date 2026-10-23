from types import SimpleNamespace

import pytest
from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

from casepilot_agent.compact_generation import BatchAudit, CaseContent, ContentBatch, ReviewContentBatch
from casepilot_agent.contracts import GenerationRequest, TestStep as CaseStep
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
        return BatchAudit(reviews=[{"slot": c["slot"], "verdict": "supported", "replacement": None, "reason": "", "assertions": [{"step": i + 1, "source_index": 0, "quote": payload["grounding_sources"][0], "explanation": "测试审核桩"} for i, step in enumerate(c["steps"]) if step["expected"].strip()]} for c in payload["test_cases"]])
    return MockProvider().complete(stage=stage, instruction=instruction, payload=payload,
                                   result_type=result_type, model_id=model_id)[0]


def run(req, executor=execute, on_batch=None):
    return GenerationPipeline(SimpleNamespace(name="real")).run(req, context={}, answers={}, execute_stage=executor, on_batch=on_batch)


def test_compact_batches_use_local_checks_and_derive_complete_coverage():
    calls, previews = [], []
    def tracked(*args):
        calls.append((args[0], args[2]["batch_count"]))
        return execute(*args)
    result = run(request(), tracked, lambda cases, total: previews.append((len(cases), total)))
    assert calls == [("test_case.generated", size) for size in [5, 5, 2]]
    assert result.quality.grounding_status == "unverified"
    assert previews == [(5, 12), (10, 12), (12, 12)]
    assert len({c.id for c in result.test_cases}) == 12
    assert result.quality.passed
    assert not any(i.code == "requirement_coverage_gap" for i in result.quality.issues)
    assert all(c.source_refs and c.module for c in result.test_cases)


def test_model_cannot_emit_system_fields_or_unbounded_citations():
    with pytest.raises(ValidationError):
        CaseContent(slot=1, title="登录", preconditions=["账号有效"],
                    steps=[{"action": "登录", "expected": "建立会话"}], source_refs=[{"excerpt": "x" * 10000}])


def test_invalid_json_retries_are_bounded_after_fresh_batches_without_recursive_split():
    calls, previews = [], []
    def malformed(stage, instruction, payload, result_type, model_id):
        calls.append((payload["batch_start_index"], payload["batch_count"], payload["retry_attempt"]))
        if payload["batch_start_index"] == 1:
            raise ModelBehaviorError("invalid JSON")
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(request(10), malformed, lambda cases, total: previews.append(len(cases)))
    assert calls == [(1, 5, 0), (6, 5, 0), (1, 5, 1), (1, 5, 2)]
    assert previews == [5]
    assert result.quality.passed
    missing = [i for i in result.quality.issues if i.code == "uncovered_test_point"]
    assert len(missing) == 5 and all("待完善" in i.message for i in missing)


def test_missing_and_malformed_slots_repair_only_failed_entries():
    calls, previews = [], []
    def broken(stage, instruction, payload, result_type, model_id):
        calls.append([p["slot"] for p in payload["points"]])
        result = execute(stage, instruction, payload, result_type, model_id)
        if payload["retry_attempt"] == 0:
            result.test_cases[1] = {"slot": 2, "title": "缺少操作"}
            result.test_cases.pop(2)
        return result
    result = run(request(5), broken, lambda cases, total: previews.append([c.id for c in cases]))
    assert calls == [[1, 2, 3, 4, 5], [2, 3]]
    assert previews[0] == ["TC-P-0-1", "TC-P-3-1", "TC-P-4-1"]
    assert len(result.test_cases) == 5 and result.quality.passed


def test_local_repair_retains_valid_siblings_and_marks_unresolved():
    calls = []
    def broken(stage, instruction, payload, result_type, model_id):
        calls.append([p["slot"] for p in payload["points"]])
        result = execute(stage, instruction, payload, result_type, model_id)
        for case in result.test_cases:
            if case.slot == 2:
                case.steps[0].expected = "正常"
        return result
    result = run(request(3), broken)
    assert calls == [[1, 2, 3], [2], [2]]
    assert result.quality.repair_rounds == 2
    assert [c.id for c in result.test_cases] == ["TC-P-0-1", "TC-P-2-1"]
    assert result.quality.passed
    assert any(i.object_id == "P-1" and "待完善" in i.message for i in result.quality.issues)


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
    result = run(request(5), unavailable, lambda *args: previews.append(args))
    assert not result.quality.passed
    assert any(i.code == "no_test_cases" for i in result.quality.issues)
    assert calls == [5, 5, 5]
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
        if issubclass(result_type, ContentBatch):
            for case in result.test_cases:
                case.steps = [CaseStep(action='Open login', expected='Session is established'), CaseStep(action='Submit credentials', expected='')]
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
            steps=[CaseStep(action="扫描过期码", expected="不建立登录会话")]))
    assert reconcile_duplicates(base, req, resolve) == 0
    assert len(base.test_cases) == 2
    assert not any(i.code.startswith('duplicate_case') for i in validate_generation(base).issues)


def test_duplicates_are_flagged_without_model_audit_or_automatic_merge():
    calls = []
    def duplicate(stage, instruction, payload, result_type, model_id):
        calls.append(stage)
        result = execute(stage, instruction, payload, result_type, model_id)
        result.test_cases[1] = result.test_cases[0].model_copy(update={"slot": 2})
        return result
    result = run(request(2), duplicate)
    assert calls == ["test_case.generated"]
    assert len(result.test_cases) == 2
    assert result.quality.passed
    assert any(i.code == "duplicate_case" and i.severity == "warning" for i in result.quality.issues)


def test_compact_payload_shares_features_and_preserves_evidence():
    inputs = []
    def capture(stage, instruction, payload, result_type, model):
        inputs.append(payload)
        return execute(stage, instruction, payload, result_type, model)
    assert run(request(5), capture).quality.passed
    assert inputs[0]["features"]
    assert all("features" not in point for point in inputs[0]["points"])
    assert "confirmed_brief" in inputs[0] and "evidence" in inputs[0]


def test_checkpoint_keeps_parseable_response_for_per_slot_validation():
    from casepilot_agent.compact_generation import validate_stage_result
    batch = ReviewContentBatch(test_cases=[{"slot": 1, "title": "缺少必填字段"}])
    assert validate_stage_result(batch, {"validation_mode": "human_review_basic"}) is batch


def test_invalid_plan_reference_is_not_downgraded_to_review_warning():
    from casepilot_agent.compact_generation import StageContractError
    req = request(2)
    req.confirmed_plan["test_points"][0]["feature_point_ids"] = ["missing"]
    with pytest.raises(StageContractError, match="invalid_feature_reference"):
        run(req)


@pytest.mark.parametrize('size', [3, 5, 10])
@pytest.mark.parametrize('concurrency', [1, 2, 4])
@pytest.mark.parametrize('count', [1, 3, 5, 6, 10, 11, 100])
def test_batch_configuration_preserves_coverage(size, concurrency, count):
    req = request(count).model_copy(update={'batch_size': size, 'batch_concurrency': concurrency})
    calls = []
    def tracked(stage, instruction, payload, result_type, model_id):
        calls.append(payload)
        assert payload['prompt_version'] == 'case-batch-v10-extra-assertions'
        assert payload['batch_count'] <= size
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(req, tracked)
    assert len(result.test_cases) == count
    assert {p for case in result.test_cases for p in case.test_point_ids} == {f'P-{i}' for i in range(count)}
    assert sorted(slot for call in calls for slot in call['batch_slots']) == list(range(1, count + 1))


def test_prompt_removes_exact_repeats_but_preserves_latest_corrections():
    req = request(1)
    req.conversation_memory = [
        {'role':'user','content':'保留预期'}, {'role':'user','content':'改为P0'},
        {'role':'user','content':'保留预期'}, {'role':'user','content':'刚才说错了，改为P2'},
        {'role':'user','content':req.prompt},
    ]
    req.confirmed_plan['feature_points'][0]['description'] = req.prompt
    def tracked(stage, instruction, payload, result_type, model_id):
        assert [m['content'] for m in payload['user_requirements']] == ['改为P0','保留预期','刚才说错了，改为P2']
        assert 'description' not in payload['features'][0]
        return execute(stage, instruction, payload, result_type, model_id)
    assert len(run(req, tracked).test_cases) == 1


def test_runtime_skill_uses_stage_schema_without_obsolete_four_field_contract():
    from casepilot_agent.skills import load_test_case_generation_skill
    load_test_case_generation_skill.cache_clear()
    skill = load_test_case_generation_skill()
    assert 'counts need not match' in skill
    assert 'containing exactly the requested slots' in skill
    assert 'their item counts must match' not in skill
    assert 'Express every candidate with the four-section' not in skill


@pytest.mark.parametrize('wrong_body', ['访问/report/91，返回200', '访问/report/90，返回成功'])
def test_explicit_endpoint_or_status_mismatch_retries_only_affected_slot(wrong_body):
    req = request(2)
    req.confirmed_plan['test_points'][0].update(objective='访问/report/90返回报表90及状态200', scenario='管理员已登录')
    calls = []
    def executor(stage, instruction, payload, result_type, model_id):
        calls.append(payload['batch_slots'])
        assert 'global_scenario_index' not in payload
        result = execute(stage, instruction, payload, result_type, model_id)
        for index, item in enumerate(result.test_cases):
            if item.slot == 1:
                updated = item.model_dump()
                updated.update(title='报表场景', preconditions=['管理员已登录'], steps=[{'action': wrong_body if payload['retry_attempt'] == 0 else '访问/report/90', 'expected': wrong_body if payload['retry_attempt'] == 0 else '返回报表90及状态200'}])
                result.test_cases[index] = updated
        return result
    result = run(req, executor)
    assert calls == [[1, 2], [1]]
    assert len(result.test_cases) == 2
    assert result.quality.repair_rounds == 1


def test_rate_limit_retries_only_the_failed_batch_and_retains_successes():
    import httpx
    from openai import RateLimitError
    calls = []
    def limited(stage, instruction, payload, result_type, model_id):
        calls.append(payload['batch_slots'])
        if payload['batch_slots'] == [6] and payload['retry_attempt'] == 0:
            raise RateLimitError('synthetic rate limit', response=httpx.Response(429,
                request=httpx.Request('POST', 'https://example.test/model')), body=None)
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(request(6), limited)
    assert calls == [[1, 2, 3, 4, 5], [6], [6]]
    assert len(result.test_cases) == 6
    assert len({case.id for case in result.test_cases}) == 6


@pytest.mark.parametrize("explicit,answer,expected", [
    ("账号系统", "旧对象", "账号系统"), ("", "订单系统", "订单系统"), ("", "", ""),
])
def test_confirmed_object_survives_prompt_batches_and_artifact(explicit, answer, expected):
    req = request(6).model_copy(update={"test_object": explicit})
    calls = []
    def tracked(*args):
        calls.append(args[2]["test_object"])
        return execute(*args)
    result = GenerationPipeline(SimpleNamespace(name="real")).run(
        req, context={}, answers={"Q-TEST-OBJECT": answer}, execute_stage=tracked)
    assert calls == [expected, expected]
    assert result.requirement.test_object == expected
    assert result.requirement.test_object_specified is bool(expected)
    assert result.model_dump(mode="json")["requirement"]["test_object"] == expected
    assert result.requirement.test_object != req.prompt
    from unittest.mock import Mock
    from uuid import uuid4
    from casepilot_agent.store import JobStore
    connection = Mock()
    connection.scalar.return_value = 0
    job = {key: uuid4() for key in ("id", "collection_id", "space_id", "account_id")}
    job["input_payload"] = {"persist_cases": False}
    JobStore.__new__(JobStore).persist_generation(connection, job, result.model_dump(mode="json"))
    persisted = connection.execute.call_args_list[0].args[0].compile().params
    assert persisted["requirement_analysis"]["test_object"] == expected


@pytest.mark.parametrize('duration', ['1140秒', '19分钟', '1.14e3秒'])
def test_point_duration_is_executable_and_unit_equivalent(duration):
    from casepilot_agent.compact_generation import validate_point_literals, StageContractError
    point = SimpleNamespace(objective='第四次错误锁定1140秒', scenario='已有3次错误，再提交错误验证码')
    case = CaseContent(slot=1, title='第四次错误锁定1140秒', preconditions=['已有3次错误'],
                       steps=[{'action': '提交错误验证码', 'expected': '返回E419，锁定' + duration}])
    if duration == '1.14e3秒':
        with pytest.raises(StageContractError, match='duration_missing'):
            validate_point_literals(case, point)
    else:
        validate_point_literals(case, point)
    case.steps[0].expected = '返回E419，锁定时刻正确'
    with pytest.raises(StageContractError, match='duration_missing'):
        validate_point_literals(case, point)


@pytest.mark.parametrize('audit_fails', [False, True])
def test_unrequested_counter_effect_is_reviewed_without_regenerating_good_sibling(audit_fails):
    from casepilot_agent.compact_generation import StageContractError
    req = request(2)
    req.prompt = '有效账号建立会话；停用账号返回E403，没有规定错误计数的变化。'
    for p in req.confirmed_plan['test_points']:
        p.update(title='账号状态', scenario='停用账号提交正确凭据', objective='返回E403')
    calls = []
    def complete(stage, instruction, payload, result_type, model_id):
        calls.append((stage, payload.get('batch_slots')))
        if stage == 'test_case.grounded':
            assert [c['slot'] for c in payload['test_cases']] == [2]
            if audit_fails:
                raise StageContractError('audit_unavailable')
            return BatchAudit(reviews=[{'slot':2,'verdict':'revise','reason':'计数副作用没有依据',
                'replacement': {'slot':2,'title':'停用拒绝','preconditions':['账号停用'],
                    'steps':[{'action':'提交正确凭据','expected':'返回E403'}]},
                'assertions':[{'step':1,'source_index':0,'quote':'停用账号返回E403','explanation':'只保留明确错误码'}]}])
        return result_type.model_validate({'test_cases':[{'slot':s,'title':f'账号状态{s}',
            'preconditions':['账号停用'],'steps':[{'action':'提交正确凭据','expected':'返回E403'+('，错误次数不增加' if s==2 else '')}]}
            for s in payload['batch_slots']]})
    result = run(req, complete)
    assert result.test_cases[0].id == 'TC-P-0-1'
    assert [c for c in calls if c[0]=='test_case.generated'] == (
        [('test_case.generated',[1,2]),('test_case.generated',[2]),('test_case.generated',[2])] if audit_fails else [('test_case.generated',[1,2])])
    if audit_fails:
        assert len(result.test_cases)==1
    else:
        assert result.test_cases[1].steps[0].expected=='返回E403'


def test_format_failure_does_not_exhaust_content_repair_and_keeps_successful_sibling():
    req = request(2)
    req.confirmed_plan["test_points"][1]["objective"] = "账号锁定1140秒"
    calls, previews = [], []
    def mixed_failure(stage, instruction, payload, result_type, model_id):
        calls.append((payload["batch_slots"], payload["retry_attempt"]))
        if payload["retry_attempt"] == 0:
            raise ModelBehaviorError("invalid JSON")
        result = execute(stage, instruction, payload, result_type, model_id)
        if payload["retry_attempt"] == 1:
            result.test_cases[1].preconditions = ["账号有效"]
            result.test_cases[1].steps = [CaseStep(action="触发锁定", expected="返回E419")]
        if payload["retry_attempt"] == 2:
            assert payload["validation_feedback"] == {2: "required_point_duration_missing_seconds:1140"}
            # Only the failed point is sent again; the accepted sibling is untouched.
            result.test_cases[0].steps = [CaseStep(action="触发锁定", expected="账号锁定1140秒")]
        return result
    result = run(req, mixed_failure, lambda cases, total: previews.append([c.model_dump() for c in cases]))
    assert calls == [([1, 2], 0), ([1, 2], 1), ([2], 2)]
    assert result.quality.passed and len(result.test_cases) == 2
    assert result.quality.repair_rounds == 2
    assert previews[0][0] == previews[-1][0]
    assert not any(i.code == "uncovered_test_point" for i in result.quality.issues)
