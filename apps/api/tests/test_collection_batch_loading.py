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


@pytest.mark.asyncio
async def test_routing_catalog_retains_old_current_and_named_collections_without_crossing_space():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from uuid import UUID
    from casepilot_api.conversations import _collection_catalog
    from casepilot_api.models import Space
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        registered = await client.post('/api/v1/auth/register', json={
            'email': f'catalog-{uuid4().hex}@casepilot.test', 'display_name': 'Catalog boundary', 'password': 'CasePilot123!'})
        space_id = UUID(registered.json()['spaces'][0]['id'])
    with get_session_factory()() as db:
        other_space = Space(name='Other space')
        db.add(other_space); db.flush()
        now = datetime.now(UTC)
        current = CaseCollection(space_id=space_id, name='旧当前集合', created_at=now-timedelta(days=3))
        mentioned = CaseCollection(space_id=space_id, name='Legacy %_ 收款', created_at=now-timedelta(days=4))
        unrelated = CaseCollection(space_id=space_id, name='无关旧集合', created_at=now-timedelta(days=5))
        deleted = CaseCollection(space_id=space_id, name=mentioned.name, deleted_at=now, created_at=now)
        foreign = CaseCollection(space_id=other_space.id, name=mentioned.name, created_at=now)
        recent = [CaseCollection(space_id=space_id, name=f'近期集合 {i}', created_at=now+timedelta(seconds=i)) for i in range(100)]
        db.add_all([current, mentioned, unrelated, deleted, foreign, *recent]); db.flush()
        conversation = SimpleNamespace(space_id=space_id, collection_id=current.id)
        ordinary = _collection_catalog(db, conversation)
        assert str(current.id) in {c['id'] for c in ordinary}
        assert len(ordinary) == 101
        named = _collection_catalog(db, conversation, '请在「LEGACY %_ 收款」集合修改用例')
        ids = {c['id'] for c in named}
        assert ids == {str(c.id) for c in [current, mentioned, *recent]}
        assert not ids.intersection({str(c.id) for c in [unrelated, deleted, foreign]})
        assert len(ids) == len(named)
        literal = _collection_catalog(db, conversation, 'Legacy abc 收款只是业务名称')
        assert str(mentioned.id) not in {c['id'] for c in literal}
        db.rollback()
