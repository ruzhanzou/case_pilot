import sys
from types import ModuleType, SimpleNamespace

import pytest

class FakeAPITimeoutError(TimeoutError):
    def __init__(self, *args, request=None):
        super().__init__(*args)


from casepilot_agent.contracts import KnowledgeAnswer
from casepilot_agent.providers.agents_sdk import AgentsSdkProvider


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("stage,timeouts", [
    ("knowledge.answered", 0), ("test_case.generated", 1), ("test_case.generated", 2),
    ("knowledge.answered", 1),
    ("test_point.generated", 0), ("feature.generated", 0),
])
def test_agents_sdk_provider_uses_explicit_openai_compatible_client(
    monkeypatch: pytest.MonkeyPatch, stage: str, timeouts: int, compact: bool,
) -> None:
    captured: dict = {}
    agents = ModuleType("agents")
    openai = ModuleType("openai")

    class FakeClient:
        async def close(self):
            pass

        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            captured["model"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured["agent"] = kwargs

    class FakeAgentOutputSchema:
        def __init__(self, output_type, *, strict_json_schema) -> None:
            self.output_type = output_type
            self.strict_json_schema = strict_json_schema

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt, max_turns):
            return FakeRunner.run_sync(agent, prompt, max_turns)

        @staticmethod
        def run_sync(agent, prompt, max_turns):
            captured["prompt"] = prompt
            captured["max_turns"] = max_turns
            captured["calls"] = captured.get("calls", 0) + 1
            if captured["calls"] <= timeouts:
                raise TimeoutError("transient provider timeout")
            return SimpleNamespace(
                final_output=KnowledgeAnswer(answer="已回答"),
                context_wrapper=SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=11,
                        output_tokens=7,
                        total_tokens=18,
                    )
                ),
            )

    agents.Agent = FakeAgent
    agents.ModelSettings = SimpleNamespace
    agents.AgentOutputSchema = FakeAgentOutputSchema
    agents.ModelBehaviorError = RuntimeError
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: captured.update(
        tracing_disabled=disabled
    )
    openai.AsyncOpenAI = FakeClient
    openai.APITimeoutError = FakeAPITimeoutError
    monkeypatch.setitem(sys.modules, "agents", agents)
    monkeypatch.setitem(sys.modules, "openai", openai)

    provider = AgentsSdkProvider(
        base_url="https://ark.example/v1/",
        api_key="test-only",
        model="doubao-test",
        pro_model="doubao-pro",
        local_model="local",
        timeout=5,
    )
    kwargs = dict(stage=stage, instruction="回答问题", payload={"question": "什么是边界值？", **({"batch_count": 20} if stage == "test_case.generated" else {})},
                  result_type=KnowledgeAnswer, model_id="auto")
    if compact:
        kwargs["payload"]["output_contract"] = "case_batch_v2"
    if (compact and timeouts) or timeouts == 2 or (stage == "knowledge.answered" and timeouts):
        with pytest.raises(TimeoutError):
            provider.complete(**kwargs)
        assert captured["calls"] == (2 if stage == "test_case.generated" and not compact else 1)
        return
    result, usage = provider.complete(**kwargs)
    assert captured["calls"] == timeouts + 1

    assert result.answer == "已回答"
    assert captured["client"]["base_url"] == "https://ark.example/v1"
    assert captured["client"]["max_retries"] == 0
    assert captured["model"]["model"] == "doubao-test"
    output_schema = captured["agent"]["output_type"]
    assert output_schema.output_type is KnowledgeAnswer
    assert captured["agent"]["model_settings"].extra_body == {"response_format": {"type": "json_object"}}
    expected_budget = 32048 if stage == "test_case.generated" else 16384 if stage in {"test_point.generated", "feature.generated"} else None
    assert captured["agent"]["model_settings"].max_tokens == expected_budget
    assert output_schema.strict_json_schema is False
    assert captured["tracing_disabled"] is True
    assert usage.token_usage["total_tokens"] == 18


