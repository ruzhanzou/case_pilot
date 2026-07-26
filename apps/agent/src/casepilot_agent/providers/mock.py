from casepilot_agent.contracts import GenerationRequest, GenerationResult, Risk, TestCase

STAGES = [
    "文件解析",
    "需求规范化",
    "风险识别",
    "测试点生成",
    "用例生成",
    "质量检查",
    "测试说明",
]


class MockProvider:
    @property
    def name(self) -> str:
        return "mock"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if any(keyword in request.prompt for keyword in ("登录", "验证码", "手机号")):
            return self._login_result()
        return self._generic_result()

    def _login_result(self) -> GenerationResult:
        return GenerationResult(
            mode=self.name,
            stages=STAGES,
            risks=[
                Risk(
                    id="R-AUTH-001",
                    severity="high",
                    title="验证码有效期与重复提交策略需要统一",
                    source="用户输入",
                ),
                Risk(
                    id="R-AUTH-002",
                    severity="medium",
                    title="连续输错后的限流阈值尚未明确",
                    source="AI 推断，等待确认",
                ),
            ],
            test_cases=[
                TestCase(
                    id="AUTH-001",
                    title="正确手机号与有效验证码登录成功",
                    preconditions=["手机号已注册", "已获取仍在有效期内的验证码"],
                    steps=[
                        {
                            "action": "输入正确手机号和有效验证码并提交",
                            "expected": "登录成功并进入默认质量空间",
                        }
                    ],
                ),
                TestCase(
                    id="AUTH-002",
                    title="验证码错误时拒绝登录",
                    preconditions=["手机号已注册", "登录页可正常访问"],
                    steps=[
                        {
                            "action": "输入正确手机号和错误验证码并提交",
                            "expected": "登录失败，提示验证码错误且不创建会话",
                        }
                    ],
                ),
                TestCase(
                    id="AUTH-003",
                    title="验证码过期后提示重新获取",
                    preconditions=["手机号已注册", "验证码已超过有效期"],
                    steps=[
                        {
                            "action": "输入已过期验证码并提交",
                            "expected": "登录失败，明确提示验证码过期并允许重新获取",
                        }
                    ],
                ),
                TestCase(
                    id="AUTH-004",
                    title="重复提交同一验证码只创建一个有效会话",
                    preconditions=["手机号已注册", "验证码仍然有效"],
                    steps=[
                        {
                            "action": "快速连续两次提交相同手机号和验证码",
                            "expected": "仅首次请求创建会话，后续请求不会产生重复副作用",
                        }
                    ],
                ),
            ],
        )

    def _generic_result(self) -> GenerationResult:
        return GenerationResult(
            mode=self.name,
            stages=STAGES,
            risks=[
                Risk(
                    id="R-001",
                    severity="high",
                    title="重复回调的幂等规则未明确",
                    source="需求说明 §4.2",
                )
            ],
            test_cases=[
                TestCase(
                    id="CASE-001",
                    title="重复请求不会产生重复副作用",
                    preconditions=["业务对象已创建"],
                    steps=[
                        {
                            "action": "使用相同业务标识连续提交两次请求",
                            "expected": "仅首次请求产生业务变更",
                        }
                    ],
                )
            ],
        )
