from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    env: str = Field(default="development", validation_alias="CASEPILOT_ENV")
    api_host: str = Field(default="0.0.0.0", validation_alias="CASEPILOT_API_HOST")
    api_port: int = Field(default=8000, validation_alias="CASEPILOT_API_PORT")
    web_origin: str = Field(
        default="http://localhost:3000",
        validation_alias="CASEPILOT_WEB_ORIGIN",
    )
    ai_mode: str = Field(default="mock", validation_alias="CASEPILOT_AI_MODE")
    agent_provider: str = Field(
        default="mock",
        validation_alias="CASEPILOT_AGENT_PROVIDER",
    )
    agent_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/coding/v3",
        validation_alias="CASEPILOT_AGENT_BASE_URL",
    )
    agent_api_key: str = Field(
        default="",
        validation_alias="CASEPILOT_AGENT_API_KEY",
    )
    agent_timeout_seconds: float = Field(
        default=60,
        gt=0,
        validation_alias="CASEPILOT_AGENT_TIMEOUT_SECONDS",
    )
    agent_tracing_enabled: bool = Field(
        default=False,
        validation_alias="CASEPILOT_AGENT_TRACING_ENABLED",
    )
    agent_model: str = Field(
        default="doubao-seed-2.0-lite",
        validation_alias="CASEPILOT_AGENT_MODEL",
    )
    agent_pro_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias="CASEPILOT_AGENT_PRO_MODEL",
    )
    agent_local_model: str = Field(
        default="ark-code-latest",
        validation_alias="CASEPILOT_AGENT_LOCAL_MODEL",
    )
    agent_models: str = Field(
        default="",
        validation_alias="CASEPILOT_AGENT_MODELS",
    )
    agent_provider_label: str = Field(
        default="OpenAI Compatible",
        validation_alias="CASEPILOT_AGENT_PROVIDER_LABEL",
    )
    database_url: str = Field(
        default=(
            "postgresql+psycopg://casepilot:casepilot-local@localhost:5432/casepilot"
        ),
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
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
    knowledge_max_file_bytes: int = Field(
        default=25 * 1024 * 1024,
        gt=0,
        validation_alias="CASEPILOT_KNOWLEDGE_MAX_FILE_BYTES",
    )
    session_cookie_name: str = Field(
        default="casepilot_session",
        validation_alias="CASEPILOT_SESSION_COOKIE_NAME",
    )
    session_ttl_hours: int = Field(
        default=168,
        gt=0,
        validation_alias="CASEPILOT_SESSION_TTL_HOURS",
    )
    seed_demo_data: bool = Field(
        default=True,
        validation_alias="CASEPILOT_SEED_DEMO_DATA",
    )

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.env == "production" and self.seed_demo_data:
            raise ValueError("CASEPILOT_SEED_DEMO_DATA must be false in production")
        if self.ai_mode != "mock" and self.agent_provider != "mock" and not self.agent_api_key:
            raise ValueError("CASEPILOT_AGENT_API_KEY is required for real AI mode")
        return self

    @property
    def allowed_web_origins(self) -> tuple[str, ...]:
        origins: list[str] = []
        loopback_hosts = {"localhost", "127.0.0.1", "::1"}
        for configured_origin in self.web_origin.split(","):
            origin = configured_origin.strip().rstrip("/")
            if not origin:
                continue
            origins.append(origin)
            parsed = urlsplit(origin)
            if parsed.hostname not in loopback_hosts or not parsed.scheme:
                continue
            port = f":{parsed.port}" if parsed.port is not None else ""
            origins.extend(
                (
                    f"{parsed.scheme}://localhost{port}",
                    f"{parsed.scheme}://127.0.0.1{port}",
                    f"{parsed.scheme}://[::1]{port}",
                )
            )
        return tuple(dict.fromkeys(origins))

    @property
    def available_agent_models(self) -> tuple[str, ...]:
        models = [
            model.strip()
            for model in self.agent_models.split(",")
            if model.strip()
        ]
        if not models:
            models = [
                self.agent_model,
                self.agent_pro_model,
                self.agent_local_model,
            ]
        return tuple(dict.fromkeys(models))

    def is_agent_model_allowed(self, model_id: str) -> bool:
        if self.ai_mode == "mock" or self.agent_provider == "mock":
            return model_id == "auto"
        return model_id in {
            "auto",
            "test-design-pro",
            "pro",
            "local",
            *self.available_agent_models,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
