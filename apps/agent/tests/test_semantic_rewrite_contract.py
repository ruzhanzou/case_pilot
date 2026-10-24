from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from casepilot_agent.contracts import (
    QualityReport,
    RewriteCandidate,
    RewriteRequest,
    UsageMetadata,
)
from casepilot_agent.pipeline import (
    GenerationPipeline,
    RewriteContentError,
    validate_rewrite_candidate,
)
from test_rewrite_preservation import original


def candidate():
    proposed = original().model_copy(update={"title": "模型理解的新标题"}, deep=True)
    return RewriteCandidate(
        proposed=proposed, diff=[], reason="修改标题", quality=QualityReport(passed=True, score=100)
    )


def provider(passed=True):
    return SimpleNamespace(
        name="openai_compatible",
        rewrite=Mock(return_value=candidate()),
        complete=Mock(
            return_value=(QualityReport(passed=passed, score=100), UsageMetadata(model="fixture"))
        ),
    )


def test_exact_assignment_still_uses_model():
    model = provider()
    request = RewriteRequest(test_case=original(), instruction="标题改为「模型理解的新标题」")
    result = GenerationPipeline(model).rewrite(request)
    model.rewrite.assert_called_once()
    model.complete.assert_called_once()
    assert result.proposed.title == "模型理解的新标题"
    assert model.complete.call_args.kwargs["stage"] == "rewrite.constraints_validated"
    assert model.complete.call_args.kwargs["payload"]["instruction"] == request.instruction


def test_semantic_constraint_failure_rejects_candidate():
    with pytest.raises(RewriteContentError):
        validate_rewrite_candidate(
            RewriteRequest(test_case=original(), instruction="保持标题不变"),
            candidate(),
            provider(False),
        )


def test_system_identity_remains_locally_enforced():
    model = provider()
    result = candidate()
    result.proposed.id = "other"
    with pytest.raises(ValueError, match="系统字段"):
        validate_rewrite_candidate(
            RewriteRequest(test_case=original(), instruction="改写"),
            result,
            model,
        )
    model.complete.assert_not_called()


def test_semantic_validation_failure_never_uses_regex_fallback():
    model = provider()
    model.complete.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        validate_rewrite_candidate(
            RewriteRequest(test_case=original(), instruction="标题改为新标题"),
            candidate(),
            model,
        )
