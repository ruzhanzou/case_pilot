"""Close request-local async model clients on the SDK's synchronous event loop."""
import asyncio
import logging
from contextlib import contextmanager


@contextmanager
def managed_model_client(client):
    try:
        yield client
    finally:
        # Runner.run_sync keeps the thread's default loop alive. Reuse it to
        # close pooled connections before their owner is garbage-collected.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client.close())
        except Exception:
            logging.getLogger(__name__).warning("model_client_cleanup_failed")


def model_failure_detail(error: Exception) -> str:
    """Actionable service failures must not be presented as ambiguous user intent."""
    from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

    if isinstance(error, APITimeoutError):
        reason = "模型响应超时，请稍后重试。"
    elif isinstance(error, APIConnectionError):
        reason = "模型连接暂时中断，请稍后重试。"
    elif isinstance(error, RateLimitError):
        reason = "模型服务当前繁忙，请稍后重试。"
    elif isinstance(error, APIStatusError):
        reason = "模型服务暂时不可用，请稍后重试。"
    else:
        reason = "模型回复未能解析，请重试。"
    return reason + "本次未执行操作，原草稿已保留。"


def model_error_chain(error: Exception) -> str:
    """Bounded diagnostic types, excluding messages, payloads, URLs and credentials."""
    names, seen = [], set()
    while error is not None and id(error) not in seen and len(names) < 6:
        seen.add(id(error))
        names.append(type(error).__name__)
        error = error.__cause__ or error.__context__
    return ">".join(names)


def compatible_model(*, model, openai_client, settings=None):
    """Select the explicitly configured API, never infer it from a model name."""
    from casepilot_api.config import get_settings

    api_type = getattr(settings or get_settings(), "agent_api_type", "chat_completions")
    if api_type == "responses":
        from casepilot_agent.providers.responses import responses_base_url, responses_model
        openai_client.base_url = responses_base_url(str(openai_client.base_url))
        return responses_model(model=model, openai_client=openai_client)
    from agents import OpenAIChatCompletionsModel
    return OpenAIChatCompletionsModel(model=model, openai_client=openai_client)


def structured_model_settings(settings=None, *, json_mode=True):
    from casepilot_api.config import get_settings

    api_type = getattr(settings or get_settings(), "agent_api_type", "chat_completions")
    if api_type != "responses" and not json_mode:
        return None
    from agents import ModelSettings

    if api_type == "responses":
        # Reasoning tokens share the output budget. Never treat empty/truncated
        # output as a valid domain result: SDK schema validation remains mandatory.
        return ModelSettings(max_tokens=8192, store=False)
    return ModelSettings(extra_body={"response_format": {"type": "json_object"}})


def optional_model_settings(settings=None):
    """Preserve the SDK default by omitting the keyword, never passing None."""
    value = structured_model_settings(settings, json_mode=False)
    return {"model_settings": value} if value is not None else {}
