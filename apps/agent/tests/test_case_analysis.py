import json

import pytest

from casepilot_agent.case_analysis import (
    CaseAnalysisReport,
    CaseFinding,
    analysis_batches,
    render_report,
)
from casepilot_agent.providers.mock import MockProvider


def test_analysis_progress_is_persisted_and_cancelled_job_cannot_be_revived():
    from unittest.mock import MagicMock
    from uuid import uuid4

    from casepilot_agent.tasks import GenerationCancelled, publish_analysis_progress

    store = MagicMock()
    store.get_job_for_update.return_value = {
        "status": "running",
        "output_payload": {"saved_result": "keep"},
    }
    publish_analysis_progress(store, uuid4(), 2, 4)
    values = store.update_job.call_args.kwargs
    assert values["output_payload"]["saved_result"] == "keep"
    assert values["output_payload"]["analysis_progress"] == {
        "completed_batches": 2,
        "total_batches": 4,
        "progress": 52,
    }
    started_at = values["output_payload"]["started_at"]
    store.get_job_for_update.return_value["output_payload"] = values["output_payload"]
    publish_analysis_progress(store, uuid4(), 3, 4)
    assert store.update_job.call_args.kwargs["output_payload"]["started_at"] == started_at
    store.update_job.reset_mock()
    store.publish.reset_mock()
    store.get_job_for_update.return_value = {
        "status": "cancelled",
        "output_payload": values["output_payload"],
    }
    with pytest.raises(GenerationCancelled):
        publish_analysis_progress(store, uuid4(), 3, 4)
    store.update_job.assert_not_called()
    store.publish.assert_not_called()


def test_report_preserves_evidence_and_rejects_unknown_case_references():
    report = CaseAnalysisReport(
        summary="发现冗余",
        findings=[
            CaseFinding(
                title="重复提交",
                severity="medium",
                case_refs=["A", "B"],
                evidence="前提、动作及预期相同",
                recommendation="保留 A，人工确认后处理 B",
            )
        ],
    )
    assert "已检查 2 条" in render_report(report, [{"ref": "A"}, {"ref": "B"}])
    with pytest.raises(ValueError, match="unknown_case_reference"):
        render_report(report, [{"ref": "A"}])


def test_mock_report_does_not_claim_semantic_review():
    report, _ = MockProvider().complete(
        stage="cases.analyzed",
        instruction="review",
        payload={"cases": []},
        result_type=CaseAnalysisReport,
        model_id="auto",
    )
    assert report.limitations and not report.findings


def test_large_case_analysis_is_split_into_bounded_requests():
    cases = [
        {
            "ref": str(index),
            "snapshot": {
                "title": f"用例 {index}",
                "steps": [{"action": "测试操作", "expected": "期望结果"}],
            },
        }
        for index in range(1001)
    ]
    batches = list(analysis_batches(cases))
    assert sum(map(len, batches)) == 1001
    assert all(len(batch) <= 20 for batch in batches)
    assert all(len(json.dumps(batch, ensure_ascii=False)) <= 18000 for batch in batches)
    oversized = {
        "ref": "large",
        "snapshot": {
            "title": "长用例",
            "description": '引号"与换行\n' * 4000,
            "preconditions": ["X" * 2000] * 10,
            "steps": [
                {"action": f"操作{i}" + "X" * 2000, "expected": "Y" * 2000} for i in range(10)
            ],
        },
    }
    pieces = list(analysis_batches([oversized]))
    assert len(pieces) > 1
    assert all(len(json.dumps(batch, ensure_ascii=False)) < 16000 for batch in pieces)
    assert [batch[0]["fragment_index"] for batch in pieces] == list(range(1, len(pieces) + 1))
    assert all(batch[0]["fragment_count"] == len(pieces) for batch in pieces)
    restored = json.loads("".join(batch[0]["content_json_fragment"] for batch in pieces))
    assert restored == oversized["snapshot"]


def test_normal_long_case_keeps_steps_after_six_and_full_field_text():
    body = {
        "title": "登录",
        "description": "需求" * 600,
        "steps": [{"action": f"操作{i}", "expected": f"完整预期{i}"} for i in range(25)],
    }
    batches = list(analysis_batches([{"ref": "A", "snapshot": body}]))
    assert batches == [[{"ref": "A", "snapshot": body}]]
    assert batches[0][0]["snapshot"]["steps"][-1]["expected"] == "完整预期24"


