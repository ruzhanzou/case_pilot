"""Real PostgreSQL outbox/claim/executor; only provider and broker transport mocked."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select, text
from test_workbench_bridge_integration import setup
from test_workbench_goal_completion import activate, send

from casepilot_api.database import get_engine, get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Base, CaseCollection, WorkbenchContinuation


@pytest.fixture
def isolated_outbox_db(monkeypatch):
    # The real dispatcher is intentionally global. Isolate its complete database
    # namespace so unrelated tests' outboxes are never claimed or modified.
    from casepilot_agent import tasks

    from casepilot_api.config import get_settings

    original = get_engine()
    schema = "qa_durable_" + uuid4().hex
    with original.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = original.url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine, checkfirst=False)
        monkeypatch.setattr(
            get_settings(), "database_url", url.render_as_string(hide_password=False)
        )
        monkeypatch.setattr(
            tasks.settings, "database_url", url.render_as_string(hide_password=False)
        )
        get_engine.cache_clear()
        get_session_factory.cache_clear()
        yield tasks
    finally:
        get_engine().dispose()
        get_engine.cache_clear()
        get_session_factory.cache_clear()
        engine.dispose()
        with original.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.asyncio
async def test_real_query_checkpoint_continues_to_exact_review_without_write(
    monkeypatch,
    isolated_outbox_db,
):
    from workbench_collection_continuation import BoundCollectionDispatch, await_collection_proposal

    from casepilot_api.workbench_run_executor import execute_workbench_continuation

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        case = (
            await client.post(
                f"/api/v1/collections/{collection['id']}/test-cases",
                json={
                    "title": "synthetic selected case",
                    "steps": [{"action": "run", "expected": "pass"}],
                },
            )
        ).json()
        selected = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
            },
        )
        assert selected.status_code == 200
        provider = activate(
            monkeypatch,
            [
                ("query_collections", {"search": ""}),
                (
                    "plan_work",
                    {
                        "steps": ["Inspect", "Prepare deletion"],
                        "plan_actions": ["COLLECTION_QUERY", "COLLECTION_DELETE"],
                    },
                ),
                "read",
                ("delete_collection", {"collection_id": collection["id"]}),
                "prepare",
            ],
        )
        turn = await send(client, cid)
        assert not turn["action"].get("proposal")
        binding = BoundCollectionDispatch(cid, turn)
        assert binding.pending_delivery()
        report = {}
        result = await await_collection_proposal(cid, turn, isolated_outbox_db, report)
        proposal = result["action"]["proposal"]
        assert proposal["status"] == "pending" and proposal["collection_id"] == collection["id"]
        assert report["continuation_tasks_executed"] == 1
        assert report["continuation_terminal"] == {
            "plan_present": True,
            "plan_cursor": 1,
            "plan_action": "COLLECTION_DELETE",
            "run_status": "waiting_approval",
        }
        repeated_report = {}
        same = await await_collection_proposal(cid, turn, isolated_outbox_db, repeated_report)
        assert same["action"]["proposal"] == proposal
        assert repeated_report["continuation_tasks_executed"] == 0
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None
            event = db.scalar(
                select(WorkbenchContinuation).where(WorkbenchContinuation.run_id == binding.run_id)
            )
            event_id = str(event.id)
        calls = len(provider.observations)
        assert execute_workbench_continuation(event_id)["status"] == "ignored"
        assert len(provider.observations) == calls
        assert not binding.pending_delivery()
        # Reject through the real API, then a fresh root must obtain its own
        # proposal. The old pending identity can never satisfy the new wait.
        rejected = await client.post(
            f"/api/v1/workspaces/{cid}/collection-proposals/{proposal['id']}/reject", json={}
        )
        assert rejected.status_code == 200
        provider = activate(
            monkeypatch,
            [
                ("query_collections", {"search": ""}),
                (
                    "plan_work",
                    {
                        "steps": ["Inspect", "Prepare deletion"],
                        "plan_actions": ["COLLECTION_QUERY", "COLLECTION_DELETE"],
                    },
                ),
                "read",
                ("delete_collection", {"collection_id": collection["id"]}),
                "prepare",
            ],
        )
        fresh = await send(client, cid)
        from workbench_agent_live_journey import JourneyFailure

        with pytest.raises(JourneyFailure, match="durable_binding_changed"):
            binding.proposal_turn()
        result = await await_collection_proposal(cid, fresh, isolated_outbox_db, {})
        assert result["action"]["proposal"]["id"] != proposal["id"]
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None
        from workbench_collection_continuation import finish_collection_approval

        current = result["action"]["proposal"]
        approved = await client.post(
            f"/api/v1/workspaces/{cid}/collection-proposals/{current['id']}/confirm",
            json={"name": collection["name"], "collection_id": collection["id"]},
        )
        assert approved.status_code == 200
        calls = len(provider.observations)
        finish_report = {}
        try:
            await finish_collection_approval(cid, fresh, current, isolated_outbox_db, finish_report)
        except JourneyFailure:
            import json

            pytest.fail(
                json.dumps(
                    {
                        "safe_approval_diagnostic": finish_report,
                        "additional_provider_calls": len(provider.observations) - calls,
                    }
                )
            )
        assert len(provider.observations) == calls
        assert finish_report["continuation_tasks_executed"] == 1
        assert finish_report["approval_continuation_terminal"]["run_status"] == "completed"
        assert finish_report["approval_continuation_remaining"] == 0
        assert finish_report["approval_outbox_remaining"] == 0
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is not None
            from casepilot_api.models import TestCase as CaseRecord

            stored = db.get(CaseRecord, UUID(case["id"]))
            assert (
                stored.deleted_at is None
                and str(stored.current_revision_id) == case["current_revision_id"]
            )


@pytest.mark.asyncio
async def test_true_awaiting_input_has_no_empty_wait(monkeypatch, isolated_outbox_db):
    from workbench_agent_live_journey import JourneyFailure
    from workbench_collection_continuation import await_collection_proposal

    from casepilot_api.workbench_agent import FinalAnswer

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        provider = activate(monkeypatch, [FinalAnswer(kind="clarify", message="请明确目标")])
        turn = await send(client, workspace["id"])
        with pytest.raises(JourneyFailure, match="durable_no_deliverable_continuation"):
            await await_collection_proposal(workspace["id"], turn, isolated_outbox_db, {})
        assert len(provider.observations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_outbox", "stale_epoch"])
async def test_missing_or_stale_delivery_never_fabricates_proposal(
    monkeypatch,
    isolated_outbox_db,
    fault,
):
    from workbench_agent_live_journey import JourneyFailure
    from workbench_collection_continuation import BoundCollectionDispatch, await_collection_proposal

    from casepilot_api.models import TaskOutbox

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        provider = activate(
            monkeypatch,
            [
                ("query_collections", {"search": ""}),
                (
                    "plan_work",
                    {
                        "steps": ["Inspect", "Prepare deletion"],
                        "plan_actions": ["COLLECTION_QUERY", "COLLECTION_DELETE"],
                    },
                ),
                "read",
            ],
        )
        turn = await send(client, cid)
        binding = BoundCollectionDispatch(cid, turn)
        with get_session_factory()() as db:
            event = db.scalar(
                select(WorkbenchContinuation).where(WorkbenchContinuation.run_id == binding.run_id)
            )
            if fault == "missing_outbox":
                outbox = db.scalar(select(TaskOutbox).where(TaskOutbox.task_id == str(event.id)))
                db.delete(outbox)  # Synthetic transport-loss fault, not an authority bypass.
            else:
                event.expected_epoch += 1  # Synthetic stale message; real claim must reject it.
            db.commit()
        calls = len(provider.observations)
        with pytest.raises(
            JourneyFailure, match="durable_(no_deliverable_continuation|proposal_not_ready)"
        ):
            await await_collection_proposal(cid, turn, isolated_outbox_db, {})
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            assert db.get(CaseCollection, UUID(collection["id"])).deleted_at is None
