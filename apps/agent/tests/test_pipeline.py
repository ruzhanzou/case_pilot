import pytest

from casepilot_agent.contracts import (
    EnhancementResult,
    GenerationRequest,
    KnowledgeAnswer,
    RequirementAnalysis,
    RewriteRequest,
)
from casepilot_agent.contracts import (
    TestCaseBatch as CaseBatchResult,
)
from casepilot_agent.pipeline import (
    AwaitingInput,
    GenerationPipeline,
    GenerationQualityError,
    extract_explicit_test_object,
    validate_generation,
)
from casepilot_agent.providers.mock import MockProvider
from casepilot_agent.tasks import KNOWLEDGE_ANSWER_INSTRUCTION


def executor(provider: MockProvider, stages: list[str] | None = None):
    def execute(stage, instruction, payload, result_type, model_id):
        if stages is not None:
            stages.append(stage)
        return provider.complete(
            stage=stage,
            instruction=instruction,
            payload=payload,
            result_type=result_type,
            model_id=model_id,
        )[0]

    return execute


def test_knowledge_answer_instruction_allows_general_concept_answers() -> None:
    assert "即使没有空间资料证据也必须直接基于通用知识回答" in (
        KNOWLEDGE_ANSWER_INSTRUCTION
    )
    assert "只有问题涉及当前产品、组织流程或内部规则" in (
        KNOWLEDGE_ANSWER_INSTRUCTION
    )


def test_login_generation_has_traceable_objects_and_real_stage_order() -> None:
    provider = MockProvider()
    stages: list[str] = []
    result = GenerationPipeline(provider).run(
        GenerationRequest(prompt="为手机号验证码登录生成测试用例"),
        context={"query": "登录", "evidence": []},
        answers={},
        execute_stage=executor(provider, stages),
    )

    assert result.mode == "mock"
    assert result.test_cases[0].id == "AUTH-001"
    assert result.test_points[0].feature_point_ids == [result.feature_points[0].id]
    assert result.test_cases[0].test_point_ids == [result.test_points[0].id]
    assert result.quality.passed
    assert stages == [
        "requirement.analyzed",
        "feature.generated",
        "test_point.generated",
        "test_case.generated",
    ]


def test_doubao_realtime_voice_generation_covers_domain_risks() -> None:
    provider = MockProvider()
    result = GenerationPipeline(provider).run(
        GenerationRequest(
            prompt=(
                "为豆包 App 实时语音通话生成测试用例，覆盖麦克风权限、"
                "双向流式、用户插话、弱网重连、音频路由、来电中断和资源释放"
            )
        ),
        context={"query": "豆包 实时语音通话", "evidence": []},
        answers={},
        execute_stage=executor(provider),
    )

    assert [item.id for item in result.feature_points] == [
        "VOICE-FP-001",
        "VOICE-FP-002",
    ]
    assert len(result.test_cases) == 8
    assert {item.id for item in result.test_cases} == {
        "VOICE-001",
        "VOICE-002",
        "VOICE-003",
        "VOICE-004",
        "VOICE-005",
        "VOICE-006",
        "VOICE-007",
        "VOICE-008",
    }
    assert any("800ms" in step.expected for step in result.test_cases[0].steps)
    assert any("3 秒" in step.expected for step in result.test_cases[3].steps)
    assert all(item.source_refs for item in result.test_cases)
    assert result.quality.passed


def test_pipeline_pauses_for_blocking_question_and_resumes_with_answer() -> None:
    provider = MockProvider()
    pipeline = GenerationPipeline(provider)
    request = GenerationRequest(prompt="请生成测试用例")

    with pytest.raises(AwaitingInput) as caught:
        pipeline.run(
            request,
            context={"query": "支付", "evidence": []},
            answers={},
            execute_stage=executor(provider),
        )
    question = caught.value.requirement.open_questions[0]
    assert question.blocking
    assert question.id == "Q-TEST-OBJECT"

    result = pipeline.run(
        request,
        context={"query": "", "evidence": []},
        answers={question.id: "手机号验证码登录"},
        execute_stage=executor(provider),
    )
    assert result.quality.passed
    assert result.requirement.test_object == "手机号验证码登录"
    assert result.requirement.open_questions == []


