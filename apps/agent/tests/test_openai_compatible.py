import json

import httpx
import pytest

from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.providers.mock import MockProvider
from casepilot_agent.providers.openai_compatible import OpenAICompatibleProvider


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


def provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://model.example/v1",
        api_key="test-only",
        model="test-model",
        timeout=1,
    )


def test_provider_validates_structured_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = MockProvider().generate(GenerationRequest(prompt="支付需求"))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(expected.model_dump_json()),
    )

    result = provider().generate(GenerationRequest(prompt="支付需求"))

    assert result.test_cases
    assert result.feature_points


def test_provider_retries_one_invalid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = MockProvider().generate(GenerationRequest(prompt="支付需求"))
    responses = iter(
        [
            FakeResponse(json.dumps({"invalid": True})),
            FakeResponse(expected.model_dump_json()),
        ]
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: next(responses))

    result = provider().generate(GenerationRequest(prompt="支付需求"))

    assert result.quality.passed