@pytest.mark.parametrize(
    ("stage", "fallback_stage_timeout"),
    [
        ("requirement.analyzed", 120),
        ("feature.generated", 120),
        ("test_point.generated", 120),
        ("test_case.generated", 300),
        ("enhancement.completed", 300),
    ],
)
def test_agents_sdk_provider_uses_fast_fallback_for_structured_generation(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    fallback_stage_timeout: int,
) -> None:
    captured: dict = {"client_timeouts": []}
    agents = ModuleType("agents")
    openai = ModuleType("openai")
    calls = 0
    models: list[str] = []
    prompts: list[str] = []

    class FakeModelBehaviorError(RuntimeError):
        pass

    class FakeClient:
        async def close(self):
            pass

        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs
            captured["client_timeouts"].append(kwargs["timeout"])

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            models.append(kwargs["model"])

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            pass

    class FakeAgentOutputSchema:
        def __init__(self, output_type, *, strict_json_schema) -> None:
            pass

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt, max_turns):
            return FakeRunner.run_sync(agent, prompt, max_turns)

        @staticmethod
        def run_sync(agent, prompt, max_turns):
            nonlocal calls
            calls += 1
            prompts.append(prompt)
            if calls <= 2:
                raise FakeModelBehaviorError("invalid structured output")
            return SimpleNamespace(
                final_output=KnowledgeAnswer(answer="已回答"),
                context_wrapper=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
                ),
            )

    agents.Agent = FakeAgent
    agents.ModelSettings = SimpleNamespace
    agents.AgentOutputSchema = FakeAgentOutputSchema
    agents.ModelBehaviorError = FakeModelBehaviorError
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: None
    openai.AsyncOpenAI = FakeClient
    openai.APITimeoutError = FakeAPITimeoutError
    monkeypatch.setitem(sys.modules, "agents", agents)
    monkeypatch.setitem(sys.modules, "openai", openai)

    provider = AgentsSdkProvider(
        base_url="https://ark.example/v1",
        api_key="test-only",
        model="doubao-test",
        pro_model="doubao-pro",
        local_model="local",
        timeout=120,
        generation_timeout=300,
        model_fallback_timeout=45,
    )
    provider.complete(
        stage=stage,
        instruction="生成用例",
        payload={},
        result_type=KnowledgeAnswer,
        model_id="local",
    )

    assert captured["client"]["timeout"] == fallback_stage_timeout
    assert captured["client_timeouts"] == [45, fallback_stage_timeout]
    assert calls == 3
    assert models == ["local", "doubao-test"]
    assert "上一次输出未通过 JSON Schema 校验" not in prompts[1]
    assert "上一次输出未通过 JSON Schema 校验" in prompts[2]
    assert "invalid structured output" in prompts[2]


@pytest.mark.parametrize("fails", [False, True])
def test_agents_sdk_provider_streams_text_deltas(
    monkeypatch: pytest.MonkeyPatch, fails: bool,
) -> None:
    captured: dict = {}
    agents = ModuleType("agents")
    openai = ModuleType("openai")

    class FakeClient:
        async def close(self):
            pass

        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

        async def close(self):
            import asyncio
            captured["closed_on_active_loop"] = asyncio.get_running_loop().is_running()

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            captured["model"] = kwargs

    class FakeModelSettings:
        def __init__(self, **kwargs) -> None:
            captured["model_settings"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured["agent"] = kwargs

    class FakeStreamResult:
        final_output = "边界值用于验证输入范围的临界点。"
        context_wrapper = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=9,
                output_tokens=6,
                total_tokens=15,
            )
        )

        async def stream_events(self):
            if fails:
                raise RuntimeError("stream interrupted")
            for delta in ("边界值用于", "验证输入范围的临界点。"):
                yield SimpleNamespace(
                    type="raw_response_event",
                    data=SimpleNamespace(
                        type="response.output_text.delta",
                        delta=delta,
                    ),
                )

    class FakeRunner:
        @staticmethod
        def run_streamed(agent, prompt, max_turns):
            captured["prompt"] = prompt
            captured["max_turns"] = max_turns
            return FakeStreamResult()

    agents.Agent = FakeAgent
    agents.ModelSettings = SimpleNamespace
    agents.ModelSettings = FakeModelSettings
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: captured.update(
        tracing_disabled=disabled
    )
    openai.AsyncOpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "agents", agents)
    monkeypatch.setitem(sys.modules, "openai", openai)

    provider = AgentsSdkProvider(
        base_url="https://ark.example/v1/",
        api_key="test-only",
        model="doubao-test",
        pro_model="doubao-pro",
        local_model="local",
        timeout=5,
    )
    deltas: list[str] = []
    kwargs = dict(stage="knowledge.answered", instruction="回答问题",
                  payload={"question": "什么是边界值？"}, model_id="auto", on_delta=deltas.append)
    if fails:
        with pytest.raises(RuntimeError, match="stream interrupted"):
            provider.complete_text_stream(**kwargs)
        assert captured["closed_on_active_loop"] is True
        return
    result, usage = provider.complete_text_stream(**kwargs)
    assert captured["closed_on_active_loop"] is True

    assert result == "边界值用于验证输入范围的临界点。"
    assert deltas == ["边界值用于", "验证输入范围的临界点。"]
    assert captured["model_settings"]["include_usage"] is True
    assert usage.token_usage["total_tokens"] == 15


