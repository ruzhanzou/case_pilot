import re
from collections.abc import Callable
from typing import Any

from casepilot_agent.contracts import (
    AgentProvider,
    EnhancementResult,
    FeaturePlan,
    GenerationRequest,
    GenerationResult,
    OpenQuestion,
    QualityIssue,
    QualityReport,
    RequirementAnalysis,
    RewriteCandidate,
    RewriteRequest,
    SourceRef,
    StructuredResultT,
    TestCaseBatch,
    TestPointPlan,
)

StageExecutor = Callable[
    [str, str, dict[str, Any], type[StructuredResultT], str],
    StructuredResultT,
]
TEST_OBJECT_QUESTION_ID = "Q-TEST-OBJECT"
UNKNOWN_TEST_OBJECT_TERMS = (
    "不知道",
    "不清楚",
    "不确定",
    "未明确",
    "没有明确",
    "尚未明确",
    "待定",
    "是什么",
    "是哪个",
    "不是明确",
)


def extract_explicit_test_object(content: str) -> str:
    """Extract a user-provided test object without relying on model output."""
    normalized = " ".join(content.strip().split())
    if not normalized or any(term in normalized for term in UNKNOWN_TEST_OBJECT_TERMS):
        return ""

    marker_patterns = (
        r"(?:测试对象|被测对象)\s*(?:是|为|：|:|包括|包含)\s*(.+)",
        r"(?:测试对象|被测对象)\s+(.+)",
    )
    candidate = ""
    for pattern in marker_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1)
            break

    if not candidate:
        generation_patterns = (
            r"(?:为|针对|围绕)\s*(.+?)\s*(?:生成|设计|编写|创建)"
            r"(?:相关)?(?:测试)?用例",
            r"(?:生成|设计|编写|创建)\s*(.+?)\s*(?:测试)?用例",
        )
        for pattern in generation_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1)
                break

    candidate = candidate.strip(" ：:，,。；;“”\"'的")
    embedded_object = re.search(r"\s为\s*(.+)", candidate)
    if embedded_object:
        candidate = embedded_object.group(1).strip()
    candidate = re.sub(
        r"(?:生成|设计|编写|创建)(?:相关)?(?:测试)?用例.*$",
        "",
        candidate,
    )
    candidate = re.sub(r"(?:测试)?用例(?:设计|生成)?$", "", candidate)
    candidate = candidate.strip(" ：:，,。；;“”\"'的")
    if (
        len(candidate) < 2
        or candidate in {"测试", "用例", "功能", "系统", "产品"}
        or any(term in candidate for term in UNKNOWN_TEST_OBJECT_TERMS)
    ):
        return ""
    return candidate[:200]


def enforce_test_object_clarification(
    requirement: RequirementAnalysis,
    answers: dict[str, str] | None = None,
) -> RequirementAnalysis:
    """Only an explicitly missing test object may pause case generation."""
    answered_object = str((answers or {}).get(TEST_OBJECT_QUESTION_ID, "")).strip()
    if answered_object:
        requirement.test_object = answered_object
        requirement.test_object_specified = True

    requirement.test_object = requirement.test_object.strip()
    if requirement.test_object and requirement.test_object_specified:
        requirement.open_questions = []
        return requirement

    requirement.test_object = ""
    requirement.test_object_specified = False
    requirement.open_questions = [
        OpenQuestion(
            id=TEST_OBJECT_QUESTION_ID,
            question="请明确本次需要生成测试用例的测试对象。",
            impact="未指定测试对象，无法确定用例生成范围。",
            blocking=True,
        )
    ]
    return requirement


class AwaitingInput(RuntimeError):
    def __init__(self, requirement: RequirementAnalysis) -> None:
        super().__init__("generation_awaiting_input")
        self.requirement = requirement


class GenerationQualityError(RuntimeError):
    def __init__(self, report: QualityReport, result: GenerationResult) -> None:
        super().__init__("generation_quality_blocked")
        self.report = report
        self.result = result


