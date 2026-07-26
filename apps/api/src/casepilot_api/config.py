from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    session_cookie_name: str = Field(
        default="casepilot_session",
        validation_alias="CASEPILOT_SESSION_COOKIE_NAME",
    )
    session_ttl_hours: int = Field(
        default=168,
        validation_alias="CASEPILOT_SESSION_TTL_HOURS",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
