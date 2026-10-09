from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select

from casepilot_api.case_management import collection_to_view
from casepilot_api.database import get_engine, get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CaseCollection


@pytest.mark.asyncio
async def test_collection_list_preserves_metadata_with_bounded_database_queries():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"collections-{uuid4().hex}@casepilot.test",
                "display_name": "Collection query regression",
                "password": "CasePilot123!",
            },
        )
        assert response.status_code == 201
        account = response.json()
        space = account["spaces"][0]["id"]
        ids = []
        for index in range(20):
            response = await client.post(
                f"/api/v1/spaces/{space}/collections", json={"name": f"Collection {index}"}
            )
            assert response.status_code == 201
            ids.append(response.json()["id"])
        created = await client.post(
            f"/api/v1/collections/{ids[0]}/test-cases",
            json={
                "title": "Preserved count",
                "module": "Login",
                "priority": "P1",
                "case_type": "功能",
                "preconditions": [],
                "steps": [{"action": "Login", "expected": "Session established"}],
            },
        )
        assert created.status_code == 201
        statements = []

        def record(*args):
            statements.append(args[2])

        engine = get_engine()
        event.listen(engine, "before_cursor_execute", record)
        try:
            response = await client.get(f"/api/v1/spaces/{space}/collections")
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200
        assert len(statements) <= 12, len(statements)
        views = response.json()
        created_views = [item for item in views if item["id"] in ids]
        assert [item["id"] for item in created_views] == ids
        assert [item["case_count"] for item in created_views] == [1] + [0] * 19
        with get_session_factory()() as db:
            collections = list(
                db.scalars(
                    select(CaseCollection)
                    .where(CaseCollection.space_id == space)
                    .order_by(CaseCollection.created_at)
                )
            )
            assert views == [
                collection_to_view(db, item).model_dump(mode="json") for item in collections
            ]
