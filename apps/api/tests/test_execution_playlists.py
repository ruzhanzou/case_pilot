from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, ExecutionRun, Space


@pytest.mark.asyncio
async def test_playlist_crud_search_execution_and_snapshot_survival() -> None:
    token = uuid4().hex
    account_id: str | None = None
    space_id: str | None = None
    run_id: str | None = None
    other_account_id: str | None = None
    other_space_id: str | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"playlist-{token}@casepilot.test",
                    "display_name": "Playlist 验收",
                    "password": "CasePilot123!",
                },
            )
            assert registered.status_code == 201
            account = registered.json()
            account_id = account["id"]
            space_id = account["spaces"][0]["id"]

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as other_client:
                other_registered = await other_client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"playlist-other-{token}@casepilot.test",
                        "display_name": "其他空间成员",
                        "password": "CasePilot123!",
                    },
                )
                assert other_registered.status_code == 201
                other_account = other_registered.json()
                other_account_id = other_account["id"]
                other_space_id = other_account["spaces"][0]["id"]
                forbidden = await other_client.get(
                    f"/api/v1/spaces/{space_id}/playlists"
                )
                assert forbidden.status_code == 403

            collections = await client.get(f"/api/v1/spaces/{space_id}/collections")
            assert collections.status_code == 200
            collection = collections.json()[0]

            created_case = await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "case_key": f"PLAY-{token[:8]}",
                    "title": "Playlist 搜索与执行",
                    "module": "执行管理",
                    "priority": "P1",
                    "case_type": "功能",
                    "tags": ["playlist", "回归"],
                    "preconditions": ["已创建空间"],
                    "steps": [
                        {
                            "id": "execute-playlist",
                            "action": "创建 Playlist 执行任务",
                            "expected": "任务包含选中的用例",
                        }
                    ],
                    "source": "自动化验收",
                },
            )
            assert created_case.status_code == 201
            test_case = created_case.json()

            searched = await client.get(
                f"/api/v1/spaces/{space_id}/test-cases",
                params={"q": "playlist 回归"},
            )
            assert searched.status_code == 200
            assert [item["id"] for item in searched.json()] == [test_case["id"]]

            created_playlist = await client.post(
                f"/api/v1/spaces/{space_id}/playlists",
                json={
                    "name": "执行回归",
                    "case_ids": [test_case["id"], test_case["id"]],
                    "source_collection_ids": [collection["id"]],
                },
            )
            assert created_playlist.status_code == 201
            playlist = created_playlist.json()
            assert playlist["case_count"] == 1

            duplicate_name = await client.post(
                f"/api/v1/spaces/{space_id}/playlists",
                json={
                    "name": "执行回归",
                    "case_ids": [test_case["id"]],
                    "source_collection_ids": [collection["id"]],
                },
            )
            assert duplicate_name.status_code == 201
            assert duplicate_name.json()["name"] == "执行回归 (2)"
            assert (
                await client.delete(f"/api/v1/playlists/{duplicate_name.json()['id']}")
            ).status_code == 204

            updated_playlist = await client.patch(
                f"/api/v1/playlists/{playlist['id']}",
                json={
                    "name": "执行回归 Playlist",
                    "case_ids": [test_case["id"]],
                    "source_collection_ids": [collection["id"]],
                },
            )
            assert updated_playlist.status_code == 200
            playlist = updated_playlist.json()

            created_run = await client.post(
                f"/api/v1/spaces/{space_id}/execution-runs",
                json={
                    "playlist_id": playlist["id"],
                    "description": "冻结 Playlist 当前 Revision",
                    "assignee_ids": [account_id],
                },
            )
            assert created_run.status_code == 200
            run = created_run.json()
            run_id = run["id"]
            assert run["source_type"] == "playlist"
            assert run["source_name"] == "执行回归 Playlist"
            assert run["source_collection_count"] == 1
            assert [item["test_case"]["id"] for item in run["records"]] == [
                test_case["id"]
            ]

            assert (await client.delete(f"/api/v1/test-cases/{test_case['id']}")).status_code == 204
            unavailable = await client.get(f"/api/v1/playlists/{playlist['id']}")
            assert unavailable.status_code == 200
            assert unavailable.json()["unavailable_case_ids"] == [test_case["id"]]
            blocked_run = await client.post(
                f"/api/v1/spaces/{space_id}/execution-runs",
                json={
                    "playlist_id": playlist["id"],
                    "description": "不可用 Playlist 不应执行",
                    "assignee_ids": [account_id],
                },
            )
            assert blocked_run.status_code == 409
            assert blocked_run.json()["detail"] == "playlist_contains_unavailable_cases"

            assert (await client.delete(f"/api/v1/playlists/{playlist['id']}")).status_code == 204
            historical_run = await client.get(f"/api/v1/execution-runs/{run['id']}")
            assert historical_run.status_code == 200
            assert historical_run.json()["source_name"] == "执行回归 Playlist"
    finally:
        if space_id or account_id or other_space_id or other_account_id:
            with get_session_factory()() as db:
                if run_id:
                    db.execute(delete(ExecutionRun).where(ExecutionRun.id == UUID(run_id)))
                if space_id:
                    db.execute(delete(Space).where(Space.id == UUID(space_id)))
                if other_space_id:
                    db.execute(delete(Space).where(Space.id == UUID(other_space_id)))
                if account_id:
                    db.execute(delete(Account).where(Account.id == UUID(account_id)))
                if other_account_id:
                    db.execute(
                        delete(Account).where(Account.id == UUID(other_account_id))
                    )
                db.commit()
