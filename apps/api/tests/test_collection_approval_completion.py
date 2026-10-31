"""Committed human effects may complete; they grant no new operation authority."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import setup
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401
from test_workbench_goal_completion import activate, send

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import (
    Account,
    AuditEvent,
    CollectionCaseMembership,
    Conversation,
    ConversationMessage,
    WorkbenchContinuation,
    WorkbenchRun,
)
from casepilot_api.workbench_run_executor import execute_workbench_continuation

pytestmark = pytest.mark.usefixtures("isolated_outbox_db")


async def approved_delete(client, monkeypatch, *, shared=False, followup=False):
    account, collection, workspace = await setup(client)
    cid = workspace["id"]
    case = (
        await client.post(
            f"/api/v1/collections/{collection['id']}/test-cases",
            json={
                "title": "Synthetic selected case",
                "steps": [{"action": "run", "expected": "pass"}],
            },
        )
    ).json()
    if shared:
        other = (
            await client.post(
                f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
                json={"name": "Retained"},
            )
        ).json()
        with get_session_factory()() as db:
            db.add(
                CollectionCaseMembership(
                    collection_id=UUID(other["id"]), test_case_id=UUID(case["id"]), position=0
                )
            )
            db.commit()
    assert (
        await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 0,
                "sources": [{"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}],
            },
        )
    ).status_code == 200
    actions = ["COLLECTION_DELETE"] + (["CASE_MODIFY"] if followup else [])
    provider = activate(
        monkeypatch,
        [
            (
                "plan_work",
                {
                    "steps": ["Delete collection"] + (["Modify old targets"] if followup else []),
                    "plan_actions": actions,
                },
            ),
            ("delete_collection", {"collection_id": collection["id"]}),
            "prepare",
        ],
    )
    turn = await send(client, cid)
    proposal = turn["action"]["proposal"]
    confirmed = await client.post(
        f"/api/v1/workspaces/{cid}/collection-proposals/{proposal['id']}/confirm",
        json={"name": collection["name"], "collection_id": collection["id"]},
    )
    assert confirmed.status_code == 200
    run_id = UUID(turn["assistant_message"]["metadata"]["workbench_agent"]["durable_run"]["id"])
    with get_session_factory()() as db:
        event = db.scalar(
            select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == run_id,
                WorkbenchContinuation.event_kind == "approval_completed",
            )
        )
        return run_id, str(event.id), provider, collection, cid


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_final_applied_delete_completes_without_model_and_duplicate_is_ignored(
    monkeypatch,
    shared,
):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_id, event_id, provider, collection, _ = await approved_delete(
            client, monkeypatch, shared=shared
        )
        calls = len(provider.observations)
        assert execute_workbench_continuation(event_id)["status"] == "completed"
        assert execute_workbench_continuation(event_id)["status"] == "ignored"
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            assert run.cursor == 1 and run.plan["steps"][0]["status"] == "completed"
            assert bool(run.binding["sources"]) is shared
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.resource_id == UUID(collection["id"]),
                        AuditEvent.action == "collection.deleted",
                    )
                )
                == 1
            )


@pytest.mark.asyncio
async def test_followup_mutation_cannot_resurrect_removed_scope(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_id, event_id, provider, _, _ = await approved_delete(client, monkeypatch, followup=True)
        calls = len(provider.observations)
        assert execute_workbench_continuation(event_id)["status"] == "active"
        with get_session_factory()() as db:
            event = db.scalar(
                select(WorkbenchContinuation).where(
                    WorkbenchContinuation.run_id == run_id,
                    WorkbenchContinuation.event_kind == "next_step",
                )
            )
            next_id = str(event.id)
        assert execute_workbench_continuation(next_id)["status"] == "ignored"
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, run_id)
            assert run.status == "invalidated" and run.cursor == 1
            assert run.plan["steps"][0]["status"] == "completed"
            assert run.plan["steps"][1]["status"] != "completed"
            assert not run.binding["sources"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "action",
        "epoch",
        "cursor",
        "foreign_run",
        "proposal",
        "version",
        "missing_proof",
        "unapplied",
        "wrong_result",
        "payload_binding",
    ],
)
async def test_forged_stale_or_unapplied_approval_never_advances(
    monkeypatch,
    fault,
):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_id, event_id, provider, _, cid = await approved_delete(client, monkeypatch, shared=True)
        calls = len(provider.observations)
        with get_session_factory()() as db:
            event = db.get(WorkbenchContinuation, UUID(event_id))
            run = db.get(WorkbenchRun, run_id)
            if fault == "action":
                plan = deepcopy(run.plan)
                plan["steps"][0]["action"] = "CASE_MODIFY"
                run.plan = plan
            elif fault == "epoch":
                event.expected_epoch += 1
            elif fault == "cursor":
                event.cursor += 1
            elif fault == "proposal":
                event.source_id = str(uuid4())
            elif fault == "version":
                event.source_version = str(uuid4())
            elif fault == "missing_proof":
                run.checkpoint = {
                    k: v for k, v in run.checkpoint.items() if k != "applied_collection_delete"
                }
            elif fault == "payload_binding":
                event.payload = {**event.payload, "binding": {}}
            elif fault == "foreign_run":
                from casepilot_api.workbench_continuation import create_run

                conversation = db.get(Conversation, UUID(cid))
                root = ConversationMessage(
                    conversation_id=conversation.id, role="user", content="Synthetic unrelated root"
                )
                db.add(root)
                db.flush()
                other = create_run(
                    db,
                    db.get(Account, run.account_id),
                    conversation,
                    root.id,
                    uuid4(),
                    plan=deepcopy(run.plan),
                )
                event.run_id = other.id
            else:
                conversation = db.get(Conversation, UUID(cid))
                context = deepcopy(conversation.context)
                proposal = context["workbench_collection_proposal"]
                if fault == "unapplied":
                    proposal["status"] = "pending"
                else:
                    proposal["result"]["deleted"] = False
                conversation.context = context
            db.commit()
        assert execute_workbench_continuation(event_id)["status"] == "ignored"
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            assert db.get(WorkbenchRun, run_id).cursor == 0
            invalid = db.get(WorkbenchContinuation, UUID(event_id))
            assert invalid.status == "invalidated"
            if fault not in {"epoch", "cursor"}:
                assert invalid.receipt["error_code"] == "workbench_approval_completion_invalid"
