from hashlib import sha256
from math import sqrt

import httpx

from casepilot_agent.contracts import EMBEDDING_DIMENSIONS
from casepilot_agent.providers.openai_compatible import ProviderResponseError


class DeterministicEmbeddingProvider:
    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    @property
    def name(self) -> str:
        return "mock:embedding"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            digest = sha256(text.encode("utf-8")).digest()
            for index, value in enumerate(digest):
                vector[(index * 47 + value) % len(vector)] += (
                    value - 127.5
                ) / 127.5
            norm = sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float,
    ) -> None:
        if not api_key:
            raise ValueError("embedding_api_key_required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    @property
    def name(self) -> str:
        return f"openai_compatible:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "input": texts,
                "encoding_format": "float",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise ProviderResponseError("embedding_count_mismatch")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ProviderResponseError("invalid_embedding_dimensions")
        return vectors
