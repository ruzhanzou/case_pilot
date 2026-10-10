from uuid import uuid4

from casepilot_agent.contracts import GenerationRequest, RequirementAnalysis
from casepilot_agent.contracts import TestCaseBatch as CaseBatch
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.planning import build_planning, evidence_batches
from casepilot_agent.providers.mock import MockProvider


def test_evidence_batches_visit_every_character_and_preserve_sources():
    evidence = [{"chunk_id": str(index), "excerpt": f"第{index}章" * 1500} for index in range(15)]
    batches = evidence_batches({"evidence": evidence}, budget=2000)
    reconstructed = {str(index): "" for index in range(15)}
    for batch in batches:
        assert sum(len(item["excerpt"]) for item in batch["evidence"]) <= 2000
        for item in batch["evidence"]:
            reconstructed[item["chunk_id"]] += item["excerpt"]
    assert reconstructed == {item["chunk_id"]: item["excerpt"] for item in evidence}


def test_planning_does_not_request_cases_and_generation_reuses_selected_point():
    provider = MockProvider()
    stages = []

    def complete(stage, instruction, payload, result_type):
        stages.append(stage)
        assert result_type is not CaseBatch
        return provider.complete(
            stage=stage,
            instruction=instruction,
            payload={**payload, "prompt": "登录功能"},
            result_type=result_type,
            model_id="auto",
        )[0]

    planning = build_planning(
        RequirementAnalysis(summary="登录", test_object="登录", test_object_specified=True),
        {"evidence": []},
        complete,
    )
    assert stages == ["feature.generated", "test_point.generated"]
    point = planning["test_points"][0]
    planning["test_points"] = [point]
    planning["brief_version"] = 1
    calls = []

    def execute(stage, instruction, payload, result_type, model_id):
        calls.append(payload)
        assert stage == "test_case.generated"
        return provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]

    result = GenerationPipeline(provider).run(
        GenerationRequest(prompt="登录功能", confirmed_plan=planning),
        context={},
        answers={},
        execute_stage=execute,
    )
    assert result.quality.passed
    assert len(calls) == len(result.test_cases) == 1
    assert result.test_cases[0].test_point_ids == [point["id"]]
    assert not result.test_cases[0].module.endswith(point["title"])
    assert point["scenario"] not in result.test_cases[0].module


def test_full_document_context_keeps_more_than_twelve_blocks_without_truncation():
    from test_embedding_fallback import FakeStore, job

    from casepilot_agent.tasks import _context_payload

    document_id = uuid4()

    class DocumentStore(FakeStore):
        def read_task_documents(self, *args, **kwargs):
            assert kwargs["document_ids"] == [document_id]
            return [
                dict(
                    id=uuid4(),
                    document_id=document_id,
                    source_id=uuid4(),
                    document_name="需求",
                    locator=f"第{i}章",
                    content="规则" * 900,
                    rrf=0,
                    distance=None,
                    lexical=0,
                    task_document=True,
                )
                for i in range(15)
            ]

    request = job(use_space_knowledge=False)
    request["input_payload"]["document_ids"] = [str(document_id)]
    result = _context_payload(DocumentStore(), request, None, full_documents=True)
    assert len(result["evidence"]) == 15
    assert all(len(item["excerpt"]) == 1800 for item in result["evidence"])


def test_rewrite_reads_every_batch_before_extracting_affected_rules():
    from casepilot_agent.planning import rewrite_evidence

    seen = []

    def complete(stage, instruction, payload, result_type):
        assert payload["test_case"]["id"] == "selected-case"
        for item in payload["context"]["evidence"]:
            seen.append(item["chunk_id"])
        return RequirementAnalysis(summary="相关规则", business_rules=[f"规则{seen[-1]}"])

    result = rewrite_evidence(
        {"evidence": [{"chunk_id": str(i), "excerpt": "约束" * 6000} for i in range(15)]},
        {"id": "selected-case"}, complete,
    )
    assert set(seen) == {str(i) for i in range(15)}
    assert result["processed_batches"] == 15
    assert "规则14" in result["business_rules"]


def test_requested_count_reports_uncovered_planning_points_without_discarding_results():
    provider = MockProvider()
    request = GenerationRequest(prompt="为登录生成1条测试用例")
    baseline = provider.generate(request)
    planning = {
        "feature_points": [item.model_dump(mode="json") for item in baseline.feature_points],
        "test_points": [item.model_dump(mode="json") for item in baseline.test_points],
        "brief_version": 1,
    }

    def execute(stage, instruction, payload, result_type, model_id):
        return provider.complete(stage=stage, instruction=instruction, payload=payload,
                                 result_type=result_type, model_id=model_id)[0]

    result = GenerationPipeline(provider).run(
        request.model_copy(update={"confirmed_plan": planning}), context={}, answers={},
        execute_stage=execute,
    )
    assert result.quality.passed
    assert len(result.test_cases) == 1
    assert any(issue.code == "planned_point_uncovered" for issue in result.quality.issues)


def test_planning_batches_features_without_losing_ids_or_coverage():
    from casepilot_agent.contracts import FeaturePlan, TestPointPlan
    seen = []

    def complete(stage, instruction, payload, result_type):
        if stage == 'feature.generated':
            return FeaturePlan.model_validate({'feature_points': [
                {'id': f'F{i}', 'module': '登录', 'name': f'方式{i}',
                 'description': f'规则{i}', 'requirement_refs': []} for i in range(5)
            ]})
        features = payload['feature_points']['feature_points']
        assert len(features) <= 3
        seen.extend(f['name'] for f in features)
        return TestPointPlan.model_validate({'test_points': [
            {'id': 'provider-reuses-id', 'title': f['name'], 'scenario': f['name'],
             'objective': '验证登录', 'category': '功能', 'priority': 'P1',
             'priority_reason': '业务规则', 'feature_point_ids': [f['id']]}
            for f in features
        ]})

    plan = build_planning(RequirementAnalysis(summary='登录'), {'evidence': []}, complete)
    assert sorted(seen) == [f'方式{i}' for i in range(5)]
    assert len({p['id'] for p in plan['test_points']}) == 5
    feature_ids = {f['id'] for f in plan['feature_points']}
    assert {ref for p in plan['test_points'] for ref in p['feature_point_ids']} == feature_ids
