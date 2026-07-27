import pytest
from httpx import ASGITransport, AsyncClient

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
    assert response.json()["generation"] == "disabled"


def test_case_management_routes_are_exposed() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/spaces/{space_id}/collections" in paths
    assert "/api/v1/collections/{collection_id}/test-cases" in paths
    assert "/api/v1/test-cases/{case_id}" in paths
    assert "/api/v1/collections/{collection_id}/execution-runs" in paths
    assert "/api/v1/execution-records/{record_id}" in paths


def test_generation_routes_are_not_exposed() -> None:
    paths = app.openapi()["paths"]

    assert all("/mock/" not in path for path in paths)
    assert all("generation-jobs" not in path for path in paths)
