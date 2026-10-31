"""Offline event channel contracts: no Redis, model, or credentials required."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from casepilot_api import workbench_events as events


class Redis:
    def __init__(self):
        self.values = {}
        self.expiries = {}

    def pipeline(self, **kwargs):
        return self

    def zadd(self, key, values, **kwargs):
        self.values.setdefault(key, {}).update(values)
        return self

    def expire(self, key, value):
        self.expiries[key] = value
        return self

    def set(self, key, value, ex):
        self.values[key] = value
        self.expiries[key] = ex
        return self

    def execute(self):
        pass

    def exists(self, key):
        return key in self.values

    def zrangebyscore(self, key, low, high):
        return [value for value, score in sorted(self.values.get(key, {}).items(),
                                                key=lambda pair: pair[1])
                if score > int(low[1:])]


def store(redis=None):
    return events.WorkbenchEventStore(uuid4(), uuid4(), uuid4(), client=redis or Redis())


def test_redacted_ordered_replay_and_ttl():
    channel = store()
    channel.publish({"sequence": 2, "type": "tool_completed", "tool": "prepare_rewrite",
                     "arguments": {"private": "body"}, "text": "private text"})
    channel.publish({"sequence": 1, "type": "run_started", "error_code": "secret error"})
    channel.publish({"sequence": 2, "type": "tool_completed", "tool": "prepare_rewrite"})
    assert channel.read() == [
        {"sequence": 1, "type": "run_started"},
        {"sequence": 2, "type": "tool_completed", "tool": "prepare_rewrite"},
    ]
    assert len(channel.read(1)) == 1
    assert "private" not in json.dumps(channel.client.values)
    assert set(channel.client.expiries.values()) == {900}
    assert not channel.publish({"sequence": 1001, "type": "run_started"})
    assert not channel.publish({"sequence": 1, "type": "private body"})


def test_cancel_exact_run_terminal_and_redis_failure():
    redis = Redis()
    first, other = store(redis), store(redis)
    assert first.request_cancel() == "requested"
    assert first.is_cancelled()
    assert not other.is_cancelled()
    first.publish({"sequence": 3, "type": "run_completed"})
    assert first.request_cancel() == "already_terminal"

    class Broken(Redis):
        def pipeline(self, **kwargs):
            raise ConnectionError("private backend error")

        def exists(self, key):
            raise ConnectionError("private backend error")

    unavailable = store(Broken())
    assert not unavailable.publish({"sequence": 1, "type": "run_started"})
    assert not unavailable.is_cancelled()


@pytest.mark.parametrize("missing", [True, False])
def test_other_account_cannot_read_or_cancel_before_redis(monkeypatch, missing):
    account = SimpleNamespace(id=uuid4())
    conversation = None if missing else SimpleNamespace(account_id=uuid4())
    db = SimpleNamespace(get=lambda *args: conversation, scalar=lambda *args: None,
                         commit=lambda: None)
    from casepilot_api import workbench_continuation
    monkeypatch.setattr(workbench_continuation, "cancel_initial_reservation", lambda *args: None)
    monkeypatch.setattr(events, "WorkbenchEventStore", lambda *args: pytest.fail("Redis accessed"))
    with pytest.raises(HTTPException) as error:
        events.authorized_store(db, account, uuid4(), uuid4())
    assert error.value.status_code == 404


def test_membership_required_before_redis(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    conversation = SimpleNamespace(account_id=account.id, space_id=uuid4())
    db = SimpleNamespace(get=lambda *args: conversation, scalar=lambda *args: None,
                         commit=lambda: None)
    from casepilot_api import workbench_continuation
    monkeypatch.setattr(workbench_continuation, "cancel_initial_reservation", lambda *args: None)

    def forbidden(*args):
        raise HTTPException(403, "space_access_denied")

    monkeypatch.setattr(events, "require_space_membership", forbidden)
    monkeypatch.setattr(events, "WorkbenchEventStore", lambda *args: pytest.fail("Redis accessed"))
    with pytest.raises(HTTPException) as error:
        events.authorized_store(db, account, uuid4(), uuid4())
    assert error.value.status_code == 403


def test_stream_replays_terminal_and_disconnects():
    async def collect():
        channel = store()
        channel.publish({"sequence": 1, "type": "run_started"})
        channel.publish({"sequence": 2, "type": "run_completed"})

        async def connected():
            return False

        request = SimpleNamespace(is_disconnected=connected)
        output = [item async for item in events.event_stream(request, channel, 1)]
        assert len(output) == 1
        assert "id: 2\nevent: workbench.activity" in output[0]
        assert [item async for item in events.event_stream(request, channel, 2)] == []

        async def disconnected():
            return True

        request.is_disconnected = disconnected
        assert [item async for item in events.event_stream(request, channel)] == []

    asyncio.run(collect())


def test_http_routes_authorize_owner_then_replay_and_cancel(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from casepilot_api.auth import require_account
    from casepilot_api.database import get_db_session

    app = FastAPI()
    app.include_router(events.router)
    account = SimpleNamespace(id=uuid4())
    conversation = SimpleNamespace(account_id=account.id, space_id=uuid4())
    db = SimpleNamespace(get=lambda *args: conversation, scalar=lambda *args: None,
                         commit=lambda: None)
    from casepilot_api import workbench_continuation
    monkeypatch.setattr(workbench_continuation, "cancel_initial_reservation", lambda *args: None)
    released = []
    db.close = lambda: released.append(True)
    app.dependency_overrides[require_account] = lambda: account
    app.dependency_overrides[get_db_session] = lambda: db
    channel = store()
    monkeypatch.setattr(events, "require_space_membership", lambda *args: None)
    monkeypatch.setattr(events, "WorkbenchEventStore", lambda *args: channel)
    original_read = channel.read

    def read_after_release(cursor=0):
        assert released, "DB connection must be released before first Redis stream read"
        return original_read(cursor)

    channel.read = read_after_release
    path = f"/api/v1/conversations/{uuid4()}/agent-runs/{uuid4()}"
    with TestClient(app) as client:
        assert client.post(path + "/cancel").json() == {
            "status": "requested", "transport_aborted": False,
        }
        channel.publish({"sequence": 1, "type": "run_started"})
        channel.publish({"sequence": 2, "type": "run_cancelled"})
        response = client.get(path + "/events", headers={"Last-Event-ID": "1"})
        assert response.status_code == 200
        assert released == [True]
        assert "run_cancelled" in response.text and "run_started" not in response.text
        assert client.post(path + "/cancel").json()["status"] == "already_terminal"
        assert client.get(path + "/events?cursor=-1").status_code == 422
        assert client.get(path + "/events", headers={"Last-Event-ID": "bad"}).status_code == 422
        conversation.account_id = uuid4()
        assert client.get(path + "/events").status_code == 404
        assert client.post(path + "/cancel").status_code == 404


def test_malformed_optional_event_fields_are_dropped():
    assert events.safe_event({"type": []}) is None
    assert events.safe_event({"type": "run_started", "sequence": 1,
                              "tool": {}, "error_code": []}) == {
        "type": "run_started", "sequence": 1,
    }


@pytest.mark.parametrize("tool", ["query_uploaded_cases", "preview_uploaded_cases"])
def test_uploaded_case_tool_events_expose_name_not_file_content(tool):
    channel = store()
    channel.publish({"sequence": 1, "type": "tool_completed", "tool": tool,
                     "arguments": {"file_content": "synthetic private evidence"},
                     "result": {"snapshot": "synthetic private row"}})
    assert channel.read() == [{"sequence": 1, "type": "tool_completed", "tool": tool}]


def test_collection_delete_event_does_not_expose_private_impact():
    channel = store()
    channel.publish({"sequence": 1, "type": "tool_completed", "tool": "delete_collection",
                     "result": {"private_conversation_ids": ["synthetic-private"]}})
    assert channel.read() == [{"sequence": 1, "type": "tool_completed",
                               "tool": "delete_collection"}]


def test_collection_navigation_event_is_redacted():
    channel = store()
    channel.publish({"sequence": 1, "type": "tool_completed", "tool": "select_collection",
                     "arguments": {"collection_id": "synthetic-private-id"}})
    assert channel.read() == [{"sequence": 1, "type": "tool_completed",
                               "tool": "select_collection"}]


def test_query_and_final_diagnostics_are_strictly_allowlisted():
    query = events.safe_event({"sequence": 1, "type": "tool_completed", "tool": "query_assets",
                               "returned_count": 0, "truncated": False, "has_more": True,
                               "arguments": {"search": "private"}, "text": "private"})
    assert query == {"sequence": 1, "type": "tool_completed", "tool": "query_assets",
                     "returned_count": 0, "truncated": False, "has_more": True}
    terminal = events.safe_event({"sequence": 2, "type": "run_awaiting_input",
                                  "final_kind": "clarify", "final_effect": "read",
                                  "final_message": "private model text"})
    assert terminal == {"sequence": 2, "type": "run_awaiting_input",
                        "final_kind": "clarify", "final_effect": "read"}
    invalid = events.safe_event({"sequence": 3, "type": "tool_completed", "tool": "query_assets",
                                 "returned_count": True, "truncated": "private", "has_more": 1,
                                 "final_kind": "private", "final_effect": {"private": True}})
    assert invalid == {"sequence": 3, "type": "tool_completed", "tool": "query_assets"}