def validate_generation(result: GenerationResult) -> QualityReport:
    issues: list[QualityIssue] = []
    feature_ids = {item.id for item in result.feature_points}
    point_ids = {item.id for item in result.test_points}
    case_point_ids = {
        point_id for case in result.test_cases for point_id in case.test_point_ids
    }
    if not result.feature_points:
        issues.append(
            QualityIssue(
                code="no_feature_points",
                message="未生成任何功能点",
                severity="error",
            )
        )
    if not result.test_points:
        issues.append(
            QualityIssue(
                code="no_test_points",
                message="未生成任何测试点",
                severity="error",
            )
        )
    if not result.test_cases:
        issues.append(
            QualityIssue(
                code="no_test_cases",
                message="未生成任何测试用例",
                severity="error",
            )
        )
    if len(feature_ids) != len(result.feature_points):
        issues.append(
            QualityIssue(
                code="duplicate_feature_id",
                message="功能点 ID 重复",
                severity="error",
            )
        )
    if len(point_ids) != len(result.test_points):
        issues.append(
            QualityIssue(
                code="duplicate_test_point_id",
                message="测试点 ID 重复",
                severity="error",
            )
        )
    for point in result.test_points:
        if not point.feature_point_ids or not set(point.feature_point_ids) <= feature_ids:
            issues.append(
                QualityIssue(
                    code="invalid_feature_reference",
                    message="测试点引用了不存在的功能点",
                    object_id=point.id,
                    severity="error",
                )
            )
        if point.id not in case_point_ids:
            issues.append(
                QualityIssue(
                    code="uncovered_test_point",
                    message="测试点没有关联用例",
                    object_id=point.id,
                    severity="error",
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
                        message="步骤必须同时包含操作和可观察预期",
                        object_id=case.id,
                        severity="error",
                    )
                )
        if not case.test_point_ids or not set(case.test_point_ids) <= point_ids:
            issues.append(
                QualityIssue(
                    code="invalid_test_point_reference",
                    message="用例引用了不存在的测试点",
                    object_id=case.id,
                    severity="error",
                )
            )
        if not case.source_refs:
            issues.append(
                QualityIssue(
                    code="missing_source_reference",
                    message="用例缺少来源引用，已使用用户输入作为回退来源",
                    object_id=case.id,
                )
            )
    covered_requirements: set[str] = set()
    for row in result.coverage_matrix:
        test_point_refs = (
            row.get("test_point_ids")
            or row.get("test_point_id")
            or row.get("测试点编号")
        )
        requirement_refs = (
            row.get("requirement_ref")
            or row.get("requirement_id")
            or row.get("需求编号")
        )
        if not test_point_refs or not requirement_refs:
            continue
        if isinstance(requirement_refs, list):
            covered_requirements.update(
                str(requirement) for requirement in requirement_refs
            )
        else:
            covered_requirements.add(str(requirement_refs))
    feature_requirements = {
        requirement
        for feature in result.feature_points
        for requirement in feature.requirement_refs
    }
    for requirement in sorted(feature_requirements - covered_requirements):
        issues.append(
            QualityIssue(
                code="requirement_coverage_gap",
                message=f"需求规则 {requirement} 未出现在覆盖矩阵中",
            )
        )
    errors = [issue for issue in issues if issue.severity == "error"]
    return QualityReport(
        passed=not errors,
        score=max(0, 100 - len(errors) * 25 - (len(issues) - len(errors)) * 8),
        issues=issues,
    )


def _merge_by_id(current: list[Any], enhanced: list[Any]) -> list[Any]:
    merged = {item.id: item for item in current}
    merged.update({item.id: item for item in enhanced})
    return list(merged.values())


