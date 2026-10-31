"""Real Redis progress/cancel alongside real transaction locks; scripted model only."""

import asyncio
import json
import threading
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from casepilot_api import conversations, workbench_tools
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import ConversationSubmission, GenerationJob, TaskOutbox
from casepilot_api.workbench_agent import FinalAnswer, ModelTurn, ToolCall
from casepilot_api.workbench_events import WorkbenchEventStore


@pytest.mark.asyncio
@pytest.mark.parametrize("after_preparation", [False, True])
async def test_live_progress_cancel_and_replay_are_exact_submission_scoped(
    monkeypatch, after_preparation
):
    entered, release = threading.Event(), threading.Event()

    class Provider:
        calls = 0

        def complete(self, messages, tools, instructions):
            self.calls += 1
            if self.calls == (3 if after_preparation else 2):
                entered.set()
                assert release.wait(10)
            if self.calls < 3:
                name = "get_workspace_context" if self.calls == 1 else "prepare_generation"
                arguments = ({} if name == "get_workspace_context" else {
                    "plan": {"steps": ["Prepare generation"], "plan_actions": ["CASE_GENERATE"]},
                })
                return ModelTurn(calls=[ToolCall(str(self.calls), name, json.dumps(arguments))])
            output = next(
                json.loads(item["output"])
                for item in reversed(messages)
                if item.get("type") == "function_call_output"
            )
            receipt = output["_receipt"]
            return ModelTurn(
                final=FinalAnswer(
                    kind="action",
                    message="请确认预览",
                    effect=receipt["effect"],
                    receipt_ids=[receipt["id"]],
                )
            )

    provider = Provider()
    monkeypatch.setattr(conversations.settings, "workbench_agent_enabled", True)
    monkeypatch.setattr(workbench_tools, "make_provider", lambda *args: provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"progress-{uuid4().hex}@casepilot.test",
                    "display_name": "Progress",
                    "password": "CasePilot123!",
                },
            )
        ).json()
        collection = (
            await client.post(
                f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
                json={"name": "Progress"},
            )
        ).json()
        conversation = (
            await client.post("/api/v1/conversations", json={"collection_id": collection["id"]})
        ).json()
        cid, request_id = conversation["id"], str(uuid4())
        request = {"content": "为手机号验证码登录生成测试用例", "client_request_id": request_id}
        url = f"/api/v1/conversations/{cid}/messages"
        task = asyncio.create_task(client.post(url, json=request))
        store = WorkbenchEventStore(account["id"], cid, request_id)
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            # Events are visible before the submission transaction commits.
            events = store.read()
            assert any(event["type"] == "model_started" for event in events)
            assert not store.is_terminal()
            assert not task.done()
            stopped = await asyncio.wait_for(
                client.post(f"/api/v1/conversations/{cid}/agent-runs/{request_id}/cancel"), 3
            )
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["status"] == "requested"
            assert stopped.json()["transport_aborted"] is False
        finally:
            release.set()
        response = await task
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["assistant_message"]["metadata"]["workbench_agent"]["status"] == "cancelled"
        calls = provider.calls
        replay = await client.post(url, json=request)
        assert replay.json() == body
        assert provider.calls == calls
        assert store.read()[-1]["type"] == "run_cancelled"
        stream = await client.get(f"/api/v1/conversations/{cid}/agent-runs/{request_id}/events")
        assert stream.status_code == 200
        assert "event: workbench.activity" in stream.text and "run_cancelled" in stream.text
        assert "image_url" not in stream.text and "arguments" not in stream.text
        with get_session_factory()() as db:
            assert db.get(ConversationSubmission, (UUID(cid), UUID(request_id))) is not None
            jobs = list(
                db.scalars(
                    select(GenerationJob).where(
                        GenerationJob.input_payload["conversation_id"].astext == cid
                    )
                )
            )
            if after_preparation:
                assert len(jobs) == 1 and jobs[0].status == "cancelled"
                outbox = db.scalar(select(TaskOutbox).where(TaskOutbox.task_id == str(jobs[0].id)))
                assert outbox.status == "cancelled"
            else:
                assert not jobs


@pytest.mark.asyncio
async def test_setup_failure_does_not_poison_same_request_retry(monkeypatch):
    from casepilot_api.workbench_agent import AgentProviderError

    class Provider:
        calls = 0

        def complete(self, messages, tools, instructions):
            self.calls += 1
            return ModelTurn(final=FinalAnswer(kind="answer", message="请描述测试目标。"))

    provider = Provider()
    attempts = 0

    def make_provider(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise AgentProviderError("agent_configuration_missing")
        return provider

    monkeypatch.setattr(conversations.settings, "workbench_agent_enabled", True)
    monkeypatch.setattr(workbench_tools, "make_provider", make_provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account = (await client.post("/api/v1/auth/register", json={
            "email": f"retry-{uuid4().hex}@casepilot.test",
            "display_name": "Retry", "password": "CasePilot123!",
        })).json()
        collection = (await client.post(
            f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
            json={"name": "Retry"},
        )).json()
        conversation = (await client.post(
            "/api/v1/conversations", json={"collection_id": collection["id"]},
        )).json()
        cid, request_id = conversation["id"], str(uuid4())
        store = WorkbenchEventStore(account["id"], cid, request_id)
        url = f"/api/v1/conversations/{cid}/messages"
        request = {"content": "你好", "client_request_id": request_id}
        failed = await client.post(url, json=request)
        assert failed.status_code == 503
        assert failed.json()["detail"] == "agent_configuration_missing"
        assert store.read() == [] and not store.is_terminal()
        with get_session_factory()() as db:
            assert db.get(ConversationSubmission, (UUID(cid), UUID(request_id))) is None
        retried = await client.post(url, json=request)
        assert retried.status_code == 202, retried.text
        assert store.read()[-1]["type"] == "run_completed"
        assert not any(event["type"] == "run_failed" for event in store.read())
        replay = await client.post(url, json=request)
        assert replay.json() == retried.json()
        assert provider.calls == 1 and attempts == 2
