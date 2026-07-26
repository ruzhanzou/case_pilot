from uuid import uuid4

from casepilot_api.schemas import (
    MockGenerationJob,
    MockGenerationRequest,
    MockRisk,
    MockTestCase,
)

STAGES = [
    "文件解析",
    "需求规范化",
    "风险识别",
    "测试点生成",
    "用例生成",
    "质量检查",
    "测试说明",
]


def create_mock_job(payload: MockGenerationRequest) -> MockGenerationJob:
    if any(keyword in payload.prompt for keyword in ("登录", "验证码", "手机号")):
        return create_login_mock_job(payload)

    return MockGenerationJob(
        id=uuid4(),
        status="queued",
        prompt=payload.prompt,
        file_names=payload.file_names,
        stages=STAGES,
        risks=[
            MockRisk(
                id="R-001",
                severity="high",
                title="重复回调的幂等规则未明确",
                source="需求说明 §4.2",
            ),
            MockRisk(
                id="R-002",
                severity="medium",
                title="弱网重试窗口缺少上限",
                source="AI 推断，等待确认",
            ),
        ],
        test_cases=[
            MockTestCase(
                id="PAY-008",
                title="支付成功后重复回调的幂等处理",
                preconditions=["订单处于待支付状态", "已配置支付回调地址"],
                steps=[
                    {
                        "action": "模拟支付平台首次发送成功回调",
                        "expected": "订单变为已支付，库存仅扣减一次",
                    },
                    {
                        "action": "使用相同交易号再次发送回调",
                        "expected": "接口返回成功，订单金额和状态保持不变",
                    },
                ],
            ),
            MockTestCase(
                id="PAY-009",
                title="退款回调超时后的补偿处理",
                preconditions=["订单已支付", "退款申请已受理"],
                steps=[
                    {
                        "action": "让首次退款回调超过系统超时时间",
                        "expected": "任务进入可重试状态且不重复退款",
                    }
                ],
            ),
        ],
    )


def create_login_mock_job(payload: MockGenerationRequest) -> MockGenerationJob:
    return MockGenerationJob(
        id=uuid4(),
        status="queued",
        prompt=payload.prompt,
        file_names=payload.file_names,
        stages=STAGES,
        risks=[
            MockRisk(
                id="R-AUTH-001",
                severity="high",
                title="验证码有效期与重复提交策略需要统一",
                source="用户输入",
            ),
            MockRisk(
                id="R-AUTH-002",
                severity="medium",
                title="连续输错后的限流阈值尚未明确",
                source="AI 推断，等待确认",
            ),
        ],
        test_cases=[
            MockTestCase(
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
            MockTestCase(
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
            MockTestCase(
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
            MockTestCase(
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