def test_fragment_cannot_establish_whole_case_duplicate_or_confirmed_gap():
    from casepilot_agent.case_analysis import constrain_fragment_findings

    report = CaseAnalysisReport(
        summary="分析",
        findings=[
            CaseFinding(
                title="重复",
                severity="medium",
                case_refs=["A", "B"],
                evidence="局部内容相同",
                recommendation="删除B",
                relationship="duplicate",
            ),
            CaseFinding(
                title="覆盖不足",
                severity="medium",
                case_refs=["A"],
                evidence="片段没有校验",
                recommendation="补充",
                relationship="coverage",
                basis="requirement",
                requirement_refs=["R1"],
            ),
        ],
    )
    constrain_fragment_findings(report, [{"ref": "A", "fragment_count": 3}, {"ref": "B"}])
    assert report.findings[0].relationship == "overlap"
    assert "不能据此直接删除" in report.findings[0].recommendation
    assert report.findings[1].basis == "potential"


def test_analysis_worker_persists_report_and_finishes_without_rewriting(monkeypatch):
    from unittest.mock import MagicMock
    from uuid import uuid4

    from casepilot_agent import tasks

    job_id = str(uuid4())
    store = MagicMock()
    store.is_cancelled.return_value = False
    store.claim_job.return_value = {
        "id": job_id,
        "input_payload": {
            "prompt": "检查冗余",
            "analysis_kind": "CASE_DEDUP",
            "model_id": "auto",
            "case_context": [{"ref": "A", "snapshot": {"title": "Submit"}}],
        },
    }
    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: MockProvider())
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args: {"evidence": []})
    result = tasks.answer_knowledge_question.run(job_id)
    assert "analysis_report" in result
    metadata = store.complete_job_message.call_args.kwargs["metadata_values"]
    assert metadata["checked_case_count"] == 1
    assert metadata["analysis_report"]["limitations"]
    assert store.update_job.call_args.kwargs["status"] == "completed"


def test_analysis_worker_collapses_equivalent_content_without_losing_original_groups(monkeypatch):
    from unittest.mock import MagicMock
    from uuid import uuid4

    from casepilot_agent import tasks

    class RecordingProvider(MockProvider):
        calls = []

        def complete(self, **kwargs):
            self.calls.append(kwargs["payload"]["cases"])
            return super().complete(**kwargs)

    provider = RecordingProvider()
    store = MagicMock()
    store.is_cancelled.return_value = False
    store.claim_job.return_value = {
        "id": str(uuid4()),
        "input_payload": {
            "prompt": "检查冗余",
            "analysis_kind": "CASE_DEDUP",
            "model_id": "auto",
            "case_context": [
                {"ref": str(index), "snapshot": {"title": f"用例 {index}"}} for index in range(45)
            ],
        },
    }
    for item in store.claim_job.return_value["input_payload"]["case_context"][:24]:
        item["snapshot"] = {
            "title": "重复场景",
            "module": "账号",
            "steps": [{"action": "提交", "expected": "成功"}],
        }
    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: provider)
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args: {"evidence": []})
    result = tasks.answer_knowledge_question.run(str(uuid4()))
    assert [len(batch) for batch in provider.calls] == [22]
    assert "已检查 45 条" in result["answer"]
    assert any("跨批次" in item for item in result["analysis_report"]["limitations"])
    assert any("990/990" in item for item in result["analysis_report"]["limitations"])
    assert len(result["analysis_report"]["findings"]) == 1
    assert set(result["analysis_report"]["findings"][0]["case_refs"]) == {str(i) for i in range(24)}
    assert "全量原文比对" in result["analysis_report"]["summary"]
    assert any(
        "mock" in item.lower() or "模拟" in item
        for item in result["analysis_report"]["limitations"]
    )


