from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
from math import sqrt
from time import sleep
from typing import Any

from casepilot_agent.contracts import (
    EMBEDDING_DIMENSIONS,
    EnhancementResult,
    FeaturePlan,
    FeaturePoint,
    FieldDiff,
    GenerationRequest,
    GenerationResult,
    KnowledgeAnswer,
    OpenQuestion,
    Priority,
    QualityReport,
    RequirementAnalysis,
    RewriteCandidate,
    RewriteRequest,
    SourceRef,
    StructuredResultT,
    TestCaseBatch,
    TestCaseDraft,
    TestPoint,
    TestPointPlan,
    TestStep,
    UsageMetadata,
)


class MockProvider:
    dimensions = EMBEDDING_DIMENSIONS

    @property
    def name(self) -> str:
        return "mock"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        login = any(keyword in request.prompt for keyword in ("登录", "验证码", "手机号"))
        voice_call = any(
            keyword in request.prompt
            for keyword in ("豆包", "实时语音", "语音通话", "双向流式")
        )
        if voice_call:
            features, points, cases = self._voice_call_design(request.prompt)
            actors = ["终端用户", "豆包语音助手", "移动操作系统"]
            business_rules = [
                "同一用户操作只创建一个实时语音会话",
                "用户插话必须停止当前播报并切回聆听",
                "异常结束必须释放麦克风、音频焦点和网络会话",
            ]
            constraints = [
                "首包音频不超过 800ms，端到端语音响应不超过 1500ms",
                "弱网重连不超过 3s，且不能重复播放或丢失用户确认",
                "生成结果需要人工评审",
            ]
            open_questions = [
                OpenQuestion(
                    id="Q-VOICE-001",
                    question="锁屏和切后台后是否允许继续保持实时语音通话？",
                    impact="影响系统中断、隐私提示和后台保活的预期结果",
                )
            ]
        else:
            module = "身份认证" if login else "核心业务"
            feature = FeaturePoint(
                id="FP-001",
                name="手机号验证码登录" if login else "业务请求处理",
                description="用户提交输入后，系统校验规则并返回明确结果。",
                module=module,
                requirement_refs=["REQ-001"],
                source_refs=[SourceRef(label="用户输入", excerpt=request.prompt[:160])],
            )
            features = [feature]
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
            actors = ["终端用户"]
            business_rules = ["合法输入成功，非法输入不产生业务副作用"]
            constraints = ["生成结果需要人工评审"]
            open_questions = [
                OpenQuestion(
                    id="Q-001",
                    question="失败重试和限流阈值是否有明确配置？",
                    impact="影响异常及边界用例的精确测试数据",
                )
            ]
        return GenerationResult(
            mode=self.name,
            requirement=RequirementAnalysis(
                test_object=(
                    "豆包 App 实时语音通话"
                    if voice_call
                    else "手机号验证码登录"
                    if login
                    else (
                        ""
                        if request.prompt.strip()
                        in {"生成测试用例", "请生成测试用例", "帮我生成测试用例"}
                        else request.prompt.strip()[:120]
                    )
                ),
                test_object_specified=(
                    request.prompt.strip()
                    not in {"生成测试用例", "请生成测试用例", "帮我生成测试用例"}
                ),
                summary=f"围绕“{request.prompt[:80]}”构建可执行测试设计。",
                actors=actors,
                business_rules=business_rules,
                constraints=constraints,
                open_questions=open_questions,
            ),
            feature_points=features,
            test_points=points,
            test_cases=cases,
            quality=QualityReport(passed=True, score=100),
            model_metadata={"provider": self.name, "model": request.model_id},
        )

    def complete(
        self,
        *,
        stage: str,
        instruction: str,
        payload: dict[str, Any],
        result_type: type[StructuredResultT],
        model_id: str,
    ) -> tuple[StructuredResultT, UsageMetadata]:
        del instruction
        prompt = str(payload.get("prompt", "核心业务需求"))
        if "取消竞争" in prompt:
            sleep(0.12)
        markdown = str(payload.get("markdown_content", ""))
        request = GenerationRequest(
            prompt=prompt,
            markdown_content=markdown,
            conversation_memory=list(payload.get("conversation_memory", [])),
            model_id=model_id,
        )
        baseline = self.generate(request)
        evidence = payload.get("context", {}).get("evidence", [])
        if evidence:
            first = evidence[0]
            source_ref = SourceRef(
                source_id=first.get("source_id"),
                document_id=first.get("document_id"),
                chunk_id=first.get("chunk_id"),
                label=first.get("label", "知识库"),
                locator=first.get("locator", ""),
                excerpt=first.get("excerpt", "")[:400],
            )
            for feature in baseline.feature_points:
                feature.source_refs = [source_ref]
            for point in baseline.test_points:
                point.source_refs = [source_ref]
            for case in baseline.test_cases:
                case.source_refs = [source_ref]

        if result_type is RequirementAnalysis:
            requirement = baseline.requirement
            current_test_brief = payload.get("current_test_brief")
            if isinstance(current_test_brief, dict):
                requirement = RequirementAnalysis(
                    test_object=str(current_test_brief.get("test_object", "")),
                    test_object_specified=bool(
                        str(current_test_brief.get("test_object", "")).strip()
                    ),
                    summary=str(
                        current_test_brief.get("test_objective")
                        or requirement.summary
                    ),
                    actors=[
                        str(item)
                        for item in current_test_brief.get("roles", [])
                    ],
                    flows=[
                        str(item)
                        for item in (
                            current_test_brief.get("core_flows")
                            or current_test_brief.get("scope", [])
                        )
                    ],
                    business_rules=[
                        str(item)
                        for item in current_test_brief.get(
                            "business_rules", []
                        )
                    ],
                    constraints=[
                        str(item)
                        for item in current_test_brief.get("constraints", [])
                    ],
                    risks=[
                        str(item)
                        for item in current_test_brief.get("risks", [])
                    ],
                    assumptions=[
                        str(item)
                        for item in current_test_brief.get("assumptions", [])
                    ],
                    open_questions=[
                        OpenQuestion.model_validate(item)
                        for item in current_test_brief.get(
                            "open_questions", []
                        )
                        if isinstance(item, dict)
                    ],
                )
            if "锁屏" in prompt and "切后台" in prompt and "允许" in prompt:
                rule = "锁屏和切后台后允许继续保持实时语音通话"
                if rule not in requirement.business_rules:
                    requirement.business_rules.append(rule)
                requirement.open_questions = [
                    item
                    for item in requirement.open_questions
                    if "锁屏" not in item.question and "切后台" not in item.question
                ]
            if "目标角色" in prompt and "成功标准" in prompt:
                requirement.open_questions = [
                    item
                    for item in requirement.open_questions
                    if not (
                        "角色" in item.question
                        or "成功判定" in item.question
                        or "成功标准" in item.question
                    )
                ]
            answers = payload.get("answers", {})
            answered_object = str(answers.get("Q-TEST-OBJECT", "")).strip()
            if answered_object:
                requirement.test_object = answered_object
                requirement.test_object_specified = True
            result: Any = requirement
        elif result_type is FeaturePlan:
            result = FeaturePlan(feature_points=baseline.feature_points)
        elif result_type is TestPointPlan:
            result = TestPointPlan(
                test_points=baseline.test_points,
                coverage_matrix=[
                    {
                        "requirement_ref": "REQ-001",
                        "feature_point_ids": ["FP-001"],
                        "test_point_ids": [point.id for point in baseline.test_points],
                    }
                ],
            )
        elif result_type is TestCaseBatch:
            result = TestCaseBatch(test_cases=baseline.test_cases)
        elif result_type is EnhancementResult:
            result = EnhancementResult(
                test_points=baseline.test_points,
                test_cases=baseline.test_cases,
                enhanced_dimensions=["边界", "异常", "幂等"],
            )
        elif result_type is KnowledgeAnswer:
            if evidence:
                result = KnowledgeAnswer(
                    answer=(
                        f"根据“{evidence[0].get('label', '当前资料')}”中的内容，"
                        f"{evidence[0].get('excerpt', '')[:240]}"
                    ),
                    citations=[
                        SourceRef(
                            source_id=evidence[0].get("source_id"),
                            document_id=evidence[0].get("document_id"),
                            chunk_id=evidence[0].get("chunk_id"),
                            label=evidence[0].get("label", "当前资料"),
                            locator=evidence[0].get("locator", ""),
                            excerpt=evidence[0].get("excerpt", "")[:400],
                        )
                    ],
                )
            elif payload.get("case_context"):
                first_case = payload["case_context"][0].get("snapshot", {})
                result = KnowledgeAnswer(
                    answer=(
                        f"当前用例“{first_case.get('title', '未命名用例')}”"
                        f"的优先级为 {first_case.get('priority', '未设置')}，"
                        f"包含 {len(first_case.get('steps', []))} 个执行步骤。"
                    ),
                    citations=[
                        SourceRef(
                            label=str(
                                first_case.get("case_key")
                                or first_case.get("id")
                                or "当前用例"
                            ),
                            excerpt=str(first_case.get("title", "")),
                        )
                    ],
                )
            else:
                result = KnowledgeAnswer(
                    answer=(
                        "当前资料中没有检索到直接依据。建议补充需求文档，"
                        "或明确要查询的用例与业务规则。"
                    )
                )
        else:
            result = result_type.model_validate(payload)
        return result, UsageMetadata(
            model=f"mock:{model_id}",
            latency_ms=1,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    def complete_text_stream(
        self,
        *,
        stage: str,
        instruction: str,
        payload: dict[str, Any],
        model_id: str,
        on_delta: Callable[[str], None],
    ) -> tuple[str, UsageMetadata]:
        result, usage = self.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=KnowledgeAnswer,
            model_id=model_id,
        )
        for start in range(0, len(result.answer), 12):
            on_delta(result.answer[start : start + 12])
        return result.answer, usage

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            digest = sha256(text.encode("utf-8")).digest()
            for index, value in enumerate(digest):
                vector[(index * 47 + value) % len(vector)] += (value - 127.5) / 127.5
            norm = sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

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

    def _voice_call_design(
        self, prompt: str
    ) -> tuple[list[FeaturePoint], list[TestPoint], list[TestCaseDraft]]:
        source_refs = [SourceRef(label="用户输入", excerpt=prompt[:400])]
        features = [
            FeaturePoint(
                id="VOICE-FP-001",
                name="通话建立与双向实时交互",
                description="建立低延迟语音会话，持续呈现聆听、思考和回答状态，并支持用户插话。",
                module="实时语音通话",
                requirement_refs=["VOICE-REQ-001"],
                source_refs=source_refs,
            ),
            FeaturePoint(
                id="VOICE-FP-002",
                name="音频路由、中断恢复与资源释放",
                description="在弱网、系统中断和设备路由变化下保持状态一致，并在结束后释放资源。",
                module="实时语音通话",
                requirement_refs=["VOICE-REQ-002"],
                source_refs=source_refs,
            ),
        ]
        points = [
            TestPoint(
                id="VOICE-TP-001",
                title="通话建立与时延",
                objective="验证授权后只建立一个会话，并满足首包与端到端时延阈值",
                category="功能与性能",
                priority=Priority.P0,
                priority_reason="实时语音的核心成功路径",
                feature_point_ids=[features[0].id],
            ),
            TestPoint(
                id="VOICE-TP-002",
                title="权限与隐私",
                objective="验证麦克风授权、拒绝、撤销与隐私提示行为",
                category="权限",
                priority=Priority.P0,
                priority_reason="麦克风是敏感权限且会直接阻断通话",
                feature_point_ids=[features[0].id],
            ),
            TestPoint(
                id="VOICE-TP-003",
                title="插话和音频路由",
                objective="验证播报可被打断，听筒、扬声器、蓝牙和耳机切换连续可用",
                category="交互与兼容性",
                priority=Priority.P0,
                priority_reason="影响实时对话自然度与多设备可用性",
                feature_point_ids=[features[0].id, features[1].id],
            ),
            TestPoint(
                id="VOICE-TP-004",
                title="异常中断与恢复",
                objective="验证弱网、断网、来电、切后台和锁屏时状态可恢复且资源不泄漏",
                category="稳定性",
                priority=Priority.P0,
                priority_reason="高频移动端异常路径",
                feature_point_ids=[features[1].id],
            ),
        ]
        cases = [
            TestCaseDraft(
                id="VOICE-001",
                title="授权后建立实时语音通话并满足时延阈值",
                module="通话建立",
                case_type="功能",
                priority=Priority.P0,
                tags=["豆包", "实时语音", "主流程", "性能"],
                preconditions=["用户已登录豆包 App", "网络稳定", "麦克风权限未被禁用"],
                steps=[
                    {
                        "action": "点击实时语音通话入口并允许麦克风权限",
                        "expected": "只创建一个会话，界面进入聆听状态且系统显示麦克风使用提示",
                    },
                    {
                        "action": "说出一条可回答的问题并记录时间戳",
                        "expected": (
                            "首包音频不超过 800ms，端到端响应不超过 1500ms，"
                            "状态依次为聆听、思考、回答"
                        ),
                    },
                ],
                test_point_ids=[points[0].id],
            ),
            TestCaseDraft(
                id="VOICE-002",
                title="麦克风权限拒绝或撤销时阻止采集并提供恢复入口",
                module="权限与隐私",
                case_type="权限",
                priority=Priority.P0,
                tags=["豆包", "麦克风", "权限", "隐私"],
                preconditions=["用户已登录", "系统允许修改豆包麦克风权限"],
                steps=[
                    {
                        "action": "首次进入时拒绝麦克风权限",
                        "expected": (
                            "不建立通话、不上传音频，页面说明原因并提供前往系统设置的恢复入口"
                        ),
                    },
                    {
                        "action": "通话中从系统设置撤销麦克风权限后返回豆包",
                        "expected": "采集立即停止，会话安全结束且不会继续显示聆听中",
                    },
                ],
                test_point_ids=[points[1].id],
            ),
            TestCaseDraft(
                id="VOICE-003",
                title="用户插话时立即停止当前播报并切回聆听",
                module="实时交互",
                case_type="交互",
                priority=Priority.P0,
                tags=["豆包", "Barge-in", "打断", "状态机"],
                preconditions=["实时语音通话已建立", "豆包正在播报回答"],
                steps=[
                    {
                        "action": "在播报中途连续说出新的问题",
                        "expected": "当前播报立即停止，只处理一次新输入，界面切回聆听后进入思考",
                    },
                    {
                        "action": "检查前后两轮字幕与音频",
                        "expected": "内容不重叠、不重复播放，上一轮未播完内容有明确截断状态",
                    },
                ],
                test_point_ids=[points[2].id],
            ),
            TestCaseDraft(
                id="VOICE-004",
                title="弱网抖动后在 3 秒内恢复且不重复播报",
                module="网络恢复",
                case_type="稳定性",
                priority=Priority.P0,
                tags=["豆包", "弱网", "重连", "幂等"],
                preconditions=["通话已建立", "可模拟高延迟、丢包和网络抖动"],
                steps=[
                    {
                        "action": "在用户说话和豆包回答阶段分别注入 30% 丢包与 800ms 抖动",
                        "expected": "界面显示恢复中，3 秒内完成重连，会话标识保持一致",
                    },
                    {
                        "action": "网络恢复后继续对话",
                        "expected": "不会重复提交用户语音，不会重复播放已完成回答，字幕顺序一致",
                    },
                ],
                test_point_ids=[points[3].id],
            ),
            TestCaseDraft(
                id="VOICE-005",
                title="断网超时后保留上下文并允许用户显式重试",
                module="网络恢复",
                case_type="异常",
                priority=Priority.P0,
                tags=["豆包", "断网", "超时", "重试"],
                preconditions=["通话已建立", "可完全断开网络"],
                steps=[
                    {
                        "action": "通话中断网并保持超过服务超时阈值",
                        "expected": "停止上传音频并明确提示连接已断开，不持续显示思考或回答",
                    },
                    {
                        "action": "恢复网络后点击重试",
                        "expected": "基于最近一次已确认上下文恢复新会话，不重复上一条用户请求",
                    },
                ],
                test_point_ids=[points[3].id],
            ),
            TestCaseDraft(
                id="VOICE-006",
                title="听筒、扬声器、蓝牙和有线耳机切换保持音频连续",
                module="音频路由",
                case_type="兼容性",
                priority=Priority.P1,
                tags=["豆包", "蓝牙", "耳机", "音频路由"],
                preconditions=["通话已建立", "设备已连接蓝牙耳机并可插拔有线耳机"],
                steps=[
                    {
                        "action": "按听筒、扬声器、蓝牙、有线耳机顺序切换输出路由",
                        "expected": (
                            "每次只激活一个正确路由，"
                            "音量合理且无爆音、长时间静音或双路播放"
                        ),
                    },
                    {
                        "action": "在播报中拔出耳机并关闭蓝牙",
                        "expected": "系统按平台策略回退到安全路由，会话和字幕保持连续",
                    },
                ],
                test_point_ids=[points[2].id],
            ),
            TestCaseDraft(
                id="VOICE-007",
                title="来电、闹钟、切后台和锁屏中断时状态一致",
                module="系统中断",
                case_type="稳定性",
                priority=Priority.P0,
                tags=["豆包", "来电", "后台", "锁屏"],
                preconditions=["通话已建立", "设备可触发来电、闹钟、切后台和锁屏"],
                steps=[
                    {
                        "action": "在聆听和回答阶段分别触发来电或闹钟",
                        "expected": "豆包按系统音频焦点规则暂停或结束，不与系统音频混播",
                    },
                    {
                        "action": "切后台、锁屏后再返回豆包",
                        "expected": "页面准确呈现已暂停、已结束或可恢复状态，不伪装为持续聆听",
                    },
                ],
                test_point_ids=[points[3].id],
            ),
            TestCaseDraft(
                id="VOICE-008",
                title="结束通话后释放资源并按隐私策略保存摘要",
                module="结束与留痕",
                case_type="安全",
                priority=Priority.P0,
                tags=["豆包", "资源释放", "摘要", "隐私"],
                preconditions=["至少完成两轮实时语音对话"],
                steps=[
                    {
                        "action": "点击结束通话并观察系统麦克风指示、音频焦点和网络连接",
                        "expected": (
                            "会话只结束一次，麦克风和音频焦点立即释放，"
                            "连接关闭且不再上传音频"
                        ),
                    },
                    {
                        "action": "进入会话记录查看文本摘要并重复点击通话入口",
                        "expected": (
                            "仅保存允许留存的文本摘要，"
                            "新通话使用新会话标识且不会复用旧音频缓存"
                        ),
                    },
                ],
                test_point_ids=[points[3].id],
            ),
        ]
        return features, points, cases

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
