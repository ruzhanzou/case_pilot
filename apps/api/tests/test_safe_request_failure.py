import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.failure_diagnostics import failure_diagnostic
from casepilot_api.main import app
from casepilot_api.models import ConversationMessage, ConversationSubmission, GenerationJob


def test_failure_projection_drops_unknown_context_and_exception_content():
    marker = "PRIVATE_HEADER SQL_PARAMETERS SECRET"
    try:
        raise ValueError(marker)
    except ValueError as error:
        diagnostic = failure_diagnostic(error, {
            "request_id": str(uuid4()), "turn_id": marker, "account_id": str(uuid4()),
            "headers": marker, "raw": marker,
        })
    assert diagnostic["exception_class"] == "ValueError"
    assert marker not in json.dumps(diagnostic)
    assert set(diagnostic) == {"phase", "error_code", "exception_class", "frames", "request_id"}


@pytest.mark.asyncio
async def test_unhandled_submission_failure_is_correlated_and_atomic_then_replayable(
    monkeypatch, caplog,
):
    monkeypatch.setattr(conversations, "enqueue_task", lambda *args, **kwargs: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user = (await client.post("/api/v1/auth/register", json={
            "email": f"safe-failure-{uuid4().hex}@casepilot.test",
            "display_name": "Synthetic safe diagnostic", "password": "CasePilot123!",
        })).json()
        collection = (await client.post(
            f"/api/v1/spaces/{user['spaces'][0]['id']}/collections",
            json={"name": "Synthetic failure"},
        )).json()
        conversation = (await client.post("/api/v1/conversations", json={
            "collection_id": collection["id"],
        })).json()
        cid = UUID(conversation["id"])
        url = f"/api/v1/conversations/{cid}/messages"
        payload = {"content": "生成1条登录测试用例", "intent_override": "CASE_GENERATE",
                   "client_request_id": str(uuid4())}
        original = conversations._send_message

        def fail_after_preparation(*args):
            original(*args)
            raise RuntimeError("PRIVATE_HEADER SQL_PARAMETERS SECRET")

        monkeypatch.setattr(conversations, "_send_message", fail_after_preparation)
        response = await client.post(url, json=payload, headers={"X-Request-ID": "PRIVATE"})
        assert response.status_code == 500
        request_id = response.json()["request_id"]
        assert UUID(request_id) and response.headers["X-Request-ID"] == request_id
        records = [json.loads(r.message) for r in caplog.records
                   if r.name == "casepilot.safe_failure"]
        diagnostic = next(r for r in records if r["request_id"] == request_id)
        assert diagnostic["client_request_id"] == payload["client_request_id"]
        assert diagnostic["conversation_id"] == str(cid)
        assert diagnostic["exception_class"] == "RuntimeError"
        assert any(f["function"] == "send_message" for f in diagnostic["frames"])
        assert "PRIVATE" not in json.dumps(diagnostic) and "SECRET" not in response.text
        assert "account_id" not in diagnostic
        with get_session_factory()() as db:
            for model in (ConversationMessage, ConversationSubmission):
                assert db.scalar(select(func.count()).select_from(model).where(
                    model.conversation_id == cid)) == 0
            assert db.scalar(select(func.count()).select_from(GenerationJob).where(
                GenerationJob.collection_id == UUID(collection["id"]))) == 0
        monkeypatch.setattr(conversations, "_send_message", original)
        retry = await client.post(url, json=payload)
        assert retry.status_code == 202
        replay = await client.post(url, json=payload)
        assert replay.status_code == 202 and replay.json() == retry.json()
