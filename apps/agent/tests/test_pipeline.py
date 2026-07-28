from casepilot_agent.contracts import GenerationRequest, RewriteRequest
from casepilot_agent.pipeline import GenerationPipeline, validate_generation
from casepilot_agent.providers.mock import MockProvider


def test_login_generation_has_traceable_objects_and_progress() -> None:
    progress: list[tuple[str, int, dict]] = []
    pipeline = GenerationPipeline(MockProvider())

    result = pipeline.run(
        GenerationRequest(prompt="为手机号验证码登录生成测试用例"),
        on_progress=lambda stage, current, detail: progress.append(
            (stage, current, detail)
        ),
    )

    assert result.mode == "mock"
    assert result.test_cases[0].id == "AUTH-001"
    assert result.test_points[0].feature_point_ids == [result.feature_points[0].id]
    assert result.test_cases[0].test_point_ids == [result.test_points[0].id]
    assert result.quality.passed
    assert progress[-1][0] == "quality.completed"


def test_validator_detects_empty_steps_and_invalid_reference() -> None:
    result = MockProvider().generate(GenerationRequest(prompt="支付回调需求"))
    result.test_cases[0].steps = []
    result.test_cases[0].test_point_ids = ["missing"]

    report = validate_generation(result)

    assert not report.passed
    assert {issue.code for issue in report.issues} >= {
        "empty_steps",
        "invalid_test_point_reference",
    }


def test_rewrite_creates_candidate_without_mutating_source() -> None:
    provider = MockProvider()
    generated = provider.generate(GenerationRequest(prompt="支付回调需求"))
    original = generated.test_cases[0]

    candidate = provider.rewrite(
        RewriteRequest(test_case=original, instruction="增加校验点")
    )

    assert len(candidate.proposed.steps) == len(original.steps) + 1
    assert len(original.steps) == 1
    assert candidate.diff


def test_rewrite_combines_custom_instruction_intents() -> None:
    provider = MockProvider()
    original = provider.generate(
        GenerationRequest(prompt="手机号验证码登录")
    ).test_cases[0]

    candidate = provider.rewrite(
        RewriteRequest(
            test_case=original,
            instruction="补充短信网关不可用时的异常校验点，并让表达更清晰",
        )
    )

    assert candidate.proposed.title.endswith("（明确校验结果）")
    assert len(candidate.proposed.steps) == len(original.steps) + 1
    assert "短信网关不可用" in candidate.proposed.steps[-1].action
    assert {item.field for item in candidate.diff} == {"title", "steps"}


def test_pipeline_stops_repairing_after_two_rounds() -> None:
    class InvalidProvider(MockProvider):
        calls = 0

        def generate(self, request: GenerationRequest):
            self.calls += 1
            result = super().generate(request)
            result.test_cases[0].steps = []
            return result

    provider = InvalidProvider()

    result = GenerationPipeline(provider).run(GenerationRequest(prompt="支付需求"))

    assert not result.quality.passed
    assert result.quality.repair_rounds == 2
    assert provider.calls == 3
