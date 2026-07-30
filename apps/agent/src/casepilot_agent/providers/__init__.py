from casepilot_agent.config import get_settings
from casepilot_agent.contracts import AgentProvider, EmbeddingProvider
from casepilot_agent.providers.embeddings import (
    DeterministicEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
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
            pro_model=settings.pro_model,
            local_model=settings.local_model,
            timeout=settings.timeout_seconds,
            available_models=settings.available_models,
        )
    raise ValueError(f"unsupported_agent_provider:{name}")


def create_embedding_provider(
    name: str | None = None,
) -> EmbeddingProvider | None:
    settings = get_settings()
    provider_name = name or settings.resolved_embedding_provider
    if provider_name in {"", "disabled", "none"}:
        return None
    if provider_name == "mock":
        return DeterministicEmbeddingProvider(settings.embedding_dimensions)
    if provider_name == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.resolved_embedding_base_url,
            api_key=settings.resolved_embedding_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.embedding_timeout_seconds,
        )
    raise ValueError(f"unsupported_embedding_provider:{provider_name}")


__all__ = ["create_embedding_provider", "create_provider"]
