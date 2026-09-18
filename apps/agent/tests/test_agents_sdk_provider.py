import sys
from types import ModuleType, SimpleNamespace

import pytest

from casepilot_agent.contracts import KnowledgeAnswer
from casepilot_agent.providers.agents_sdk import AgentsSdkProvider


def test_agents_sdk_provider_uses_explicit_openai_compatible_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    agents = ModuleType("agents")
    openai = ModuleType("openai")

    class FakeClient:
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
        def run_sync(agent, prompt, max_turns):
            captured["prompt"] = prompt
            captured["max_turns"] = max_turns
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
    agents.AgentOutputSchema = FakeAgentOutputSchema
    agents.ModelBehaviorError = RuntimeError
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: captured.update(
        tracing_disabled=disabled
    )
    openai.AsyncOpenAI = FakeClient
    openai.APITimeoutError = TimeoutError
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
    result, usage = provider.complete(
        stage="knowledge.answered",
        instruction="回答问题",
        payload={"question": "什么是边界值？"},
        result_type=KnowledgeAnswer,
        model_id="auto",
    )

    assert result.answer == "已回答"
    assert captured["client"]["base_url"] == "https://ark.example/v1"
    assert captured["client"]["max_retries"] == 2
    assert captured["model"]["model"] == "doubao-test"
    output_schema = captured["agent"]["output_type"]
    assert output_schema.output_type is KnowledgeAnswer
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
    agents.AgentOutputSchema = FakeAgentOutputSchema
    agents.ModelBehaviorError = FakeModelBehaviorError
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: None
    openai.AsyncOpenAI = FakeClient
    openai.APITimeoutError = TimeoutError
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


def test_agents_sdk_provider_streams_text_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    agents = ModuleType("agents")
    openai = ModuleType("openai")

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

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
    result, usage = provider.complete_text_stream(
        stage="knowledge.answered",
        instruction="回答问题",
        payload={"question": "什么是边界值？"},
        model_id="auto",
        on_delta=deltas.append,
    )

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
    agents.AgentOutputSchema = FakeAgentOutputSchema
    agents.ModelBehaviorError = ValueError
    agents.OpenAIChatCompletionsModel = FakeModel
    agents.Runner = FakeRunner
    agents.set_tracing_disabled = lambda disabled: None
    openai.AsyncOpenAI = FakeClient
    openai.APITimeoutError = TimeoutError
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