def test_equivalent_review_inputs_keep_aliases_but_never_merge_business_or_provenance_changes():
    from copy import deepcopy

    from casepilot_agent.case_analysis import equivalent_analysis_cases

    body = {
        "id": "id-A",
        "case_key": "A",
        "created_at": "old",
        "current_revision_id": "rev-A",
        "title": "登录",
        "priority": "P1",
        "test_targets": ["web"],
        "source_refs": [{"document_id": "doc-A"}],
        "steps": [{"id": "step-A", "action": "登录", "expected": "成功"}],
    }
    copy = deepcopy(body)
    copy.update(id="id-B", case_key="B", created_at="new", current_revision_id="rev-B")
    copy["steps"][0]["id"] = "step-B"
    rows = [{"ref": "A", "snapshot": body}, {"ref": "B", "snapshot": copy}]
    representatives, aliases = equivalent_analysis_cases(rows)
    assert representatives == [rows[0]] and aliases == {"A": ["A", "B"]}
    for field, value in [
        ("priority", "P0"),
        ("test_targets", ["mobile"]),
        ("source_refs", [{"document_id": "doc-B"}]),
    ]:
        changed = {**copy, field: value}
        assert len(equivalent_analysis_cases([rows[0], {"ref": "B", "snapshot": changed}])[0]) == 2
    assert body["steps"][0]["id"] == "step-A" and copy["steps"][0]["id"] == "step-B"


def test_cross_batch_counts_preserve_weighted_original_pairs():
    from casepilot_agent.case_analysis import cross_batch_comparisons

    batches = [
        [{"ref": "A", "snapshot": {"title": "a"}}],
        [{"ref": "B", "snapshot": {"title": "b"}}],
    ]
    bridges, count = cross_batch_comparisons(batches, weights={"A": 3, "B": 2})
    assert len(bridges) == 1 and count == 6


def test_oversized_group_is_split_when_complete_individual_pairs_fit():
    from casepilot_agent.case_analysis import cross_batch_comparisons

    batches = [
        [{"ref": "A", "snapshot": {"description": "A" * 9000}}],
        [
            {"ref": "B", "snapshot": {"description": "B" * 3600}},
            {"ref": "C", "snapshot": {"description": "C" * 3600}},
        ],
    ]
    bridges, count = cross_batch_comparisons(batches)
    assert count == 2 and len(bridges) == 2
    assert {tuple(item["ref"] for item in batch) for batch in bridges} == {("A", "B"), ("A", "C")}
    assert all(len(json.dumps(batch, ensure_ascii=False)) <= 16000 for batch in bridges)
    assert all(len(batch[0]["snapshot"]["description"]) == 9000 for batch in bridges)


def test_cross_batch_comparison_covers_all_pairs_without_title_filtering():
    from itertools import combinations

    from casepilot_agent.case_analysis import cross_batch_comparisons

    cases = [
        {
            "ref": str(i),
            "snapshot": {
                "title": f"完全不同标题{i}",
                "steps": [{"action": f"操作{i}", "expected": f"预期{i}"}],
            },
        }
        for i in range(45)
    ]
    batches = list(analysis_batches(cases))
    bridges, count = cross_batch_comparisons(batches)
    pairs = {
        tuple(sorted((a["ref"], b["ref"])))
        for batch in [*batches, *bridges]
        for a, b in combinations(batch, 2)
    }
    assert len(pairs) == 45 * 44 // 2
    assert count == 600
    assert len(bridges) == 3
    assert all(
        len(batch) <= 40 and len(json.dumps(batch, ensure_ascii=False)) <= 16000
        for batch in bridges
    )
    original = {item["ref"]: item["snapshot"] for item in cases}
    assert all(item["snapshot"] == original[item["ref"]] for batch in bridges for item in batch)


def test_cross_batch_comparison_budget_and_oversized_cases_are_not_silently_counted():
    from casepilot_agent.case_analysis import cross_batch_comparisons

    batches = [[{"ref": str(i), "snapshot": {"title": f"场景{i}"}}] for i in range(100)]
    bridges, count = cross_batch_comparisons(batches, max_batches=3)
    assert len(bridges) == count == 3
    large = [
        [{"ref": "A", "snapshot": {"title": "X" * 15000}}],
        [{"ref": "B", "snapshot": {"title": "Y" * 15000}}],
        [{"ref": "C", "fragment_count": 2, "content_json_fragment": "part"}],
    ]
    assert cross_batch_comparisons(large) == ([], 0)


