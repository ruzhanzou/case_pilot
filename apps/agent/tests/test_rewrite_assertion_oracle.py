"""Independent synthetic acceptance oracles, not production business classifiers."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_rewrite_preservation import original

from casepilot_agent.contracts import (
    QualityIssue,
    QualityReport,
    RequirementAnalysis,
    RewriteCandidate,
    RewriteRequest,
    UsageMetadata,
)
from casepilot_agent.pipeline import RewriteContentError, validate_rewrite_candidate
from casepilot_agent.planning import rewrite_evidence


@pytest.fixture(params=[
    ("金额必填", "不创建任何报销单", "系统拒绝提交，不创建任何报销单"),
    ("请重新登录", "保持未登录", "拒绝访问，保持未登录"),
])
def obligation(request):
    # Deliberately independent of model output and production rules.
    return request.param


def missing_assertions(expected, required):
    return [literal for literal in required if literal not in expected]


def make_candidate(obligation):
    message, effect, omitted = obligation
    base = original()
    base.steps[0].expected = f"提示{message}，{effect}"
    proposed = base.model_copy(deep=True)
    proposed.steps[0].expected = omitted
    return base, RewriteCandidate(
        proposed=proposed, diff=[], reason="Synthetic proposal",
        quality=QualityReport(passed=True, score=100),
    )


def test_saved_omission_is_not_independent_quality_pass(obligation):
    base, candidate = make_candidate(obligation)
    model = SimpleNamespace(name="openai_compatible", complete=Mock(return_value=(
        QualityReport(passed=True, score=100), UsageMetadata(model="fixture"),
    )))
    result = validate_rewrite_candidate(
        RewriteRequest(test_case=base, instruction="补充操作后的提示，不删除原有校验"),
        candidate, model,
    )
    assert missing_assertions(result.proposed.steps[0].expected, obligation[:2]) == [obligation[0]]
    assert result.quality.grounding_status == "unverified"
    assert any(i.code == "manual_review_required" for i in result.quality.issues)
    payload = model.complete.call_args.kwargs["payload"]
    assert payload["original"]["steps"][0]["expected"] == base.steps[0].expected
    assert payload["proposed"]["steps"][0]["expected"] == obligation[2]


def test_reported_independent_omission_blocks_proposal(obligation):
    base, candidate = make_candidate(obligation)
    model = SimpleNamespace(name="openai_compatible", complete=Mock(return_value=(
        QualityReport(passed=False, score=0, issues=[QualityIssue(
            code="assertion_omitted", severity="error", message="Unrequested assertion removal",
        )]), UsageMetadata(model="fixture"),
    )))
    with pytest.raises(RewriteContentError, match="Unrequested assertion removal"):
        validate_rewrite_candidate(
            RewriteRequest(test_case=base, instruction="补充提示，其他预期保留"), candidate, model,
        )
    assert base.steps[0].expected != candidate.proposed.steps[0].expected


def test_explicit_replacement_has_its_own_oracle(obligation):
    base, candidate = make_candidate(obligation)
    candidate.proposed.steps[0].expected = f"提示新的确认文案，{obligation[1]}"
    required_after_approval = ("新的确认文案", obligation[1])
    assert not missing_assertions(candidate.proposed.steps[0].expected, required_after_approval)
    assert missing_assertions(
        candidate.proposed.steps[0].expected, obligation[:2],
    ) == [obligation[0]]
    model = SimpleNamespace(name="openai_compatible", complete=Mock(return_value=(
        QualityReport(passed=True, score=100), UsageMetadata(model="fixture"),
    )))
    validate_rewrite_candidate(RewriteRequest(
        test_case=base, instruction=f"明确将提示{obligation[0]}替换为新的确认文案，其他校验保留",
    ), candidate, model)


def test_historical_assertion_is_quote_evidence_not_generated_expectation():
    quote = "未填写时提示字段必填，不创建记录"
    def complete(stage, instruction, payload, result_type):
        assert stage == "rewrite.evidence"
        assert "不输出测试步骤或预期" not in instruction
        assert "expected" not in payload["test_case"]["steps"][0]
        assert quote in payload["context"]["evidence"][0]["excerpt"]
        return RequirementAnalysis(summary="Synthetic quoted assertion", business_rules=[quote])
    result = rewrite_evidence(
        {"evidence": [{"document_id": "synthetic-history", "excerpt": quote}]},
        {"steps": [{"action": "提交", "expected": "未经核验的旧断言"}]}, complete,
    )
    assert result["business_rules"] == [quote]
    assert result["evidence"][0]["excerpt"] == quote
    assert result["evidence"][0]["document_id"] == "synthetic-history"
