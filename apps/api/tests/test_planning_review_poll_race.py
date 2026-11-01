"""Two real PG sessions race poll timeout against the worker's locked terminal CAS."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, current_thread
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from test_planning_review_lifecycle import start

from casepilot_api import planning_review as service
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, PlanningReview


@pytest.mark.asyncio
async def test_timeout_poll_cannot_overwrite_concurrent_worker_terminal(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, row, _ = await start(client)
    rid = UUID(row["id"])
    with get_session_factory()() as db:
        item = db.get(PlanningReview, rid)
        item.status = "auditing"
        item.updated_at = datetime.now(UTC) - timedelta(minutes=11)
        aid, cid = item.account_id, item.conversation_id
        db.commit()
    poll_read, release_poll, writer_started = Event(), Event(), Event()
    original_fresh = service.fresh
    pid = []

    def pause_poll(db, conversation, item):
        if current_thread().name.startswith("poll"):
            poll_read.set()
            assert release_poll.wait(10)
        return original_fresh(db, conversation, item)

    monkeypatch.setattr(service, "fresh", pause_poll)

    def poll():
        with get_session_factory()() as db:
            return service.list_reviews(cid, db.get(Account, aid), db)

    def completion():
        with get_session_factory()() as db:
            pid.append(db.scalar(text("select pg_backend_pid()")))
            writer_started.set()
            item = db.scalar(
                select(PlanningReview).where(PlanningReview.id == rid).with_for_update()
            )
            if item.status != "auditing":
                return "ignored"
            service.fresh(db, db.get(service.Conversation, cid), item)
            item.status = "reviewed"
            item.data = {**item.data, "review": {"findings": [], "unresolved": ["independent"]}}
            db.commit()
            return "reviewed"

    with (
        ThreadPoolExecutor(1, thread_name_prefix="poll") as polls,
        ThreadPoolExecutor(1) as workers,
    ):
        first = polls.submit(poll)
        assert poll_read.wait(10)
        second = workers.submit(completion)
        assert writer_started.wait(10)
        # Observe the actual server lock, not a timing-only guess about concurrent execution.
        blocked = False
        import time

        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not second.done():
                with get_session_factory()() as db:
                    blocked = bool(
                        db.scalar(
                            text("select cardinality(pg_blocking_pids(:pid))"), {"pid": pid[0]}
                        )
                    )
                if blocked:
                    break
                time.sleep(0.01)
        finally:
            release_poll.set()
        first.result(timeout=10)
        winner = second.result(timeout=10)
    with get_session_factory()() as db:
        item = db.get(PlanningReview, rid)
        if winner == "reviewed":
            assert item.status == "reviewed" and item.data["review"]["unresolved"] == [
                "independent"
            ]
        else:
            assert (
                blocked
                and item.status == "failed"
                and item.error_code == "planning_review_interrupted"
            )


@pytest.mark.asyncio
async def test_poll_refreshes_preloaded_stale_orm_after_terminal_commit():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, row, _ = await start(client)
    rid = UUID(row["id"])
    with get_session_factory()() as db:
        item = db.get(PlanningReview, rid)
        item.status = "auditing"
        item.updated_at = datetime.now(UTC) - timedelta(minutes=11)
        db.commit()
    with get_session_factory()() as reader:
        stale = reader.get(PlanningReview, rid)
        with get_session_factory()() as writer:
            item = writer.get(PlanningReview, rid)
            item.status = "reviewed"
            writer.commit()
        result = service.list_reviews(
            stale.conversation_id, reader.get(Account, stale.account_id), reader
        )
        assert next(r for r in result if r["id"] == str(rid))["status"] == "reviewed"