def test_full_content_duplicate_check_crosses_batches_and_ignores_storage_ids():
    from copy import deepcopy

    from casepilot_agent.case_analysis import exact_duplicate_findings

    original = {
        "title": "登录",
        "module": "账号",
        "case_type": "功能",
        "preconditions": ["账号启用"],
        "steps": [
            {"id": "step-A", "action": f"执行第{i}项", "expected": "检查" * 400} for i in range(8)
        ],
    }
    duplicate = deepcopy(original)
    for step in duplicate["steps"]:
        step["id"] = "different-storage-id"
    different_tail = deepcopy(original)
    different_tail["steps"][7]["expected"] += "不同结果"
    cases = [
        {"ref": "A", "snapshot": original},
        *[{"ref": str(i), "snapshot": {"title": f"其他{i}"}} for i in range(45)],
        {"ref": "B", "snapshot": duplicate},
        {"ref": "C", "snapshot": different_tail},
    ]
    findings = exact_duplicate_findings(cases)
    assert len(findings) == 1 and findings[0].case_refs == ["A", "B"]
    assert findings[0].relationship == "duplicate"
    assert original["steps"][0]["id"] == "step-A"


@pytest.mark.parametrize(
    "field,value",
    [("module", "支付"), ("title", "不同场景"), ("tags", ["Android"]), ("case_type", "性能")],
)
def test_duplicate_check_does_not_conflate_different_business_contexts(field, value):
    from casepilot_agent.case_analysis import exact_duplicate_findings

    body = {"title": "提交", "module": "账号", "steps": [{"action": "提交", "expected": "成功"}]}
    assert (
        exact_duplicate_findings(
            [{"ref": "A", "snapshot": body}, {"ref": "B", "snapshot": {**body, field: value}}]
        )
        == []
    )


def test_long_review_stops_between_batches_without_reporting_false_completion(monkeypatch):
    from unittest.mock import MagicMock, Mock
    from uuid import uuid4

    from casepilot_agent import tasks

    store = MagicMock()
    store.is_cancelled.side_effect = [False, True]
    job_id = str(uuid4())
    store.claim_job.return_value = {
        "id": job_id,
        "input_payload": {
            "prompt": "评审所有用例",
            "analysis_kind": "CASE_REVIEW",
            "model_id": "auto",
            "case_context": [{"ref": str(i), "snapshot": {"title": f"场景{i}"}} for i in range(30)],
        },
    }
    provider = MockProvider()
    provider.complete = Mock(wraps=provider.complete)
    fail = Mock()
    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: provider)
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args: {"evidence": []})
    monkeypatch.setattr(tasks, "fail_job", fail)
    result = tasks.answer_knowledge_question.run(job_id)
    assert result == {"job_id": job_id, "status": "cancelled"}
    assert provider.complete.call_count == 1
    fail.assert_not_called()
    store.complete_job_message.assert_not_called()


def test_analysis_reference_repair_is_bounded_and_preserves_usage():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from casepilot_agent.case_analysis import complete_analysis_batch
    from casepilot_agent.contracts import UsageMetadata
    def report(ref):
        return CaseAnalysisReport(summary="评审结果", findings=[CaseFinding(
            title="预期不明确", severity="medium", case_refs=[ref], evidence="原文",
            recommendation="明确断言")])
    provider = SimpleNamespace(complete=Mock(side_effect=[
        (report("invented"), UsageMetadata(model="real", token_usage={"total_tokens": 3})),
        (report("c0"), UsageMetadata(model="real", token_usage={"total_tokens": 5})),
    ]))
    result, usage = complete_analysis_batch(provider, instruction="评审全部",
        payload={"cases": [{"ref": "original-id", "snapshot": {"title": "登录"}}]}, model_id="auto")
    assert result.findings[0].case_refs == ["original-id"]
    assert usage.token_usage["total_tokens"] == 8
    assert provider.complete.call_args.kwargs["payload"]["validation_feedback"]["unknown_references"] == ["invented"]


def test_analysis_invalid_reference_is_never_silently_dropped():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from casepilot_agent.case_analysis import complete_analysis_batch
    from casepilot_agent.contracts import UsageMetadata
    provider = SimpleNamespace(complete=Mock(return_value=(CaseAnalysisReport(
        summary="结果", findings=[CaseFinding(title="问题", severity="high", case_refs=["outside"],
        evidence="原文", recommendation="修订")]), UsageMetadata(model="real"))))
    with pytest.raises(ValueError, match="analysis_unknown_case_reference"):
        complete_analysis_batch(provider, instruction="评审全部", payload={"cases": [{"ref": "A"}]}, model_id="auto")
    assert provider.complete.call_count == 2
