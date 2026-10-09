import re
from collections.abc import Callable
from typing import Any

from casepilot_agent.contracts import (
    AgentProvider,
    EnhancementResult,
    FeaturePlan,
    FieldDiff,
    GenerationRequest,
    GenerationResult,
    OpenQuestion,
    QualityIssue,
    QualityReport,
    RequirementAnalysis,
    RewriteCandidate,
    RewriteCaseDraft,
    RewriteRequest,
    SourceRef,
    StructuredResultT,
    TestCaseBatch,
    TestPointPlan,
)
from casepilot_agent.planning import planned_module

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


def _explicit_rewrite_candidate(
    request: RewriteRequest,
) -> RewriteCandidate | None:
    """Apply exact field assignments locally; leave semantic rewrites to the model."""
    instruction = " ".join(request.instruction.strip().split())
    if re.search(r"不要|无需|禁止|勿|不(?:修改|改写|改动|调整|改变)", instruction):
        return None
    unsupported_fields = ("前置条件", "执行步骤", "操作步骤", "标签", "自动化", "来源")
    if any(field in instruction for field in unsupported_fields):
        return None

    assignment_spans: list[tuple[int, int]] = []

    def quoted_value(field_pattern: str) -> str:
        match = re.search(
            rf"(?:{field_pattern})\s*(?:统一|全部)?\s*"
            r"(?:改为|改成|修改为|调整为|设置为|设为|替换为|更新为|补充为|为|是|[:：])\s*"
            r"[「“\"]([^」”\"]+)[」”\"]",
            instruction,
            flags=re.IGNORECASE,
        )
        if match:
            assignment_spans.append(match.span())
        return match.group(1).strip() if match else ""

    mentioned = {
        "title": any(field in instruction for field in ("用例名称", "名称", "标题")),
        "module": any(field in instruction for field in ("所属模块", "模块")),
        "case_type": any(field in instruction for field in ("用例类型", "类型")),
        "priority": "优先级" in instruction,
        "expected": any(field in instruction for field in ("预期结果", "校验点")),
    }
    values = {
        "title": quoted_value(r"用例名称|名称|标题"),
        "module": quoted_value(r"所属模块|模块"),
        "case_type": quoted_value(r"用例类型|类型"),
        "expected": quoted_value(r"预期结果|校验点"),
    }
    priority_match = re.search(
        r"优先级\s*(?:统一|全部)?\s*(?:改为|改成|修改为|调整为|设置为|设为|为|[:：])\s*(P[012])\b",
        instruction,
        re.I,
    )
    values["priority"] = priority_match.group(1).upper() if priority_match else ""

    if not any(values.values()):
        return None
    if any(mentioned[field] and not values[field] for field in mentioned):
        return None

    if priority_match:
        assignment_spans.append(priority_match.span())
    # Only complete assignment commands qualify. Anything left that asks for
    # semantic work must reach the provider rather than silently disappear.
    remainder = instruction
    for start, end in sorted(assignment_spans, reverse=True):
        remainder = remainder[:start] + remainder[end:]
    if not re.fullmatch(
        r"[\s，,。；;、]*(?:请)?(?:仅|只)?(?:把|将)?(?:当前|这个|选中|所选)?(?:的)?"
        r"(?:用例(?:\s+[A-Za-z0-9_-]+)?)?(?:的)?[\s，,。；;、]*"
        r"(?:(?:并|和|及|同时)(?:把|将)?[\s，,。；;、]*)*"
        r"(?:其他字段保持不变[\s，,。；;、]*)?",
        remainder,
    ):
        return None

    proposed = request.test_case.model_copy(deep=True)
    before = proposed.model_dump(mode="json")
    if values["title"]:
        proposed.title = values["title"][:300]
    if values["module"]:
        proposed.module = values["module"]
    if values["case_type"]:
        proposed.case_type = values["case_type"]
    if values["priority"]:
        proposed.priority = values["priority"]  # type: ignore[assignment]
    if values["expected"]:
        proposed.steps[-1].expected = values["expected"][:4000]

    after = proposed.model_dump(mode="json")
    diff = [
        FieldDiff(field=field, before=before[field], after=after[field])
        for field in after
        if before.get(field) != after[field]
    ]
    return RewriteCandidate(
        proposed=proposed,
        diff=diff,
        reason="按明确的字段赋值指令生成快速候选。",
        quality=QualityReport(passed=True, score=100),
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
    case_point_ids = {point_id for case in result.test_cases for point_id in case.test_point_ids}
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
    if len({case.id for case in result.test_cases}) != len(result.test_cases):
        issues.append(
            QualityIssue(
                code="duplicate_case_id",
                message="用例 ID 重复",
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
                    severity="error",
                )
            )
        seen_titles.add(normalized)
        if not case.preconditions or not any(item.strip() for item in case.preconditions):
            issues.append(
                QualityIssue(
                    code="empty_test_setup",
                    message="test_setup 不能为空；无特殊前置条件时必须明确声明",
                    object_id=case.id,
                    severity="error",
                )
            )
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
            if step.expected.strip() in {
                "正常",
                "结果正常",
                "符合预期",
                "结果符合预期",
            }:
                issues.append(
                    QualityIssue(
                        code="vague_test_validation",
                        message="test_validation 必须给出可观察、可判定的具体结果",
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
            row.get("test_point_ids") or row.get("test_point_id") or row.get("测试点编号")
        )
        requirement_refs = (
            row.get("requirement_ref") or row.get("requirement_id") or row.get("需求编号")
        )
        if not test_point_refs or not requirement_refs:
            continue
        if isinstance(requirement_refs, list):
            covered_requirements.update(str(requirement) for requirement in requirement_refs)
        else:
            covered_requirements.add(str(requirement_refs))
    feature_requirements = {
        requirement for feature in result.feature_points for requirement in feature.requirement_refs
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


def requested_case_count(request: GenerationRequest) -> int | None:
    """Only explicit case quantities count; business thresholds are not quantities."""
    texts = (request.prompt, request.markdown_content)
    # A total takes precedence over a per-module quantity in a summarized brief.
    patterns = (
        r"(?:总计|共计|合计|总共|共)\s*([1-9]\d{0,3})\s*条",
        r"(?:生成|编写|设计|创建|新增|增加|补充|恰好)[^。；;\n]{0,24}?"
        r"(?<!\d)([1-9]\d{0,3})\s*条\s*(?:新(?:的)?\s*)?(?:候选\s*)?(?:测试)?用例",
    )
    for text in texts:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                count = int(match.group(1))
                if count > 500:
                    raise ValueError("单次生成最多支持500条用例，请缩小范围后重试")
                return count
    return None


def rebase_rewrite_candidate(
    base: RewriteCaseDraft, candidate: RewriteCandidate
) -> RewriteCandidate:
    """Review cumulative changes against persisted data, including prior draft edits."""
    before, after = base.model_dump(mode="json"), candidate.proposed.model_dump(mode="json")
    fields = (
        "title",
        "module",
        "priority",
        "case_type",
        "tags",
        "preconditions",
        "steps",
        "source_refs",
    )
    return candidate.model_copy(
        update={
            "diff": [
                FieldDiff(field=field, before=before[field], after=after[field])
                for field in fields
                if before.get(field) != after.get(field)
            ]
        }
    )


class GenerationPipeline:
    def __init__(self, provider: AgentProvider) -> None:
        self.provider = provider

    def run_planned(self, request: GenerationRequest, execute_stage: StageExecutor):
        plan = request.confirmed_plan
        features = FeaturePlan.model_validate(plan).feature_points
        points = TestPointPlan.model_validate(plan).test_points
        if not points:
            raise ValueError("planning_has_no_test_points")
        requirement = RequirementAnalysis(
            test_object=request.prompt,
            test_object_specified=True,
            summary=request.markdown_content or request.prompt,
        )
        generated = []
        count = requested_case_count(request)
        limit = count or len(points)
        for index in range(limit):
            point = points[index % len(points)]
            feature_ids = set(point.feature_point_ids)
            selected_features = [item for item in features if item.id in feature_ids]
            refs = {ref.chunk_id for ref in point.source_refs}
            if not refs:
                for feature in selected_features:
                    refs.update(ref.chunk_id for ref in feature.source_refs)
            evidence = [item for item in plan.get("evidence", []) if item.get("chunk_id") in refs]
            # Source excerpts on the plan remain available even if originals have expired.
            batch = execute_stage(
                "test_case.generated",
                "只为给定测试点生成1条可执行用例，不重新规划或扩大范围。"
                "使用batch_start_index唯一编号，避免重复previous_titles。"
                "保留规则的数值与例外；操作与预期一一对应，提供具体可观察断言。",
                {
                    "prompt": request.prompt,
                    "test_points": {"test_points": [point.model_dump(mode="json")]},
                    "feature_points": {
                        "feature_points": [f.model_dump(mode="json") for f in selected_features]
                    },
                    "context": {"evidence": evidence},
                    "batch_count": 1,
                    "batch_start_index": index + 1,
                    "brief_version": plan.get("brief_version"),
                    "previous_titles": [case.title for case in generated],
                },
                TestCaseBatch,
                request.model_id,
            )
            if len(batch.test_cases) != 1:
                raise ValueError("规划生成每批应返回1条用例，请重试")
            case = batch.test_cases[0]
            case.id = f"TC-{point.id}-{index // len(points) + 1}"
            case.test_point_ids = [point.id]
            case.module = planned_module(point, features)
            if not case.source_refs:
                case.source_refs = point.source_refs or [
                    SourceRef(label="用户输入", excerpt=request.prompt)
                ]
            generated.append(case)
        result = GenerationResult(
            mode=self.provider.name,
            requirement=requirement,
            feature_points=features,
            test_points=points,
            test_cases=generated,
            coverage_matrix=[],
            quality=QualityReport(passed=True, score=100),
        )
        result.quality = validate_generation(result)
        if count and count < len(points):
            for issue in result.quality.issues:
                if issue.code == "uncovered_test_point":
                    issue.code = "planned_point_uncovered"
                    issue.severity = "warning"
                    issue.message = "数量预算内尚未生成此测试点"
        errors = sum(item.severity == "error" for item in result.quality.issues)
        warnings = len(result.quality.issues) - errors
        result.quality.passed = errors == 0
        result.quality.score = max(0, 100 - errors * 25 - warnings * 8)
        return result

    def run(
        self,
        request: GenerationRequest,
        *,
        context: dict[str, Any],
        answers: dict[str, str],
        execute_stage: StageExecutor,
    ) -> GenerationResult:
        if request.confirmed_plan:
            return self.run_planned(request, execute_stage)
        requested_count = requested_case_count(request)
        common = {
            "requested_case_count": requested_count,
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
            "基于需求分析生成可追溯功能点，覆盖用户指定的全部模块，不得合并或遗漏模块。"
            "每个用户指定的顶层模块只生成1个功能点，将其子规则放入描述，不要拆成多个模块。"
            "未指定模块时生成 2 至 4 个功能点。每个功能点关联需求编号和证据来源。"
            "描述保持精炼，不重复展开测试步骤。",
            {**common, "requirement": requirement.model_dump(mode="json"), "feature_scope_policy": "one_per_requested_module"},
            FeaturePlan,
            request.model_id,
        )
        point_groups = (
            [[feature] for feature in features.feature_points]
            if requested_count and requested_count > 10
            else [features.feature_points]
        )
        all_points = []
        coverage_matrix = []
        for group_index, group in enumerate(point_groups):
            planned = execute_stage(
                "test_point.generated",
                (
                    f"只为本批 feature_points 规划共不超过{requested_count}个测试点，"
                    "优先覆盖用户明确指定的场景，不自动增加范围外的边界或异常场景。"
                    if requested_count and requested_count <= 10
                    else "只为本批 feature_points 规划测试点；每个功能点恰好3个：正常、异常、边界。"
                )
                + "标明优先级、类型、可执行性，每个测试点使用 point_id_prefix 开头的唯一ID。"
                "覆盖矩阵只保留需求、功能点和测试点编号映射，不输出解释性长文。"
                "final_case_count是最终用例总量，不是本批测试点数量；严格遵守max_test_points和allowed_feature_ids，不重规划其他功能点。",
                {
                    **common,
                    "requirement": requirement.model_dump(mode="json"),
                    "feature_points": FeaturePlan(feature_points=group).model_dump(mode="json"),
                    "point_id_prefix": f"TP-{group_index + 1}-",
                    "requested_case_count": None,
                    "final_case_count": requested_count,
                    "max_test_points": requested_count if requested_count and requested_count <= 10 else 3 * len(group),
                    "allowed_feature_ids": [feature.id for feature in group],
                },
                TestPointPlan,
                request.model_id,
            )
            all_points.extend(planned.test_points)
            coverage_matrix.extend(planned.coverage_matrix)
        point_plan = TestPointPlan(test_points=all_points, coverage_matrix=coverage_matrix)
        generated_cases = []
        batch_total = (requested_count + 9) // 10 if requested_count else 1
        for batch_index in range(batch_total):
            batch_count = (
                min(10, requested_count - len(generated_cases)) if requested_count else None
            )
            quantity = f"恰好 {batch_count} 条" if batch_count else "8 至 10 条"
            # Small responses avoid truncation; all batches belong to one generation job.
            feature = (
                features.feature_points[batch_index]
                if batch_total == len(features.feature_points)
                else None
            )
            case_batch = execute_stage(
                "test_case.generated",
                f"本批只生成{quantity}可执行候选用例，不要一次生成全量。"
                "遵从 batch_scope（若非空），只覆盖该功能点所属模块。"
                "用例ID全局唯一，按 batch_start_index 连续编号，"
                "不重复 previous_titles 中的测试目标。"
                "严格遵循四段式用例规范：title 是单一测试目标；"
                "preconditions 是环境、状态、身份、权限和测试数据前提；"
                "steps 保留 1 至 4 个按序操作，action 不混入预期，"
                "expected 为同序可观察且可判定断言。"
                "补充来源引用，避免‘正常’‘符合预期’等模糊表达。",
                {
                    **common,
                    "requirement": requirement.model_dump(mode="json"),
                    "feature_points": features.model_dump(mode="json"),
                    "test_points": point_plan.model_dump(mode="json"),
                    "batch_count": batch_count,
                    "batch_start_index": len(generated_cases) + 1,
                    "batch_scope": feature.model_dump(mode="json") if feature else None,
                    "previous_titles": [case.title for case in generated_cases],
                },
                TestCaseBatch,
                request.model_id,
            )
            if batch_count and len(case_batch.test_cases) != batch_count:
                raise ValueError(
                    f"候选数量不符：本批需要{batch_count}条，"
                    f"实际返回{len(case_batch.test_cases)}条，请重试"
                )
            generated_cases.extend(case_batch.test_cases)
        case_batch = TestCaseBatch(test_cases=generated_cases)

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
            affected_ids = {str(item["object_id"]) for item in gaps if item.get("object_id")}
            enhancement = execute_stage(
                "enhancement.completed",
                "只返回质量报告要求新增或修改的对象，不得复制无关对象。可新增功能点"
                "修复引用缺口；除整类对象缺失外，每类最多返回 3 项。定向修复边界、"
                "异常、权限、状态、并发、幂等和历史缺陷场景。"
                "如果requested_case_count有值，必须保持用例总数不变，复用现有用例ID，"
                "通过完善现有用例及测试点关联修复覆盖缺口，不得新增用例。",
                {
                    "prompt": request.prompt,
                    "requested_case_count": requested_count,
                    "requirement": enhanced.requirement.model_dump(mode="json"),
                    "current_inventory": {
                        "feature_points": [
                            {
                                "id": item.id,
                                "name": item.name,
                                "module": item.module,
                                "requirement_refs": item.requirement_refs,
                            }
                            for item in enhanced.feature_points
                        ],
                        "test_points": [
                            {
                                "id": item.id,
                                "title": item.title,
                                "feature_point_ids": item.feature_point_ids,
                            }
                            for item in enhanced.test_points
                        ],
                        "test_cases": [
                            {
                                "id": item.id,
                                "title": item.title,
                                "test_point_ids": item.test_point_ids,
                            }
                            for item in enhanced.test_cases
                        ],
                    },
                    "affected_objects": {
                        "test_points": [
                            item.model_dump(mode="json")
                            for item in enhanced.test_points
                            if item.id in affected_ids
                        ],
                        "test_cases": [
                            item.model_dump(mode="json")
                            for item in enhanced.test_cases
                            if item.id in affected_ids
                        ],
                    },
                    "quality_gaps": gaps,
                    "round": repair_rounds + 1,
                },
                EnhancementResult,
                request.model_id,
            )
            enhanced.feature_points = _merge_by_id(
                enhanced.feature_points,
                enhancement.feature_points,
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

        if requested_count and len(enhanced.test_cases) != requested_count:
            report.issues.append(
                QualityIssue(
                    code="case_count_mismatch",
                    severity="error",
                    message=f"需要{requested_count}条用例，实际{len(enhanced.test_cases)}条",
                )
            )
            report.passed = False
        report.repair_rounds = repair_rounds
        enhanced.quality = report
        if not report.passed:
            raise GenerationQualityError(report, enhanced)
        return enhanced

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate:
        explicit = _explicit_rewrite_candidate(request)
        if explicit is not None:
            return explicit
        if request.context:
            request = request.model_copy(update={"instruction": request.instruction +
                "\n结合context中的任务资料，只修改当前用例受影响的字段。"
                "规则不相关时保持原内容；资料冲突写入质量问题，不擅自选择版本。"
                "保留具体数值、条件与来源，不扩大修改范围。"})
        return self.provider.rewrite(request)