def test_agents_sdk_provider_skips_degraded_model_for_later_generation_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {"models": [], "timeouts": []}
    agents = ModuleType("agents")
    openai = ModuleType("openai")

    class FakeClient:
        async def close(self):
            pass

        def __init__(self, **kwargs) -> None:
            captured["timeouts"].append(kwargs["timeout"])

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            self.name = kwargs["model"]
            captured["models"].append(self.name)

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            self.model = kwargs["model"]

    class FakeAgentOutputSchema:
        def __init__(self, output_type, *, strict_json_schema) -> None:
            pass

    class FakeRunner:
        @staticmethod
        async def run(agent, prompt, max_turns):
            return FakeRunner.run_sync(agent, prompt, max_turns)

        @staticmethod
        def run_sync(agent, prompt, max_turns):
            if agent.model.name == "local":
                raise TimeoutError("slow selected model")
            return SimpleNamespace(
                final_output=KnowledgeAnswer(answer="已回答"),
                context_wrapper=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
                ),
            )

    agents.Agent = FakeAgent
    agents.ModelSettings = SimpleNamespace
    agents.AgentOutputSchema = FakeAgentOutputSchema
    agents.ModelBehaviorError = ValueError
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: None
    openai.AsyncOpenAI = FakeClient
    openai.APITimeoutError = FakeAPITimeoutError
    monkeypatch.setitem(sys.modules, "agents", agents)
    monkeypatch.setitem(sys.modules, "openai", openai)

    provider = AgentsSdkProvider(
        base_url="https://ark.example/v1",
        api_key="test-only",
        model="doubao-test",
        pro_model="doubao-pro",
        local_model="local",
        timeout=120,
        generation_timeout=300,
        model_fallback_timeout=45,
    )
    for stage in ("requirement.analyzed", "feature.generated"):
        provider.complete(
            stage=stage,
            instruction="生成",
            payload={},
            result_type=KnowledgeAnswer,
            model_id="local",
        )

    assert captured["models"] == ["local", "doubao-test", "doubao-test"]
    assert captured["timeouts"] == [45, 120, 120]


def test_batch_instruction_is_scoped_to_one_existing_case(monkeypatch):
    import json

    from agents import Runner

    from casepilot_agent.contracts import (
        GenerationRequest,
        QualityReport,
        RewriteCandidate,
        RewriteRequest,
    )
    from casepilot_agent.providers import agents_sdk
    from casepilot_agent.providers.mock import MockProvider

    original = MockProvider().generate(GenerationRequest(prompt="登录")).test_cases[0]
    candidate = RewriteCandidate(
        proposed=original, diff=[], reason="无需改动", quality=QualityReport(passed=True, score=100)
    )
    captured = {}

    async def run(agent, prompt, **kwargs):
        captured.update(
            instructions=agent.instructions,
            prompt=json.loads(prompt),
            output=agent.output_type.output_type,
        )
        return SimpleNamespace(
            final_output=candidate, context_wrapper=SimpleNamespace(usage=SimpleNamespace())
        )

    def no_generation_skill():
        raise AssertionError("Existing-case rewrite must not load new-case generation rules")

    monkeypatch.setattr(Runner, "run", run)
    monkeypatch.setattr(agents_sdk, "load_test_case_generation_skill", no_generation_skill)
    provider = AgentsSdkProvider(
        base_url="https://example.test/v1",
        api_key="test-only",
        model="test",
        pro_model="test",
        local_model="test",
        timeout=1,
    )
    result = provider.rewrite(
        RewriteRequest(test_case=original, instruction="重写剩余未纳入的2条候选用例")
    )
    assert result.proposed.id == original.id
    assert captured["prompt"]["input"]["test_case"]["id"] == original.id
    assert "proposed 必须是单个完整用例对象" in captured["instructions"]
    assert "未要求修改的内容逐字保留" in captured["instructions"]
    assert captured["output"] is RewriteCandidate