class GenerationPipeline:
    def __init__(self, provider: AgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        request: GenerationRequest,
        *,
        context: dict[str, Any],
        answers: dict[str, str],
        execute_stage: StageExecutor,
    ) -> GenerationResult:
        common = {
            "prompt": request.prompt,
            "markdown_content": request.markdown_content,
            "file_names": request.file_names,
            "context": context,
            "conversation_memory": request.conversation_memory,
            "answers": answers,
        }
        requirement = execute_stage(
            "requirement.analyzed",
            "先判断用户是否明确指定了测试对象，并填写 test_object 与 "
            "test_object_specified。只有缺少测试对象时才允许提出一个阻塞澄清项；"
            "角色、流程、业务规则、约束、风险等其他内容均由模型结合上下文分析，"
            "必要时写入假设，不得要求用户澄清。结合用户回答消除已解决问题。",
            common,
            RequirementAnalysis,
            request.model_id,
        )
        resolved_answers = dict(answers)
        explicit_test_object = extract_explicit_test_object(request.prompt)
        if explicit_test_object:
            resolved_answers.setdefault(TEST_OBJECT_QUESTION_ID, explicit_test_object)
        requirement = enforce_test_object_clarification(requirement, resolved_answers)
        unresolved = [
            question
            for question in requirement.open_questions
            if question.blocking and question.id not in answers
        ][:3]
        if unresolved:
            requirement.open_questions = unresolved
            raise AwaitingInput(requirement)

        features = execute_stage(
            "feature.generated",
            "基于需求分析生成 2 至 4 个可追溯功能点，每个功能点关联需求编号和证据来源。"
            "描述保持精炼，不重复展开测试步骤。",
            {**common, "requirement": requirement.model_dump(mode="json")},
            FeaturePlan,
            request.model_id,
        )
        point_plan = execute_stage(
            "test_point.generated",
            "规划 6 至 8 个测试点，标明优先级、类型、可执行性。"
            "覆盖矩阵只保留需求、功能点和测试点编号映射，不输出解释性长文。",
            {
                **common,
                "requirement": requirement.model_dump(mode="json"),
                "feature_points": features.model_dump(mode="json"),
            },
            TestPointPlan,
            request.model_id,
        )
        case_batch = execute_stage(
            "test_case.generated",
            "按测试点生成 8 至 10 条可执行用例；每条用例保留 2 至 4 个关键步骤，"
            "步骤必须有明确操作和可观察结果，补充必要前置条件和来源引用，避免重复背景描述。",
            {
                **common,
                "requirement": requirement.model_dump(mode="json"),
                "feature_points": features.model_dump(mode="json"),
                "test_points": point_plan.model_dump(mode="json"),
            },
            TestCaseBatch,
            request.model_id,
        )

        fallback_ref = SourceRef(label="用户输入", excerpt=request.prompt[:400])
        for case in case_batch.test_cases:
            if not case.source_refs:
                case.source_refs = [fallback_ref]
        initial = GenerationResult(
            mode=self.provider.name,
            requirement=requirement,
            feature_points=features.feature_points,
            test_points=point_plan.test_points,
            test_cases=case_batch.test_cases,
            coverage_matrix=point_plan.coverage_matrix,
            source_refs=[
                SourceRef(
                    source_id=item.get("source_id"),
                    document_id=item.get("document_id"),
                    chunk_id=item.get("chunk_id"),
                    label=item.get("label", "知识库"),
                    locator=item.get("locator", ""),
                    excerpt=item.get("excerpt", ""),
                )
                for item in context.get("evidence", [])
            ],
            quality=QualityReport(passed=True, score=100),
        )

        report = validate_generation(initial)
        enhanced = initial
        repair_rounds = 0
        while not report.passed and repair_rounds < 2:
            gaps = [
                issue.model_dump(mode="json")
                for issue in report.issues
                if issue.severity == "error"
            ]
            enhancement = execute_stage(
                "enhancement.completed",
                "只修复质量报告指出的测试点或用例缺口，并定向补充边界、异常、"
                "权限、状态、并发、幂等和历史缺陷场景；不要重做无关内容。",
                {
                    **common,
                    "current": enhanced.model_dump(mode="json"),
                    "quality_gaps": gaps,
                    "round": repair_rounds + 1,
                },
                EnhancementResult,
                request.model_id,
            )
            enhanced.test_points = _merge_by_id(
                enhanced.test_points,
                enhancement.test_points,
            )
            enhanced.test_cases = _merge_by_id(
                enhanced.test_cases,
                enhancement.test_cases,
            )
            repair_rounds += 1
            report = validate_generation(enhanced)

        report.repair_rounds = repair_rounds
        enhanced.quality = report
        if not report.passed:
            raise GenerationQualityError(report, enhanced)
        return enhanced

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate:
        return self.provider.rewrite(request)
