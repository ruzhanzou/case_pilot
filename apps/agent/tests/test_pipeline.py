from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers.mock import MockProvider


def test_login_generation_is_structured_and_reports_progress() -> None:
    progress: list[tuple[str, int, int]] = []
    pipeline = GenerationPipeline(MockProvider())

    result = pipeline.run(
        GenerationRequest(prompt="为手机号验证码登录生成测试用例"),
        on_progress=lambda stage, current, total: progress.append(
            (stage, current, total)
        ),
    )

    assert result.mode == "mock"
    assert len(result.test_cases) == 4
    assert result.test_cases[0].id == "AUTH-001"
    assert len(progress) == len(result.stages)
    assert progress[-1] == ("测试说明", len(result.stages), len(result.stages))


def test_provider_can_be_developed_without_api_package() -> None:
    result = MockProvider().generate(GenerationRequest(prompt="支付回调需求"))

    assert result.test_cases
    assert result.risks
