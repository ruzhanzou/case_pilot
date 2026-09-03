import pytest
from httpx import ASGITransport, AsyncClient

from casepilot_api import generation, main
from casepilot_api.config import Settings, get_settings
from casepilot_api.generation import list_generation_models
from casepilot_api.main import app


@pytest.mark.asyncio
async def test_live_health() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["generation"] == get_settings().ai_mode


@pytest.mark.asyncio
async def test_readiness_returns_503_when_a_dependency_is_unavailable(monkeypatch) -> None:
    class UnavailableRedis:
        def ping(self) -> None:
            raise ConnectionError("redis unavailable")

        def close(self) -> None:
            pass

    monkeypatch.setattr(main, "check_database", lambda: None)
    monkeypatch.setattr(main.Redis, "from_url", lambda *args, **kwargs: UnavailableRedis())

    response = await main.ready()

    assert response.status_code == 503


def test_loopback_web_origin_accepts_localhost_and_ip_aliases() -> None:
    settings = Settings(
        _env_file=None,
        CASEPILOT_WEB_ORIGIN="http://localhost:13000",
    )

    assert settings.allowed_web_origins == (
        "http://localhost:13000",
        "http://127.0.0.1:13000",
        "http://[::1]:13000",
    )


def test_case_management_routes_are_exposed() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/spaces/{space_id}/collections" in paths
    assert "/api/v1/collections/{collection_id}/test-cases" in paths
    assert "/api/v1/collections/{collection_id}/test-cases/batch" in paths
    assert "/api/v1/test-cases/{case_id}" in paths
    assert "/api/v1/collections/{collection_id}/execution-runs" in paths
    assert "/api/v1/execution-records/{record_id}" in paths


def test_generation_routes_are_exposed_without_legacy_mock_paths() -> None:
    paths = app.openapi()["paths"]

    assert all("/mock/" not in path for path in paths)
    assert "/api/v1/generation-jobs" in paths
    assert "/api/v1/generation-jobs/{job_id}/events" in paths
    assert "/api/v1/generation-models" in paths
    assert "/api/v1/test-cases/{case_id}/candidate-revisions" in paths


def test_generation_models_expose_the_configured_catalog(monkeypatch) -> None:
    monkeypatch.setattr(generation.settings, "ai_mode", "real")
    monkeypatch.setattr(
        generation.settings,
        "agent_provider",
        "openai_compatible",
    )
    monkeypatch.setattr(
        generation.settings,
        "agent_provider_label",
        "火山方舟 Coding Plan",
    )
    monkeypatch.setattr(
        generation.settings,
        "agent_models",
        "ark-code-latest,glm-5.2,kimi-k2.7-code",
    )

    result = list_generation_models(None)

    assert result["default_model_id"] == "ark-code-latest"
    assert [model["id"] for model in result["models"]] == [
        "ark-code-latest",
        "glm-5.2",
        "kimi-k2.7-code",
    ]
    assert all(
        model["provider"] == "火山方舟 Coding Plan"
        for model in result["models"]
    )
