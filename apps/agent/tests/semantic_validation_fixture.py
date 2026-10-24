"""Offline constraint-response fixture, not a production semantic interpreter.

Legacy rule checks supply deterministic verdicts for execution/retry tests.
Live acceptance separately measures actual model interpretation.
"""

from casepilot_agent.contracts import QualityIssue, QualityReport, RewriteCaseDraft, RewriteRequest
from casepilot_agent.rewrite_guards import preservation_error, reference_rewrite_error


def constraint_report(payload):
    request = RewriteRequest(
        test_case=payload["original"],
        instruction=payload["instruction"],
        context=payload.get("context", {}),
    )
    proposed = RewriteCaseDraft.model_validate(payload["proposed"])
    error = preservation_error(request, proposed) or reference_rewrite_error(request, proposed)
    return QualityReport(
        passed=not error,
        score=0 if error else 100,
        issues=[QualityIssue(code="fixture_constraint", message=error)] if error else [],
    )


def point_semantic_checks(payload):
    """Deterministic model response for legacy execution/repair scenarios."""
    from casepilot_agent.compact_generation import (
        CaseContent,
        PointSemanticChecks,
        StageContractError,
        extra_assertion_risks,
        validate_point_literals,
    )
    from casepilot_agent.contracts import TestPoint

    points = {item["slot"]: TestPoint.model_validate(item["point"]) for item in payload["points"]}
    checks = []
    for raw in payload["test_cases"]:
        case = CaseContent.model_validate(raw)
        errors = []
        try:
            validate_point_literals(case, points[case.slot])
        except StageContractError as error:
            errors.append(str(error))
        if any(
            step.expected.strip() in {"正常", "结果正常", "符合预期", "结果符合预期"}
            for step in case.steps
        ):
            errors.append("vague_test_validation")
        checks.append(
            {
                "slot": case.slot,
                "errors": errors,
                "assertion_risks": extra_assertion_risks(case, points[case.slot]),
            }
        )
    return PointSemanticChecks(checks=checks)


def with_point_semantics(executor):
    def execute(stage, instruction, payload, result_type, model_id):
        if stage == "test_case.semantics_checked":
            return point_semantic_checks(payload)
        return executor(stage, instruction, payload, result_type, model_id)

    return execute
