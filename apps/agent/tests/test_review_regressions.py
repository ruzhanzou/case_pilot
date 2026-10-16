"""Regression cases from the generation/rewrite correctness and cost review."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from casepilot_agent.compact_generation import (
    BatchAudit,
    ContentBatch,
    StageContractError,
    validate_stage_result,
)
from casepilot_agent.contracts import (
    GenerationRequest,
    RequirementAnalysis,
    RewriteCandidate,
    RewriteRequest,
)
from casepilot_agent.pipeline import GenerationPipeline, rewrite_batch_payload, rewrite_groups
from casepilot_agent.providers.mock import MockProvider


def case():
    return MockProvider().generate(GenerationRequest(prompt="登录")).test_cases[0]


def test_rewrite_rejects_empty_steps_despite_model_perfect_score():
    original = case()
    proposed = original.model_copy(deep=True)
    proposed.steps[0].action = ""
    proposed.steps[0].expected = ""
    proposed.steps = proposed.steps[:1]
    provider = Mock()
    provider.rewrite.return_value = RewriteCandidate(
        proposed=proposed, diff=[], reason="改写", quality={"passed": True, "score": 100}
    )
    with pytest.raises(ValueError, match="有效操作"):
        GenerationPipeline(provider).rewrite(
            RewriteRequest(test_case=original, instruction="根据附件修正预期，保留已有全部操作步骤")
        )


def test_rewrite_rejects_deleted_protected_action():
    original = case()
    proposed = original.model_copy(deep=True)
    proposed.steps[0].action = "未经授权替换操作"
    provider = Mock()
    provider.rewrite.return_value = RewriteCandidate(
        proposed=proposed, diff=[], reason="改写", quality={"passed": True, "score": 100}
    )
    with pytest.raises(ValueError, match="保留操作步骤"):
        GenerationPipeline(provider).rewrite(
            RewriteRequest(test_case=original, instruction="修正预期，保留已有全部操作步骤")
        )


def test_shared_history_is_sent_once_without_dropping_messages():
    memory = [{"role": "user", "content": str(i) + "需求" * 600} for i in range(100)]
    group = [
        (
            str(i),
            RewriteRequest(test_case=case(), instruction="调整边界", conversation_memory=memory),
        )
        for i in range(20)
    ]
    payload = rewrite_batch_payload(group)
    assert len(payload["shared"]) == 1
    assert payload["shared"][0]["conversation_memory"] == memory
    assert len(payload["items"]) == 20
    assert len(list(rewrite_groups(group))) == 1
    original = {
        "items": [{"ref": ref, **request.model_dump(mode="json")} for ref, request in group]
    }
    assert len(json.dumps(payload)) < len(json.dumps(original)) / 10


def test_groups_bound_different_contexts_and_keep_all_targets():
    group = [
        (
            str(i),
            RewriteRequest(
                test_case=case(), instruction=f"修正{i}", context={"evidence": "x" * 20000}
            ),
        )
        for i in range(7)
    ]
    batches = list(rewrite_groups(group, budget=60000))
    assert [ref for batch in batches for ref, _ in batch] == [str(i) for i in range(7)]
    assert all(
        len(json.dumps(rewrite_batch_payload(batch), ensure_ascii=False)) <= 60000
        for batch in batches
    )


def test_grounding_requires_every_expectation_and_real_original_quote():
    content = {
        "slot": 1,
        "title": "登录",
        "preconditions": ["有效账号"],
        "steps": [{"action": "登录", "expected": "建立会话"}],
    }
    inputs = {"test_cases": [content], "grounding_sources": ["有效账号登录后建立会话。"]}
    audit = BatchAudit(
        reviews=[{"slot": 1, "verdict": "supported", "replacement": None, "reason": ""}]
    )
    with pytest.raises(StageContractError, match="not_covered"):
        validate_stage_result(audit, inputs)
    audit.reviews[0].assertions = []
    data = audit.model_dump()
    data["reviews"][0]["assertions"] = [
        {"step": 1, "source_index": 0, "quote": "显示首页导航", "explanation": "推断"}
    ]
    with pytest.raises(StageContractError, match="not_in_original_source"):
        validate_stage_result(BatchAudit.model_validate(data), inputs)
    data["reviews"][0]["assertions"][0]["quote"] = "登录后建立会话"
    validate_stage_result(BatchAudit.model_validate(data), inputs)


def test_invalid_generation_cache_is_replaced_and_never_resaved(monkeypatch):
    from casepilot_agent import tasks

    original = MockProvider().generate(GenerationRequest(prompt="登录"))
    req = GenerationRequest(
        prompt="生成1条用例",
        output_contract="case_batch_v2",
        confirmed_plan={
            "feature_points": [f.model_dump() for f in original.feature_points],
            "test_points": [original.test_points[0].model_dump()],
        },
    )
    job_id = uuid4()
    job = {
        "id": job_id,
        "status": "running",
        "input_payload": req.model_dump(),
        "output_payload": {},
    }
    store = MagicMock()
    store.connection.side_effect = lambda: nullcontext(object())
    store.claim_job.return_value = job
    store.get_job_for_update.return_value = job
    store.is_cancelled.return_value = False
    corrupt = {
        "slot": 999,
        "title": "错误缓存",
        "preconditions": ["账号有效"],
        "steps": [{"action": "登录", "expected": "成功"}],
    }
    store.load_completed_stage.return_value = {"output_payload": {"test_cases": [corrupt]}}
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["stage"])
        return MockProvider().complete(**kwargs)

    monkeypatch.setattr(tasks, "JobStore", lambda *_: store)
    monkeypatch.setattr(
        tasks, "create_provider", lambda *_: SimpleNamespace(name="mock", complete=complete)
    )
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    # Stop after the stage was validated and saved, before persistence unrelated to this regression.
    monkeypatch.setattr(
        tasks,
        "_apply_persisted_asset_quality",
        Mock(side_effect=RuntimeError("stop_after_checkpoint")),
    )
    with pytest.raises(RuntimeError, match="stop_after_checkpoint"):
        tasks.generate_test_cases.run(str(job_id))
    assert calls == ["test_case.generated"]
    stages = [c.kwargs for c in store.record_stage.call_args_list]
    assert stages and stages[0]["output_payload"]["test_cases"][0]["slot"] == 1


def test_wrong_fresh_slot_is_rejected_before_checkpoint():
    content = ContentBatch(
        test_cases=[
            {
                "slot": 999,
                "title": "错位",
                "preconditions": ["前置"],
                "steps": [{"action": "操作", "expected": "结果"}],
            }
        ]
    )
    with pytest.raises(StageContractError, match="slot_mismatch"):
        validate_stage_result(content, {"points": [{"slot": 1}]})


@pytest.mark.parametrize(
    "selection", [{"knowledge_source_ids": ["source"]}, {"use_space_knowledge": True}]
)
def test_rewrite_uses_source_only_and_space_knowledge(monkeypatch, selection):
    from casepilot_agent import tasks

    context = {"evidence": [{"excerpt": "原始业务规则"}], "warnings": []}
    retrieve = Mock(return_value=context)
    extraction = Mock(return_value=context)
    monkeypatch.setattr(tasks, "_context_payload", retrieve)
    monkeypatch.setattr(tasks, "_rewrite_reference_context", extraction)
    requests = {
        str(i): RewriteRequest(test_case=case(), instruction="根据资料调整边界") for i in range(20)
    }
    prepared = tasks._prepare_rewrite_requests(
        Mock(), {"input_payload": selection}, Mock(), requests
    )
    retrieve.assert_called_once()
    extraction.assert_called_once()
    assert len(extraction.call_args.args[-1]["selected_cases"]) == 20
    assert all(request.context == context for request in prepared.values())


def test_exact_priority_assignment_skips_all_retrieval(monkeypatch):
    from casepilot_agent import tasks

    retrieve = Mock(side_effect=AssertionError("local edit must not retrieve"))
    monkeypatch.setattr(tasks, "_context_payload", retrieve)
    requests = {"one": RewriteRequest(test_case=case(), instruction="优先级改为P0")}
    tasks._prepare_rewrite_requests(
        Mock(), {"input_payload": {"document_ids": ["large"]}}, Mock(), requests
    )
    retrieve.assert_not_called()


def test_shared_large_evidence_reads_each_batch_once_and_keeps_quotes():
    from casepilot_agent.planning import rewrite_evidence

    calls = []
    evidence = [
        {"chunk_id": str(i), "excerpt": f"规则{i}：超时后允许重试。" + " " * 18000}
        for i in range(4)
    ]

    def complete(stage, instruction, payload, result_type):
        calls.append(payload)
        text = payload["context"]["evidence"][0]["excerpt"].strip()
        return RequirementAnalysis(summary="规则", business_rules=[text] if text else [])

    result = rewrite_evidence({"evidence": evidence}, {"selected_cases": [{}] * 20}, complete)
    assert len(calls) == result["processed_batches"]
    assert len(calls) < 20 * len(evidence)
    assert len(json.dumps(result, ensure_ascii=False)) < 10000
    assert all(
        source["excerpt"]
        in next(e["excerpt"] for e in evidence if e["chunk_id"] == source["chunk_id"])
        for source in result["evidence"]
    )


def test_oversized_single_rewrite_fails_without_silent_truncation():
    request = RewriteRequest(
        test_case=case(), instruction="调整预期", context={"evidence": "x" * 180001}
    )
    with pytest.raises(ValueError, match="输入预算"):
        list(rewrite_groups([("one", request)]))


def test_single_case_malformed_json_retries_only_once():
    from agents.exceptions import ModelBehaviorError
    from test_compact_generation import request, run, execute

    calls = []

    def unstable(stage, instruction, payload, result_type, model_id):
        calls.append(stage)
        if len(calls) == 1:
            raise ModelBehaviorError("invalid JSON")
        return execute(stage, instruction, payload, result_type, model_id)

    assert len(run(request(1), unstable).test_cases) == 1
    assert calls.count("test_case.generated") == 2


def test_empty_setup_in_audit_replacement_is_not_cacheable():
    replacement = {
        "slot": 1,
        "title": "登录",
        "preconditions": [" "],
        "steps": [{"action": "登录", "expected": "建立会话"}],
    }
    audit = BatchAudit(
        reviews=[{"slot": 1, "verdict": "revise", "replacement": replacement, "reason": "修正"}]
    )
    with pytest.raises(StageContractError, match="empty_case_title_or_setup"):
        validate_stage_result(audit, {"test_cases": [replacement]})


@pytest.mark.parametrize('quote,source,valid', [
    ('退出后旧会话失效.', '退出后旧会话失效。', True),
    ('退款金额不得超过实付金额。', '退款金额不得超过实付金额.', True),
    ('错误3次锁定15分钟.', '错误5次锁定15分钟。', False),
    ('退款金额超过实付金额.', '退款金额不得超过实付金额。', False),
    ('金额1。', '金额1.5元', False),
])
def test_audit_only_normalizes_sentence_stop(quote, source, valid):
    content = {'slot': 1, 'title': '核对规则', 'preconditions': ['有数据'],
               'steps': [{'action': '执行', 'expected': '核对结果'}]}
    audit = BatchAudit(reviews=[{'slot': 1, 'verdict': 'supported', 'replacement': None,
        'reason': '', 'assertions': [{'step': 1, 'source_index': 0, 'quote': quote,
                                    'explanation': '原文'}]}])
    payload = {'test_cases': [content], 'grounding_sources': [source]}
    if valid:
        validate_stage_result(audit, payload)
        assert audit.reviews[0].assertions[0].quote in source
    else:
        with pytest.raises(StageContractError):
            validate_stage_result(audit, payload)


def test_human_review_generation_never_calls_model_audit():
    from agents.exceptions import ModelBehaviorError
    from test_compact_generation import request, run, execute
    calls = []
    def flaky(stage, instruction, payload, result_type, model_id):
        calls.append((stage, payload['batch_count'], payload.get('validation_feedback')))
        if stage == 'test_case.grounded' and payload['batch_count'] > 1:
            raise ModelBehaviorError('malformed JSON')
        return execute(stage, instruction, payload, result_type, model_id)
    result = run(request(2), flaky)
    assert len(result.test_cases) == 2
    assert [c[1] for c in calls if c[0] == 'test_case.generated'] == [2]
    assert [c[1] for c in calls if c[0] == 'test_case.grounded'] == []


@pytest.mark.parametrize('source_index', [0, 99])
def test_audit_resolves_misnumbered_quote_only_within_original_evidence(source_index):
    content = {'slot': 7, 'title': '订单', 'preconditions': ['有库存'],
               'steps': [{'action': '下单', 'expected': '创建订单成功'}]}
    data = {'reviews': [{'slot': 7, 'verdict': 'supported', 'replacement': None,
        'reason': '', 'assertions': [{'step': 1, 'source_index': source_index,
            'quote': 'ORDER-1: 库存充足创建订单成功.', 'explanation': '原始规则'}]}]}
    audit = BatchAudit.model_validate(data)
    payload = {'test_cases': [content], 'grounding_sources': [
        'LOGIN-6: 退出后旧会话失效。', 'ORDER-1: 库存充足创建订单成功。']}
    validate_stage_result(audit, payload)
    support = audit.reviews[0].assertions[0]
    assert support.source_index == 1
    assert support.quote == payload['grounding_sources'][1]
    with pytest.raises(StageContractError, match='not_in_original_source'):
        validate_stage_result(BatchAudit.model_validate(data),
                              {**payload, 'grounding_sources': payload['grounding_sources'][:1]})


def test_rewrite_extraction_does_not_repeat_case_source_excerpts(monkeypatch):
    from casepilot_agent import tasks
    from casepilot_agent.contracts import SourceRef
    original = case()
    original.source_refs = [SourceRef(label='大型附件', excerpt='原文' * 20000)]
    requests = {str(i): RewriteRequest(test_case=original, instruction='按附件核对预期') for i in range(18)}
    context = {'evidence': [{'excerpt': '原始业务规则'}]}
    monkeypatch.setattr(tasks, '_context_payload', Mock(return_value=context))
    extract = Mock(return_value=context)
    monkeypatch.setattr(tasks, '_rewrite_reference_context', extract)
    prepared = tasks._prepare_rewrite_requests(Mock(), {'input_payload': {'document_ids': ['doc']}}, Mock(), requests)
    extract.assert_called_once()
    snapshots = extract.call_args.args[-1]['selected_cases']
    assert len(snapshots) == 18
    assert all('source_refs' not in item['test_case'] for item in snapshots)
    assert all(item['test_case']['steps'] == original.model_dump()['steps'] for item in snapshots)
    assert all(r.test_case.source_refs == original.source_refs for r in prepared.values())


def test_rewrite_payload_interns_original_sources_losslessly():
    from casepilot_agent.contracts import SourceRef
    original = case()
    original.source_refs = [SourceRef(label='附件', excerpt='完整原文' * 10000)]
    group = [(str(i), RewriteRequest(test_case=original, instruction='只改标题')) for i in range(18)]
    payload = rewrite_batch_payload(group)
    assert len(payload['source_references']) == 1
    for item in payload['items']:
        restored = [payload['source_references'][i] for i in item['source_ref_indexes']]
        assert restored == original.model_dump(mode='json')['source_refs']
    assert len(list(rewrite_groups(group))) == 1


def test_rewrite_rule_id_hint_restores_original_conditions_and_overlapping_windows():
    from casepilot_agent.planning import rewrite_evidence
    from casepilot_agent.contracts import RequirementAnalysis
    text = 'ORDER-1: 库存充足创建订单成功。特殊账户除外。ORDER-2: 库存不足拒绝创建订单。'
    context = {'evidence': [{'chunk_id': str(i), 'excerpt': text + ' ' * 18000} for i in range(2)]}
    def extract(stage, instruction, payload, result_type):
        return RequirementAnalysis(summary='规则', business_rules=['ORDER-1：库存充足时创建订单成功', 'ORDER-2：库存不足时拒绝创建订单'])
    result = rewrite_evidence(context, {}, extract)
    assert len(result['evidence']) <= 4
    assert all('时' not in s for s in result['business_rules'])
    assert any('特殊账户除外' in x['excerpt'] for x in result['evidence'])
    assert all(any(x['excerpt'] in s['excerpt'] for s in context['evidence']) for x in result['evidence'])


def test_rewrite_timeout_retries_once_and_preserves_targets():
    import httpx
    from openai import APITimeoutError
    calls = []
    def complete(**kwargs):
        items = kwargs['payload']['items'];calls.append(len(items))
        if not kwargs['payload'].get('validation_feedback'):
            raise APITimeoutError(request=httpx.Request('POST', 'https://example.test'))
        return kwargs['result_type'].model_validate({'items': [
            {'ref':item['ref'], 'changes':{'title':'复核 '+item['test_case']['title']},
             'reason':'改标题','quality':{'passed':True,'score':90}} for item in items]}), None
    requests = {str(i): RewriteRequest(test_case=case(), instruction='润色标题') for i in range(2)}
    result = GenerationPipeline(SimpleNamespace(name='real',complete=complete)).rewrite_many(requests)
    assert set(result) == set(requests)
    assert calls == [2,2]


def test_rewrite_schema_forbids_unrequested_system_fields():
    from pydantic import ValidationError
    from casepilot_agent.contracts import RewritePatchItem
    with pytest.raises(ValidationError):
        RewritePatchItem(ref='one', changes={'id':'invented'}, reason='修改', quality={'passed':True,'score':100})


@pytest.mark.parametrize('index,valid', [(0, True), (999, False)])
def test_rewrite_sources_are_restored_from_server_catalog(index, valid):
    from casepilot_agent.contracts import SourceRef
    original = case();original.source_refs=[SourceRef(label='原资料',excerpt='原文不可改写')]
    def complete(**kwargs):
        entry=kwargs['payload']['items'][0]
        return kwargs['result_type'].model_validate({'items':[{'ref':entry['ref'],
            'changes':{'source_ref_indexes':[index]},'reason':'更新引用',
            'quality':{'passed':True,'score':90}}]}),None
    pipeline=GenerationPipeline(SimpleNamespace(name='real',complete=complete))
    requests={'one':RewriteRequest(test_case=original,instruction='核对来源引用')}
    if valid:
        result=pipeline.rewrite_many(requests)
        assert result['one'].proposed.source_refs==original.source_refs
    else:
        candidate = pipeline.rewrite_many(requests)['one']
        assert not candidate.quality.passed
        assert candidate.proposed == original
        assert candidate.diff == []


@pytest.mark.parametrize("original_setup,allowed", [([], True), (["账号已注册"], False)])
def test_rewrite_allows_existing_empty_setup_but_rejects_losing_required_setup(original_setup, allowed):
    from casepilot_agent.contracts import RewriteCaseDraft
    from casepilot_agent.pipeline import RewriteContentError, validate_rewrite_candidate

    original = RewriteCaseDraft.model_validate({**case().model_dump(), "preconditions": original_setup})
    proposed = original.model_copy(update={"title": "修改后的标题", "preconditions": []})
    candidate = RewriteCandidate(proposed=proposed, diff=[], reason="仅改标题", quality={"passed": True, "score": 100})
    request = RewriteRequest(test_case=original, instruction="仅修改标题")
    if allowed:
        assert validate_rewrite_candidate(request, candidate).proposed.preconditions == []
    else:
        with pytest.raises(RewriteContentError, match="前置条件"):
            validate_rewrite_candidate(request, candidate)