def test_pipeline_does_not_clarify_details_beyond_the_test_object() -> None:
    provider = MockProvider()
    result = GenerationPipeline(provider).run(
        GenerationRequest(prompt="为手机号验证码登录生成测试用例"),
        context={"query": "登录", "evidence": []},
        answers={},
        execute_stage=executor(provider),
    )

    assert result.requirement.test_object == "手机号验证码登录"
    assert result.requirement.test_object_specified
    assert result.requirement.open_questions == []


def test_explicit_test_object_extraction_handles_confirmation_and_questions() -> None:
    assert extract_explicit_test_object("测试对象为豆包APP") == "豆包APP"
    assert (
        extract_explicit_test_object(
            "测试对象 都包 为手机号验证码登录生成测试用例，覆盖弱网场景"
        )
        == "手机号验证码登录"
    )
    assert extract_explicit_test_object("测试对象不是明确了吗") == ""


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


def test_validator_accepts_localized_coverage_matrix_keys() -> None:
    result = MockProvider().generate(GenerationRequest(prompt="支付回调需求"))
    requirement_ref = result.feature_points[0].requirement_refs[0]
    result.coverage_matrix = [
        {
            "需求编号": requirement_ref,
            "功能点ID": [result.feature_points[0].id],
            "测试点编号": [result.test_points[0].id],
        }
    ]

    report = validate_generation(result)

    assert "requirement_coverage_gap" not in {
        issue.code for issue in report.issues
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


def test_mock_provider_answers_knowledge_question_with_citation() -> None:
    answer, _ = MockProvider().complete(
        stage="knowledge.answered",
        instruction="基于证据回答",
        payload={
            "prompt": "需求中的超时阈值是多少？",
            "context": {
                "evidence": [
                    {
                        "source_id": "source-1",
                        "document_id": "document-1",
                        "chunk_id": "chunk-1",
                        "label": "登录需求.md",
                        "locator": "超时策略",
                        "excerpt": "验证码有效期为 5 分钟。",
                    }
                ]
            },
        },
        result_type=KnowledgeAnswer,
        model_id="auto",
    )

    assert "验证码有效期为 5 分钟" in answer.answer
    assert answer.citations[0].label == "登录需求.md"


def test_mock_provider_updates_existing_brief_and_resolves_background_call() -> None:
    updated, _ = MockProvider().complete(
        stage="requirement.analyzed",
        instruction="合并测试说明",
        payload={
            "prompt": "锁屏和切后台后允许继续保持实时语音通话",
            "current_test_brief": {
                "test_object": "豆包 App 实时语音通话",
                "test_objective": "验证豆包实时通话",
                "roles": ["终端用户"],
                "core_flows": ["发起实时通话"],
                "business_rules": ["用户授权麦克风后才能通话"],
                "constraints": ["支持 iOS 与 Android"],
                "risks": ["后台保活受系统限制"],
                "assumptions": [],
                "open_questions": [
                    {
                        "id": "Q-BACKGROUND",
                        "question": "锁屏和切后台是否允许继续保持实时通话？",
                        "impact": "影响后台场景测试范围",
                        "blocking": True,
                    },
                    {
                        "id": "Q-RETENTION",
                        "question": "通话文本摘要保存多久？",
                        "impact": "影响隐私验证",
                        "blocking": False,
                    },
                ],
            },
        },
        result_type=RequirementAnalysis,
        model_id="auto",
    )

    assert "锁屏和切后台后允许继续保持实时语音通话" in (
        updated.business_rules
    )
    assert all("锁屏" not in item.question for item in updated.open_questions)
    assert any("保存多久" in item.question for item in updated.open_questions)


def test_pipeline_stops_enhancement_after_two_rounds() -> None:
    class InvalidProvider(MockProvider):
        enhancement_calls = 0

        def complete(self, **kwargs):
            result, usage = super().complete(**kwargs)
            if kwargs["result_type"] is CaseBatchResult:
                result.test_cases[0].steps = []
            if kwargs["result_type"] is EnhancementResult:
                self.enhancement_calls += 1
                result.test_cases[0].steps = []
            return result, usage

    provider = InvalidProvider()
    with pytest.raises(GenerationQualityError) as caught:
        GenerationPipeline(provider).run(
            GenerationRequest(prompt="支付需求"),
            context={"query": "支付", "evidence": []},
            answers={},
            execute_stage=executor(provider),
        )

    assert caught.value.report.repair_rounds == 2
    assert provider.enhancement_calls == 2
