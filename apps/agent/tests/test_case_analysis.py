import json

import pytest

from casepilot_agent.case_analysis import (
    CaseAnalysisReport,
    CaseFinding,
    analysis_batches,
    render_report,
)
from casepilot_agent.providers.mock import MockProvider


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
        {"ref": str(index), "snapshot": {"title": f"用例 {index}", "steps": [
            {"action": "测试操作", "expected": "期望结果"}
        ]}}
        for index in range(1001)
    ]
    batches = list(analysis_batches(cases))
    assert sum(map(len, batches)) == 1001
    assert all(len(batch) <= 20 for batch in batches)
    assert all(
        len(json.dumps(batch, ensure_ascii=False)) <= 18000
        for batch in batches
    )
    oversized = {"ref": "large", "snapshot": {
        "title": "X" * 100_000,
        "preconditions": ["X" * 100_000] * 100,
        "steps": [{"action": "X" * 100_000, "expected": "X" * 100_000}] * 100,
    }}
    compact = list(analysis_batches([oversized]))[0][0]
    assert compact["truncated"]
    assert len(json.dumps(compact, ensure_ascii=False)) < 16000


def test_analysis_worker_persists_report_and_finishes_without_rewriting(monkeypatch):
    from unittest.mock import MagicMock
    from uuid import uuid4

    from casepilot_agent import tasks

    job_id = str(uuid4())
    store = MagicMock()
    store.claim_job.return_value = {"id": job_id, "input_payload": {
        "prompt": "检查冗余", "analysis_kind": "CASE_DEDUP", "model_id": "auto",
        "case_context": [{"ref": "A", "snapshot": {"title": "Submit"}}],
    }}
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


def test_analysis_worker_sends_large_selection_in_batches(monkeypatch):
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
    store.claim_job.return_value = {"id": str(uuid4()), "input_payload": {
        "prompt": "检查冗余", "analysis_kind": "CASE_DEDUP", "model_id": "auto",
        "case_context": [
            {"ref": str(index), "snapshot": {"title": f"用例 {index}"}}
            for index in range(45)
        ],
    }}
    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: provider)
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args: {"evidence": []})
    result = tasks.answer_knowledge_question.run(str(uuid4()))
    assert [len(batch) for batch in provider.calls] == [20, 20, 5]
    assert "已检查 45 条" in result["answer"]
    assert any("跨批次" in item for item in result["analysis_report"]["limitations"])
