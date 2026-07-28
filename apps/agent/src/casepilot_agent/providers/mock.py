from copy import deepcopy

from casepilot_agent.contracts import (
    FeaturePoint,
    FieldDiff,
    GenerationRequest,
    GenerationResult,
    OpenQuestion,
    Priority,
    QualityReport,
    RequirementAnalysis,
    RewriteCandidate,
    RewriteRequest,
    SourceRef,
    TestCaseDraft,
    TestPoint,
    TestStep,
)


class MockProvider:
    @property
    def name(self) -> str:
        return "mock"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        login = any(keyword in request.prompt for keyword in ("登录", "验证码", "手机号"))
        module = "身份认证" if login else "核心业务"
        feature = FeaturePoint(
            id="FP-001",
            name="手机号验证码登录" if login else "业务请求处理",
            description="用户提交输入后，系统校验规则并返回明确结果。",
            module=module,
            requirement_refs=["REQ-001"],
            source_refs=[SourceRef(label="用户输入", excerpt=request.prompt[:160])],
        )
        points = [
            TestPoint(
                id="TP-001",
                title="主流程验证",
                objective="验证合法输入能够完成业务流程",
                category="功能",
                priority=Priority.P0,
                priority_reason="核心用户路径",
                feature_point_ids=[feature.id],
            ),
            TestPoint(
                id="TP-002",
                title="异常与边界验证",
                objective="验证错误、过期和重复输入不会产生非预期副作用",
                category="异常",
                priority=Priority.P1,
                priority_reason="高频失败路径",
                feature_point_ids=[feature.id],
            ),
        ]
        cases = self._login_cases(points) if login else self._generic_cases(points)
        return GenerationResult(
            mode=self.name,
            requirement=RequirementAnalysis(
                summary=f"围绕“{request.prompt[:80]}”构建可执行测试设计。",
                actors=["终端用户"],
                business_rules=["合法输入成功，非法输入不产生业务副作用"],
                constraints=["生成结果需要人工评审"],
                open_questions=[
                    OpenQuestion(
                        id="Q-001",
                        question="失败重试和限流阈值是否有明确配置？",
                        impact="影响异常及边界用例的精确测试数据",
                    )
                ],
            ),
            feature_points=[feature],
            test_points=points,
            test_cases=cases,
            quality=QualityReport(passed=True, score=100),
            model_metadata={"provider": self.name, "model": request.model_id},
        )

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate:
        proposed = deepcopy(request.test_case)
        before = proposed.model_dump(mode="json")
        changed = False
        if "边界" in request.instruction:
            proposed.preconditions.append("已准备最小值、最大值及越界测试数据")
            proposed.tags = sorted(set([*proposed.tags, "边界"]))
            changed = True
        if "清晰" in request.instruction or "表达" in request.instruction:
            proposed.title = f"{proposed.title}（明确校验结果）"
            changed = True
        if any(keyword in request.instruction for keyword in ("校验点", "增加校验", "补充")):
            gateway_failure = "网关" in request.instruction
            proposed.steps.append(
                TestStep(
                    action=(
                        "模拟短信网关不可用后提交登录请求"
                        if gateway_failure
                        else "执行关键操作后检查业务状态与关联记录"
                    ),
                    expected=(
                        "系统返回明确的服务不可用提示，不创建登录会话，并记录可追踪的失败日志"
                        if gateway_failure
                        else "页面提示、业务状态和关联数据均与预期一致"
                    ),
                )
            )
            changed = True
        if not changed:
            proposed.steps.append(
                TestStep(
                    action="重复执行关键操作并检查关联记录",
                    expected="系统保持幂等，状态和数据均无重复副作用",
                )
            )
        after = proposed.model_dump(mode="json")
        diff = [
            FieldDiff(field=field, before=before[field], after=after[field])
            for field in after
            if before.get(field) != after[field]
        ]
        return RewriteCandidate(
            proposed=proposed,
            diff=diff,
            reason=f"根据“{request.instruction}”生成可评审候选版本。",
            quality=QualityReport(passed=True, score=96),
        )

    def _login_cases(self, points: list[TestPoint]) -> list[TestCaseDraft]:
        return [
            TestCaseDraft(
                id="AUTH-001",
                title="有效验证码登录成功",
                module="身份认证",
                case_type="功能",
                priority=Priority.P0,
                tags=["登录", "主流程"],
                preconditions=["手机号已注册", "验证码在有效期内"],
                steps=[
                    {
                        "action": "输入手机号和有效验证码并提交",
                        "expected": "登录成功且只创建一个有效会话",
                    }
                ],
                test_point_ids=[points[0].id],
            ),
            TestCaseDraft(
                id="AUTH-002",
                title="错误或过期验证码拒绝登录",
                module="身份认证",
                case_type="异常",
                priority=Priority.P1,
                tags=["登录", "异常"],
                preconditions=["手机号已注册"],
                steps=[
                    {
                        "action": "分别提交错误验证码和过期验证码",
                        "expected": "登录失败，原因明确且不创建会话",
                    }
                ],
                test_point_ids=[points[1].id],
            ),
        ]

    def _generic_cases(self, points: list[TestPoint]) -> list[TestCaseDraft]:
        return [
            TestCaseDraft(
                id="CASE-001",
                title="合法输入完成核心业务流程",
                module="核心业务",
                case_type="功能",
                priority=Priority.P0,
                tags=["主流程"],
                preconditions=["服务可用且用户具备操作权限"],
                steps=[
                    {
                        "action": "提交符合业务规则的请求",
                        "expected": "请求成功且业务状态按预期更新",
                    }
                ],
                test_point_ids=[points[0].id],
            ),
            TestCaseDraft(
                id="CASE-002",
                title="重复请求保持幂等",
                module="核心业务",
                case_type="异常",
                priority=Priority.P1,
                tags=["幂等", "异常"],
                preconditions=["首次请求已成功"],
                steps=[
                    {
                        "action": "使用相同业务标识再次提交请求",
                        "expected": "不会产生重复数据或重复副作用",
                    }
                ],
                test_point_ids=[points[1].id],
            ),
        ]