def test_ark_rewrite_uses_same_inference_options_as_generation():
    from casepilot_agent.providers.agents_sdk import _response_options
    ark = "https://ark.cn-beijing.volces.com/api/coding/v3"
    for stage in ("rewrite.batch", "rewrite.evidence", "test_case.rewritten"):
        assert _response_options(ark, stage) == _response_options(ark, "test_case.generated")
        assert "thinking" not in _response_options(ark, stage)
    assert _response_options(ark, "requirement.extracted")["thinking"] == {"type": "disabled"}
    assert "thinking" not in _response_options(ark, "test_point.generated")
    assert "thinking" not in _response_options(ark, "test_case.grounded")
    assert "thinking" not in _response_options("https://api.openai.com/v1", "requirement.extracted")
    assert "thinking" not in _response_options(ark, "requirement.analyzed")
    assert "thinking" not in _response_options("https://api.openai.com/v1", "rewrite.batch")
    assert "thinking" not in _response_options("https://ark.volces.com.example.org/v1", "rewrite.batch")


def test_structured_call_has_wall_clock_deadline(monkeypatch):
    import asyncio
    import time
    from agents import Runner
    from openai import APITimeoutError
    cancelled = []
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(Runner, 'run', slow)
    provider = AgentsSdkProvider(base_url='https://example.test/v1',api_key='test-only',
        model='same',pro_model='same',local_model='same',timeout=0.01,generation_timeout=0.01)
    started = time.monotonic()
    with pytest.raises(APITimeoutError):
        provider.complete(stage='rewrite.batch', instruction='修改',payload={'items':[]},
                          result_type=KnowledgeAnswer,model_id='auto')
    assert cancelled == [True]
    assert time.monotonic()-started < 1


def test_auto_rewrite_falls_back_once_and_reuses_backup_model(monkeypatch):
    from agents import Runner
    from agents.exceptions import ModelBehaviorError
    models=[]
    async def run(agent,*args,**kwargs):
        models.append(agent.model.model)
        if agent.model.model=='fast':raise ModelBehaviorError('invalid output')
        return SimpleNamespace(final_output=KnowledgeAnswer(answer='有效结果'),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace()))
    monkeypatch.setattr(Runner,'run',run)
    provider=AgentsSdkProvider(base_url='https://example.test/v1',api_key='test-only',
        model='fast',pro_model='backup',local_model='fast',timeout=5)
    for _ in range(2):
        result,usage=provider.complete(stage='rewrite.batch',instruction='修改',payload={'items':[]},
                                      result_type=KnowledgeAnswer,model_id='auto')
        assert usage.model=='backup'
    assert models==['fast','backup','backup']


@pytest.mark.parametrize('stage,model_id,expected', [
    ('test_case.grounded', 'auto', 'quality'),
    ('rewrite.batch', 'auto', 'quality'),
    ('rewrite.batch', 'test-design-fast', 'fast'),
])
def test_evidence_review_uses_quality_model_only_in_auto_mode(monkeypatch, stage, model_id, expected):
    from agents import Runner
    models = []
    async def run(agent, *args, **kwargs):
        models.append(agent.model.model)
        return SimpleNamespace(final_output=KnowledgeAnswer(answer='结果'),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace()))
    monkeypatch.setattr(Runner, 'run', run)
    provider = AgentsSdkProvider(base_url='https://example.test/v1', api_key='test-only',
        model='fast', pro_model='quality', local_model='fast', timeout=5)
    provider.complete(stage=stage, instruction='核对预期',
        payload={'shared': [{'instruction': '核对预期', 'context': {'evidence_ref_indexes': [0]}}]},
        result_type=KnowledgeAnswer, model_id=model_id)
    assert models == [expected]


@pytest.mark.parametrize('fail', [False, True])
def test_basic_rewrite_does_not_upgrade_model_for_evidence_or_retry(monkeypatch, fail):
    from agents import Runner
    from agents.exceptions import ModelBehaviorError
    models = []
    async def run(agent, *args, **kwargs):
        models.append(agent.model.model)
        if fail:
            raise ModelBehaviorError('invalid output')
        return SimpleNamespace(final_output=KnowledgeAnswer(answer='结果'),
                               context_wrapper=SimpleNamespace(usage=SimpleNamespace()))
    monkeypatch.setattr(Runner, 'run', run)
    provider = AgentsSdkProvider(base_url='https://example.test/v1', api_key='test-only',
        model='fast', pro_model='quality', local_model='fast', timeout=5)
    kwargs = dict(stage='rewrite.batch', instruction='核对预期',
        payload={'validation_mode':'human_review_basic', 'shared': [
            {'instruction':'核对预期','context':{'evidence_ref_indexes':[0]}}]},
        result_type=KnowledgeAnswer, model_id='auto')
    if fail:
        with pytest.raises(ModelBehaviorError):
            provider.complete(**kwargs)
    else:
        provider.complete(**kwargs)
    assert models == ['fast']
