from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    provider: str = Field(default="mock", validation_alias="CASEPILOT_AGENT_PROVIDER")
    base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/coding/v3",
        validation_alias="CASEPILOT_AGENT_BASE_URL",
    )
    api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CASEPILOT_AGENT_API_KEY",
            "DASHSCOPE_API_KEY",
        ),
    )
    model: str = Field(
        default="doubao-seed-2.0-lite",
        validation_alias="CASEPILOT_AGENT_MODEL",
    )
    pro_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias="CASEPILOT_AGENT_PRO_MODEL",
    )
    local_model: str = Field(
        default="ark-code-latest",
        validation_alias="CASEPILOT_AGENT_LOCAL_MODEL",
    )
    models: str = Field(
        default="",
        validation_alias="CASEPILOT_AGENT_MODELS",
    )
    embedding_model: str = Field(
        default="doubao-embedding-vision",
        validation_alias="CASEPILOT_EMBEDDING_MODEL",
    )
    embedding_provider: str = Field(
        default="",
        validation_alias="CASEPILOT_EMBEDDING_PROVIDER",
    )
    embedding_base_url: str = Field(
        default="",
        validation_alias="CASEPILOT_EMBEDDING_BASE_URL",
    )
    embedding_api_key: str = Field(
        default="",
        validation_alias="CASEPILOT_EMBEDDING_API_KEY",
    )
    embedding_dimensions: int = Field(
        default=2048,
        validation_alias="CASEPILOT_EMBEDDING_DIMENSIONS",
    )
    embedding_timeout_seconds: float = Field(
        default=30,
        validation_alias="CASEPILOT_EMBEDDING_TIMEOUT_SECONDS",
    )
    embedding_fallback_enabled: bool = Field(
        default=True,
        validation_alias="CASEPILOT_EMBEDDING_FALLBACK_ENABLED",
    )
    timeout_seconds: float = Field(
        default=60,
        validation_alias="CASEPILOT_AGENT_TIMEOUT_SECONDS",
    )
    tracing_enabled: bool = Field(
        default=False,
        validation_alias="CASEPILOT_AGENT_TRACING_ENABLED",
    )
    database_url: str = Field(
        default="postgresql+psycopg://casepilot:casepilot-local@localhost:5432/casepilot",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        validation_alias="CELERY_BROKER_URL",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2",
        validation_alias="CELERY_RESULT_BACKEND",
    )
    knowledge_storage_path: str = Field(
        default="/var/lib/casepilot/knowledge",
        validation_alias="CASEPILOT_KNOWLEDGE_STORAGE_PATH",
    )

    def resolve_model(self, model_id: str) -> str:
        if model_id in {"test-design-pro", "pro"}:
            return self.pro_model
        if model_id == "local":
            return self.local_model
        if model_id in self.available_models:
            return model_id
        return self.model

    @property
    def available_models(self) -> tuple[str, ...]:
        models = [
            model.strip()
            for model in self.models.split(",")
            if model.strip()
        ]
        if not models:
            models = [self.model, self.pro_model, self.local_model]
        return tuple(dict.fromkeys(models))

    @property
    def resolved_embedding_provider(self) -> str:
        return self.embedding_provider or self.provider

    @property
    def resolved_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.base_url

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.api_key


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
