from types import SimpleNamespace

from casepilot_api.model_client import compatible_model, structured_model_settings


def test_explicit_responses_adapter_disables_remote_storage():
    from agents import OpenAIResponsesModel
    from openai import AsyncOpenAI

    settings = SimpleNamespace(agent_api_type="responses")
    client = AsyncOpenAI(api_key="synthetic-unused")
    model = compatible_model(model="synthetic", openai_client=client, settings=settings)
    assert isinstance(model, OpenAIResponsesModel)
    options = structured_model_settings(settings)
    assert options.store is False
    assert options.max_tokens == 8192
    assert options.extra_body is None
    import asyncio
    asyncio.run(client.close())


def test_chat_adapter_retains_default_and_json_mode():
    from agents import OpenAIChatCompletionsModel
    from openai import AsyncOpenAI

    settings = SimpleNamespace(agent_api_type="chat_completions")
    client = AsyncOpenAI(api_key="synthetic-unused")
    assert isinstance(compatible_model(model="synthetic", openai_client=client,
                                      settings=settings), OpenAIChatCompletionsModel)
    assert structured_model_settings(settings, json_mode=False) is None
    assert structured_model_settings(settings).extra_body == {
        "response_format": {"type": "json_object"}}
    import asyncio
    asyncio.run(client.close())


def test_responses_endpoint_and_incomplete_status_fail_closed(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    import pytest
    from agents import OpenAIResponsesModel
    from casepilot_agent.providers.responses import responses_base_url, responses_model
    from openai import AsyncOpenAI

    assert responses_base_url("https://ark.example/api/v3/responses") == (
        "https://ark.example/api/v3/")
    with pytest.raises(ValueError, match="api_type_mismatch"):
        responses_base_url("https://ark.example/v1/chat/completions")
    client = AsyncOpenAI(api_key="synthetic-unused")
    model = responses_model(model="synthetic", openai_client=client)
    monkeypatch.setattr(OpenAIResponsesModel, "_fetch_response", AsyncMock(
        return_value=SimpleNamespace(status="incomplete")))
    async def verify():
        try:
            with pytest.raises(ValueError, match="provider_incomplete_response"):
                await model._fetch_response()
        finally:
            await client.close()
    asyncio.run(verify())
