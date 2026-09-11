from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from casepilot_api import integrations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    CallbackDelivery,
    CaseGenerationSession,
    ExecutionRun,
    GenerationJob,
    Space,
    TaskOutbox,
)

SERVICE_HEADERS = {"Authorization": "Bearer case-service-local"}
TOOL_HEADERS = {"Authorization": "Bearer test-tool-local"}


@pytest.mark.asyncio
async def test_testweb_mock_generation_and_testtool_execution_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = uuid4().hex
    account_id: str | None = None
    space_id: str | None = None
    visitor_account_id: str | None = None
    visitor_space_id: str | None = None
    project_public_id: str | None = None
    generation_id: str | None = None
    regenerated_id: str | None = None
    real_generation_id: str | None = None
    task_id: str | None = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"testtool-{token}@casepilot.test",
                    "display_name": "TestTool User",
                    "password": "CasePilot123!",
                },
            )
            assert registered.status_code == 201
            account = registered.json()
            account_id = account["id"]
            space_id = account["spaces"][0]["id"]
            tool_headers = {**TOOL_HEADERS, "X-TestTool-User-ID": account["email"]}

            unauthorized = await client.post(
                "/case-projects",
                headers={"Authorization": "Bearer wrong"},
                json={
                    "source_system": "test_web",
                    "space_id": space_id,
                    "test_target": {
                        "target_type": "fr_test",
                        "target_id": 1,
                        "title": "unauthorized",
                    },
                },
            )
            assert unauthorized.status_code == 401

            target_id = int(token[:10], 16)
            target = {
                "target_type": "fr_test",
                "target_id": target_id,
                "target_key": f"FR-{token[:8]}",
                "title": "Speaker diarization detect device owner",
                "linked_fr_ids": [],
                "linked_qpm_ids": [],
            }
            created = await client.post(
                "/case-projects",
                headers=SERVICE_HEADERS,
                json={
                    "source_system": "test_web",
                    "space_id": space_id,
                    "test_target": target,
                    "test_context": {"platform": "mock-lab"},
                },
            )
            assert created.status_code == 201
            project_public_id = created.json()["case_project_id"]
            assert project_public_id.startswith("CP-")
            project_url = urlsplit(created.json()["case_platform_url"])
            assert project_url.path == f"/case-projects/{project_public_id}"
            access_token = parse_qs(project_url.query)["access_token"][0]

            navigation = await client.get(
                f"/api/v1/case-projects/{project_public_id}"
            )
            assert navigation.status_code == 200
            assert navigation.json()["case_project_id"] == project_public_id
            assert navigation.json()["space_id"] == space_id
            assert navigation.json()["collection_id"]
            assert navigation.json()["test_target"] == target

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as visitor_client:
                visitor_registration = await visitor_client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"case-link-visitor-{token}@casepilot.test",
                        "display_name": "Case Link Visitor",
                        "password": "CasePilot123!",
                    },
                )
                assert visitor_registration.status_code == 201
                visitor_account_id = visitor_registration.json()["id"]
                visitor_space_id = visitor_registration.json()["spaces"][0]["id"]
                denied_navigation = await visitor_client.get(
                    f"/api/v1/case-projects/{project_public_id}"
                )
                assert denied_navigation.status_code == 403
                granted_navigation = await visitor_client.get(
                    f"/api/v1/case-projects/{project_public_id}",
                    params={"access_token": access_token},
                )
                assert granted_navigation.status_code == 200
                repeated_navigation = await visitor_client.get(
                    f"/api/v1/case-projects/{project_public_id}"
                )
                assert repeated_navigation.status_code == 200

            duplicate = await client.post(
                "/case-projects",
                headers=SERVICE_HEADERS,
                json={
                    "source_system": "test_web",
                    "space_id": space_id,
                    "test_target": target,
                    "test_context": {},
                },
            )
            assert duplicate.status_code == 201
            assert duplicate.json()["case_project_id"] == project_public_id

            generated = await client.post(
                f"/case-projects/{project_public_id}/case-generation-jobs",
                headers=SERVICE_HEADERS,
                json={"test_target": target, "test_context": {"build_version": "mock-1"}},
            )
            assert generated.status_code == 202
            assert generated.json()["case_generation_status"] == "generating"
            generation_id = generated.json()["case_generation_id"]

            summary_get = await client.get(
                f"/case-projects/{project_public_id}/case-summary",
                headers=SERVICE_HEADERS,
            )
            summary_post = await client.post(
                f"/case-projects/{project_public_id}/case-summary",
                headers=SERVICE_HEADERS,
            )
            assert summary_get.status_code == summary_post.status_code == 200
            assert summary_get.json() == summary_post.json()
            summary = summary_get.json()
            assert summary["generation_status"] == "approved"
            assert [item["stage"] for item in summary["cases"].values()] == [
                "L0",
                "L2",
                "L4",
            ]

            task_request_id = str(uuid4())
            task_request = {
                "test_target": target,
                "test_context": {"build_version": "mock-1"},
                "task_context": {
                    "tester": account["email"],
                    "execution_notes": "Run L2 regression scope",
                    "execution_level": "L2",
                },
                "task_request_id": task_request_id,
                "case_generation_id": generation_id,
                "callback_url": "https://caller.example.test/hooks/task",
                "callback_events": ["task-status", "case-execution-status"],
                "callback_correlation_id": "task-correlation",
            }
            task_created = await client.post(
                f"/case-projects/{project_public_id}/tasks",
                headers=SERVICE_HEADERS,
                json=task_request,
            )
            assert task_created.status_code == 202
            task_id = task_created.json()["test_task_id"]
            assert task_created.json()["execution_status"] == "pending_confirmation"
            repeated = await client.post(
                f"/case-projects/{project_public_id}/tasks",
                headers=SERVICE_HEADERS,
                json=task_request,
            )
            assert repeated.status_code == 202
            assert repeated.json()["test_task_id"] == task_id

            regenerated = await client.post(
                f"/case-projects/{project_public_id}/case-generation-jobs",
                headers=SERVICE_HEADERS,
                json={"test_target": target, "test_context": {"build_version": "mock-2"}},
            )
            assert regenerated.status_code == 202
            regenerated_id = regenerated.json()["case_generation_id"]
            latest_summary = await client.get(
                f"/case-projects/{project_public_id}/case-summary",
                headers=SERVICE_HEADERS,
            )
            assert latest_summary.status_code == 200
            assert latest_summary.json()["case_generation_id"] == regenerated_id
            assert len(latest_summary.json()["cases"]) == 3

            confirmed = await client.post(
                f"/api/v1/integration-task-requests/{task_request_id}/confirm",
                json={"execution_level": "L2"},
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["execution_status"] == "confirmed"
            assert {item["stage"] for item in confirmed.json()["cases"].values()} == {
                "L0",
                "L2",
            }

            listed = await client.get(
                "/api/test-tool/v1/tasks",
                headers=tool_headers,
                params={
                    "target_type": "fr_test",
                    "case_id": next(iter(confirmed.json()["cases"])),
                },
            )
            assert listed.status_code == 200
            assert [item["test_task_id"] for item in listed.json()["items"]] == [task_id]

            claimed = await client.post(
                f"/api/test-tool/v1/tasks/{task_id}/claim",
                headers=tool_headers,
                json={"worker_id": "mock-worker", "lease_seconds": 60},
            )
            assert claimed.status_code == 200
            lease_token = claimed.json()["lease_token"]
            assert claimed.json()["execution_status"] == "running"

            heartbeat = await client.post(
                f"/api/test-tool/v1/tasks/{task_id}/heartbeat",
                headers={**tool_headers, "X-Lease-Token": lease_token},
                json={"worker_id": "mock-worker", "lease_seconds": 60},
            )
            assert heartbeat.status_code == 200

            updated_at = datetime.now(UTC) + timedelta(seconds=2)
            case_updates = {}
            for index, case_id in enumerate(confirmed.json()["cases"]):
                case_updates[case_id] = {
                    "status": "passed" if index == 0 else "failed",
                    "updated_at": updated_at.isoformat(),
                    "actual_result": "mock result",
                    "completed_step_ids": [],
                    "cr": "CR343255" if index else "",
                    "logs": [{"message": "mock log"}],
                    "artifacts": [],
                }
            update_id = str(uuid4())
            task_update = {
                "update_id": update_id,
                "lease_token": lease_token,
                "status": "completed",
                "updated_at": updated_at.isoformat(),
                "cases_complete": True,
                "cases": case_updates,
                "logs": [{"message": "complete"}],
                "artifacts": [],
            }
            updated = await client.patch(
                f"/api/test-tool/v1/tasks/{task_id}", headers=tool_headers, json=task_update
            )
            assert updated.status_code == 200
            assert updated.json()["execution_status"] == "completed"
            assert {item["status"] for item in updated.json()["cases"].values()} == {
                "passed",
                "failed",
            }
            idempotent = await client.patch(
                f"/api/test-tool/v1/tasks/{task_id}", headers=tool_headers, json=task_update
            )
            assert idempotent.status_code == 200
            assert idempotent.json() == updated.json()

            case_id = next(iter(updated.json()["cases"]))
            single_case = await client.get(
                f"/api/test-tool/v1/tasks/{task_id}/cases/{case_id}",
                headers=tool_headers,
            )
            assert single_case.status_code == 200
            assert single_case.json()["case_id"] == case_id

            with get_session_factory()() as db:
                callback_count = db.scalar(
                    select(func.count())
                    .select_from(CallbackDelivery)
                    .where(CallbackDelivery.aggregate_id.in_([generation_id, task_id]))
                )
                assert callback_count >= 5
                task_callbacks = list(
                    db.scalars(
                        select(CallbackDelivery).where(
                            CallbackDelivery.aggregate_id == task_id
                        )
                    )
                )
                assert task_callbacks
                assert {item.event_type for item in task_callbacks} == {
                    "task-status",
                    "case-execution-status",
                }
                assert {
                    callback.callback_url for callback in task_callbacks
                } == {"https://caller.example.test/hooks/task"}
                assert {
                    callback.payload["callback_correlation_id"]
                    for callback in task_callbacks
                } == {"task-correlation"}

            monkeypatch.setattr(integrations.settings, "case_service_mock_mode", False)
            real_generation = await client.post(
                f"/case-projects/{project_public_id}/case-generation-jobs",
                headers=SERVICE_HEADERS,
                json={
                    "test_target": target,
                    "test_context": {"build_version": "real-queue-branch"},
                    "model_id": "auto",
                    "callback_url": "https://caller.example.test/hooks/generation",
                    "callback_events": ["generation-status", "case-summary"],
                    "callback_correlation_id": "real-generation-correlation",
                },
            )
            assert real_generation.status_code == 202
            real_generation_id = real_generation.json()["case_generation_id"]
            with get_session_factory()() as db:
                generation = db.scalar(
                    select(CaseGenerationSession).where(
                        CaseGenerationSession.public_id == real_generation_id
                    )
                )
                assert generation is not None
                assert generation.status == "generating"
                assert generation.generation_job_id is not None
                job = db.get(GenerationJob, generation.generation_job_id)
                assert job is not None
                assert job.status.value == "queued"
                assert job.input_payload["integration_generation_id"] == str(generation.id)
                assert (
                    job.input_payload["integration_callback_url"]
                    == "https://caller.example.test/hooks/generation"
                )
                assert job.input_payload["integration_callback_events"] == [
                    "generation-status",
                    "case-summary",
                ]
                assert (
                    job.input_payload["integration_callback_correlation_id"]
                    == "real-generation-correlation"
                )
                outbox = db.scalar(
                    select(TaskOutbox).where(TaskOutbox.task_id == str(job.id))
                )
                assert outbox is not None
                assert outbox.task_name == "casepilot.agent.generate"
        finally:
            with get_session_factory()() as db:
                callback_aggregate_ids = [
                    value
                    for value in (
                        project_public_id,
                        generation_id,
                        regenerated_id,
                        real_generation_id,
                        task_id,
                    )
                    if value
                ]
                if callback_aggregate_ids:
                    db.execute(
                        delete(CallbackDelivery).where(
                            CallbackDelivery.aggregate_id.in_(callback_aggregate_ids)
                        )
                    )
                for cleanup_space_id in (space_id, visitor_space_id):
                    if cleanup_space_id:
                        db.execute(
                            delete(ExecutionRun).where(
                                ExecutionRun.space_id == UUID(cleanup_space_id)
                            )
                        )
                        db.execute(delete(Space).where(Space.id == UUID(cleanup_space_id)))
                for cleanup_account_id in (account_id, visitor_account_id):
                    if cleanup_account_id:
                        db.execute(
                            delete(Account).where(Account.id == UUID(cleanup_account_id))
                        )
                db.commit()


@pytest.mark.asyncio
async def test_v14_caller_callbacks_and_playlist_creation_flow() -> None:
    token = uuid4().hex
    account_id: str | None = None
    space_id: str | None = None
    generation_id: str | None = None
    playlist_creation_id: str | None = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"playlist-creator-{token}@casepilot.test",
                    "display_name": "Playlist Creator",
                    "password": "CasePilot123!",
                },
            )
            assert registered.status_code == 201
            account = registered.json()
            account_id = account["id"]
            space_id = account["spaces"][0]["id"]
            target = {
                "target_type": "fr_test",
                "target_id": int(token[:10], 16),
                "target_key": f"FR-{token[:8]}",
                "title": "Caller callback integration",
                "linked_fr_ids": [],
                "linked_qpm_ids": [],
            }
            created = await client.post(
                "/case-projects",
                headers=SERVICE_HEADERS,
                json={
                    "source_system": "test_web",
                    "space_id": space_id,
                    "test_target": target,
                    "test_context": {},
                },
            )
            assert created.status_code == 201
            project_id = created.json()["case_project_id"]

            callback_url = "https://caller.example/hooks/case-generation"
            generated = await client.post(
                f"/case-projects/{project_id}/case-generation-jobs",
                headers=SERVICE_HEADERS,
                json={
                    "test_target": target,
                    "callback_url": callback_url,
                    "callback_events": ["generation-status"],
                    "callback_correlation_id": f"generation-{token}",
                },
            )
            assert generated.status_code == 202
            assert generated.json()["callback_correlation_id"] == f"generation-{token}"
            generation_id = generated.json()["case_generation_id"]
            summary = await client.get(
                f"/case-projects/{project_id}/case-summary", headers=SERVICE_HEADERS
            )
            assert summary.status_code == 200
            case_ids = list(summary.json()["cases"])

            with get_session_factory()() as db:
                deliveries = list(
                    db.scalars(
                        select(CallbackDelivery).where(
                            CallbackDelivery.aggregate_id == generation_id
                        )
                    )
                )
                assert deliveries
                assert {item.event_type for item in deliveries} == {"generation-status"}
                assert {item.callback_url for item in deliveries} == {callback_url}
                assert all(
                    item.payload["callback_correlation_id"] == f"generation-{token}"
                    and item.payload["event_id"] == str(item.event_id)
                    for item in deliveries
                )

            playlist_callback_url = "https://caller.example/hooks/playlist"
            started = await client.post(
                f"/case-projects/{project_id}/playlist-creation-sessions",
                headers=SERVICE_HEADERS,
                json={
                    "creator": account["email"].split("@", 1)[0],
                    "test_target": target,
                    "case_collections": [
                        {
                            "case_project_id": project_id,
                            "case_generation_id": generation_id,
                        }
                    ],
                    "playlist": {
                        "name": "Prefilled regression",
                        "case_ids": case_ids[:2],
                        "execution_notes": "Run the caller-selected scope",
                    },
                    "callback_url": playlist_callback_url,
                    "callback_correlation_id": f"playlist-{token}",
                    "callback_context": {"request_id": f"REQ-{token}"},
                },
            )
            assert started.status_code == 201
            playlist_creation_id = started.json()["playlist_creation_id"]
            assert f"playlist_creation_id={playlist_creation_id}" in started.json()[
                "case_platform_url"
            ]

            prefill = await client.get(
                f"/api/v1/playlist-creation-sessions/{playlist_creation_id}"
            )
            assert prefill.status_code == 200
            assert prefill.json()["creator"]["email"] == account["email"]
            assert prefill.json()["playlist"]["case_ids"] == case_ids[:2]
            collection_id = prefill.json()["case_collections"][0]["collection_id"]

            completed = await client.post(
                f"/api/v1/playlist-creation-sessions/{playlist_creation_id}/complete",
                json={
                    "name": "Caller regression playlist",
                    "description": "Created from the TestWeb hand-off",
                    "case_ids": case_ids[:2],
                    "execution_notes": "Run the caller-selected scope",
                },
            )
            assert completed.status_code == 201
            playlist = completed.json()["playlist"]
            assert completed.json()["creation_status"] == "created"
            assert playlist["case_count"] == 2
            assert playlist["creator"]["id"] == account_id

            repeated = await client.post(
                f"/api/v1/playlist-creation-sessions/{playlist_creation_id}/complete",
                json={"name": "ignored", "case_ids": case_ids[:1]},
            )
            assert repeated.status_code == 201
            assert repeated.json()["playlist"]["playlist_id"] == playlist["playlist_id"]

            listed = await client.get(
                f"/case-projects/{project_id}/playlist-tasks",
                headers=SERVICE_HEADERS,
                params={
                    "creator": "Playlist Creator",
                    "target_type": "fr_test",
                    "target_id": target["target_id"],
                    "collection_id": collection_id,
                    "playlist_id": playlist["playlist_id"],
                    "status": "ready",
                },
            )
            assert listed.status_code == 200
            assert [item["playlist_id"] for item in listed.json()["items"]] == [
                playlist["playlist_id"]
            ]
            assert listed.json()["items"][0]["task"] is None

            with get_session_factory()() as db:
                callback = db.scalar(
                    select(CallbackDelivery).where(
                        CallbackDelivery.aggregate_id == playlist_creation_id,
                        CallbackDelivery.event_type == "playlist-created",
                    )
                )
                assert callback is not None
                assert callback.callback_url == playlist_callback_url
                assert callback.payload["event_id"] == str(callback.event_id)
                assert callback.payload["callback_correlation_id"] == f"playlist-{token}"
                assert callback.payload["callback_context"]["request_id"] == f"REQ-{token}"
        finally:
            with get_session_factory()() as db:
                aggregate_ids = [value for value in (generation_id, playlist_creation_id) if value]
                if aggregate_ids:
                    db.execute(
                        delete(CallbackDelivery).where(
                            CallbackDelivery.aggregate_id.in_(aggregate_ids)
                        )
                    )
                if space_id:
                    db.execute(delete(Space).where(Space.id == UUID(space_id)))
                if account_id:
                    db.execute(delete(Account).where(Account.id == UUID(account_id)))
                db.commit()
