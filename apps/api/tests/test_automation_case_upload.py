from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Space


@pytest.mark.asyncio
async def test_upload_multiple_automation_cases_and_clear_bindings() -> None:
    token = uuid4().hex
    account_id: str | None = None
    space_id: str | None = None
    other_account_id: str | None = None
    other_space_id: str | None = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registration = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"automation-{token}@casepilot.test",
                    "display_name": "Automation Binder",
                    "password": "CasePilot123!",
                },
            )
            assert registration.status_code == 201
            account_id = registration.json()["id"]
            space_id = registration.json()["spaces"][0]["id"]
            collection_response = await client.get(f"/api/v1/spaces/{space_id}/collections")
            assert collection_response.status_code == 200
            collection_id = collection_response.json()[0]["id"]
            created = await client.post(
                f"/api/v1/collections/{collection_id}/test-cases",
                json={
                    "title": "登录验证",
                    "module": "认证",
                    "steps": [{"action": "登录", "expected": "登录成功"}],
                },
            )
            assert created.status_code == 201
            case_id = created.json()["id"]
            path = f"/api/v1/test-cases/{case_id}/automation-cases/upload"
            first = {
                "creator": "张三",
                "git": "https://example.com/automation.git",
                "branch": "main",
                "commit": "a" * 40,
                "case_name": "tests/login.py::test_success",
                "create_time": "2026-09-10T09:00:00+08:00",
                "update_time": "2026-09-17T10:00:00+08:00",
            }
            second = {**first, "case_name": "tests/login.py::test_failure"}

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as other_client:
                other = await other_client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"automation-other-{token}@casepilot.test",
                        "display_name": "Other Binder",
                        "password": "CasePilot123!",
                    },
                )
                assert other.status_code == 201
                other_account_id = other.json()["id"]
                other_space_id = other.json()["spaces"][0]["id"]
                assert (await other_client.post(path, json=[first])).status_code == 403

            duplicate = await client.post(path, json=[first, first])
            assert duplicate.status_code == 422
            saved = await client.post(path, json=[first, second])
            assert saved.status_code == 200
            assert saved.json()["automation_type"] == "automated"
            assert len(saved.json()["automation_cases"]) == 2
            assert saved.json()["revision_number"] == 2

            repeated = await client.post(path, json=[first, second])
            assert repeated.status_code == 200
            assert repeated.json()["revision_number"] == 2
            retrieved = await client.get(f"/api/v1/test-cases/{case_id}")
            assert retrieved.json()["automation_cases"] == saved.json()["automation_cases"]

            edited = await client.patch(
                f"/api/v1/test-cases/{case_id}",
                json={
                    "base_revision_id": saved.json()["current_revision_id"],
                    "title": "登录验证更新",
                    "module": "认证",
                    "steps": [{"action": "登录", "expected": "登录成功"}],
                },
            )
            assert edited.status_code == 200
            assert len(edited.json()["automation_cases"]) == 2
            assert edited.json()["automation_type"] == "automated"

            cleared = await client.post(path, json=[])
            assert cleared.status_code == 200
            assert cleared.json()["automation_type"] == "manual"
            assert cleared.json()["automation_cases"] == []
            assert cleared.json()["revision_number"] == 4
    finally:
        with get_session_factory()() as db:
            if space_id:
                db.execute(delete(Space).where(Space.id == UUID(space_id)))
            if other_space_id:
                db.execute(delete(Space).where(Space.id == UUID(other_space_id)))
            if account_id:
                db.execute(delete(Account).where(Account.id == UUID(account_id)))
            if other_account_id:
                db.execute(delete(Account).where(Account.id == UUID(other_account_id)))
            db.commit()
