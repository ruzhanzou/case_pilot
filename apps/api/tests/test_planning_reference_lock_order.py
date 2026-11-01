"""Real two-session lock interleaving through production binding/update functions."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, current_thread
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from test_collection_references import source
from test_planning_review_lifecycle import PLAN
from test_workbench_bridge_integration import setup

from casepilot_api import collection_references as refs
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Conversation, WorkspaceTestBrief
from casepilot_api.planning_review import binding


@pytest.mark.asyncio
async def test_review_and_reference_update_have_no_opposing_lock_order(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, collection, ws = await setup(client)
        sid, did = source(account)
        response = await client.put(
            f"/api/v1/collections/{collection['id']}/references",
            json={"base_version": 0, "source_ids": [sid]},
        )
        assert response.status_code == 200
    plan = deepcopy(PLAN)
    for point in plan["feature_points"] + plan["test_points"]:
        point["source_refs"][0].update(source_id=sid, document_id=did)
    with get_session_factory()() as db:
        brief = WorkspaceTestBrief(
            conversation_id=UUID(ws["id"]),
            version=1,
            status="draft",
            content={"test_object": "Synthetic", "planning": plan},
        )
        db.add(brief)
        db.commit()
        bid = brief.id
    review_at_capture, writer_has_collection, review_attempts_collection = Event(), Event(), Event()
    original_capture, original_state = refs.capture_reference_binding, refs.collection_state

    def capture(*args, **kwargs):
        if current_thread().name.startswith("review"):
            review_at_capture.set()
            assert writer_has_collection.wait(10)
            review_attempts_collection.set()
        return original_capture(*args, **kwargs)

    def state(*args, **kwargs):
        result = original_state(*args, **kwargs)
        if current_thread().name.startswith("binding-writer") and kwargs.get("lock"):
            writer_has_collection.set()
            assert review_attempts_collection.wait(10)
        return result

    monkeypatch.setattr(refs, "capture_reference_binding", capture)
    monkeypatch.setattr(refs, "collection_state", state)

    def review():
        with get_session_factory()() as db:
            try:
                value = binding(
                    db, db.get(Conversation, UUID(ws["id"])), db.get(WorkspaceTestBrief, bid)
                )
                db.commit()
                return bool(value)
            except Exception as error:
                db.rollback()
                return getattr(getattr(error, "orig", None), "sqlstate", type(error).__name__)

    def writer():
        with get_session_factory()() as db:
            try:
                refs.update_references(
                    UUID(collection["id"]),
                    refs.ReferenceUpdate(base_version=1, source_ids=[UUID(sid)]),
                    db.get(Account, UUID(account["id"])),
                    db,
                )
                return True
            except Exception as error:
                db.rollback()
                return getattr(getattr(error, "orig", None), "sqlstate", type(error).__name__)

    with (
        ThreadPoolExecutor(1, thread_name_prefix="review") as reviews,
        ThreadPoolExecutor(1, thread_name_prefix="binding-writer") as writers,
    ):
        first = reviews.submit(review)
        assert review_at_capture.wait(10), first.result(timeout=1)
        second = writers.submit(writer)
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert results == [True, True], results
