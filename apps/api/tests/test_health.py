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
    assert response.json()["ai_mode"] == "mock"


@pytest.mark.asyncio
async def test_mock_generation_starts_pending_cases() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/mock/generation-jobs",
            json={"prompt": "生成支付回调测试用例", "file_names": ["支付需求.docx"]},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["mode"] == "mock"
    assert body["test_cases"]
    assert all(case["status"] == "pending" for case in body["test_cases"])


@pytest.mark.asyncio
async def test_login_prompt_returns_login_test_cases() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/mock/generation-jobs",
            json={"prompt": "为手机号验证码登录生成用例"},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["test_cases"][0]["id"] == "AUTH-001"
    assert all(case["status"] == "pending" for case in body["test_cases"])
