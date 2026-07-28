from collections.abc import Callable

from casepilot_agent.contracts import (
    AgentProvider,
    GenerationRequest,
    GenerationResult,
    QualityIssue,
    QualityReport,
    RewriteCandidate,
    RewriteRequest,
)

ProgressCallback = Callable[[str, int, dict], None]

STAGES = (
    "requirement.analyzed",
    "feature.generated",
    "test_point.generated",
    "test_case.generated",
    "quality.completed",
)


def validate_generation(result: GenerationResult) -> QualityReport:
    issues: list[QualityIssue] = []
    feature_ids = {item.id for item in result.feature_points}
    point_ids = {item.id for item in result.test_points}
    if len(feature_ids) != len(result.feature_points):
        issues.append(QualityIssue(code="duplicate_feature_id", message="功能点 ID 重复"))
    if len(point_ids) != len(result.test_points):
        issues.append(QualityIssue(code="duplicate_test_point_id", message="测试点 ID 重复"))
    for point in result.test_points:
        if not set(point.feature_point_ids) <= feature_ids:
            issues.append(
                QualityIssue(
                    code="invalid_feature_reference",
                    message="测试点引用了不存在的功能点",
                    object_id=point.id,
                )
            )
    seen_titles: set[str] = set()
    for case in result.test_cases:
        normalized = case.title.strip().lower()
        if normalized in seen_titles:
            issues.append(
                QualityIssue(
                    code="duplicate_case",
                    message="存在重复用例标题",
                    object_id=case.id,
                )
            )
        seen_titles.add(normalized)
        if not case.steps:
            issues.append(
                QualityIssue(
                    code="empty_steps",
                    message="用例没有执行步骤",
                    object_id=case.id,
                    severity="error",
                )
            )
        for step in case.steps:
            if not step.action.strip() or not step.expected.strip():
                issues.append(
                    QualityIssue(
                        code="invalid_step",
                        message="步骤必须同时包含操作和预期",
                        object_id=case.id,
                        severity="error",
                    )
                )
        if not set(case.test_point_ids) <= point_ids:
            issues.append(
                QualityIssue(
                    code="invalid_test_point_reference",
                    message="用例引用了不存在的测试点",
                    object_id=case.id,
                )
            )
    errors = [issue for issue in issues if issue.severity == "error"]
    return QualityReport(
        passed=not errors,
        score=max(0, 100 - len(errors) * 25 - (len(issues) - len(errors)) * 8),
        issues=issues,
    )


class GenerationPipeline:
    def __init__(self, provider: AgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        request: GenerationRequest,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        result = self.provider.generate(request)
        report = validate_generation(result)
        previous_snapshot = result.model_dump_json(exclude={"quality"})
        repair_rounds = 0
        while not report.passed and repair_rounds < 2:
            issue_summary = "; ".join(
                f"{issue.code}:{issue.object_id or 'global'}" for issue in report.issues
            )
            repair_request = request.model_copy(
                update={
                    "prompt": (
                        f"{request.prompt[:7000]}\n"
                        "请修复上一轮结构化结果中的以下校验问题，并重新返回完整结果："
                        f"{issue_summary}"
                    )
                }
            )
            repaired = self.provider.generate(repair_request)
            current_snapshot = repaired.model_dump_json(exclude={"quality"})
            repair_rounds += 1
            result = repaired
            report = validate_generation(result)
            if current_snapshot == previous_snapshot:
                break
            previous_snapshot = current_snapshot
        report.repair_rounds = repair_rounds
        result.quality = report
        if on_progress:
            payloads = (
                {"open_questions": len(result.requirement.open_questions)},
                {"feature_count": len(result.feature_points)},
                {"test_point_count": len(result.test_points)},
                {"test_case_count": len(result.test_cases)},
                {"quality": result.quality.model_dump(mode="json")},
            )
            for sequence, (stage, payload) in enumerate(
                zip(STAGES, payloads, strict=True),
                start=1,
            ):
                on_progress(stage, sequence, payload)
        return result

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate:
        return self.provider.rewrite(request)
