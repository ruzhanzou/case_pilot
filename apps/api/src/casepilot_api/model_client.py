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
            logging.getLogger(__name__).warning("model_client_cleanup_failed", exc_info=True)


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
