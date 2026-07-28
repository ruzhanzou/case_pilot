from casepilot_agent.config import get_settings
from casepilot_agent.contracts import AgentProvider
from casepilot_agent.providers.mock import MockProvider
from casepilot_agent.providers.openai_compatible import OpenAICompatibleProvider


def create_provider(name: str) -> AgentProvider:
    if name == "mock":
        return MockProvider()
    if name == "openai_compatible":
        settings = get_settings()
        return OpenAICompatibleProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout=settings.timeout_seconds,
        )
    raise ValueError(f"unsupported_agent_provider:{name}")


__all__ = ["create_provider"]
