from casepilot_agent.contracts import AgentProvider
from casepilot_agent.providers.mock import MockProvider


def create_provider(name: str) -> AgentProvider:
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unsupported_agent_provider:{name}")


__all__ = ["create_provider"]
