"""Exact applied CASE_DELETE proof; real PG/API/claim, scripted model boundaries only."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import activate
from test_workbench_collection_durable_harness import isolated_outbox_db  # noqa: F401
from test_workbench_continuation_scope import selected_pair
from test_workbench_goal_completion import send

from casepilot_api import conversations
from casepilot_api.config import get_settings
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import AuditEvent, CaseChangeSet, WorkbenchContinuation, WorkbenchRun
from casepilot_api.workbench_run_executor import execute_workbench_continuation

pytestmark = pytest.mark.usefixtures("isolated_outbox_db")


async def approved(client, monkeypatch, *, keep=False, followup=False):
    cid, cases = await selected_pair(client)
    version = 1
    if not keep:
        result = await client.patch(
            f"/api/v1/workspaces/{cid}/selection",
            json={
                "base_version": 1,
                "sources": [
                    {"ref": f"asset:{cases[0]['id']}", "version": cases[0]["current_revision_id"]}
                ],
            },
        )
        assert result.status_code == 200
        version = 2
    actions = ["CASE_DELETE"] + (["CASE_MODIFY"] if followup else [])
    provider = activate(
        monkeypatch,
        [("prepare_delete", {})],
        fixture_plan={
            "steps": ["Delete selected"] + (["Modify remaining"] if followup else []),
            "plan_actions": actions,
        },
    )
    monkeypatch.setattr(get_settings(), "agent_provider", "openai_compatible")
    monkeypatch.setattr(get_settings(), "agent_api_key", "")

    def scope(content, catalog, context, **kwargs):
        return SimpleNamespace(
            ids=[cases[0]["id"]],
            reference="selection",
            requested_count=1,
            referenced_case_keys=[],
            ambiguous=False,
            clarification=None,
        )

    monkeypatch.setattr(conversations, "select_case_scope", scope)
    turn = await send(
        client,
        cid,
        "请软删除刚才选中的这一条用例，保留其余用例不变。先给我精确删除清单，未经确认不要删除。",
    )
    change = turn["action"]["change_set_id"]
    assert (await client.get(f"/api/v1/test-cases/{cases[0]['id']}")).status_code == 200
    result = await client.post(
        f"/api/v1/case-change-sets/{change}/apply",
        json={
            "selection_version": version,
            "review_refs": [cases[0]["id"]],
            "accepted_fields": {cases[0]["id"]: ["delete"]},
        },
    )
    assert result.status_code == 200
    assert (await client.get(f"/api/v1/test-cases/{cases[0]['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/test-cases/{cases[1]['id']}")).json()[
        "current_revision_id"
    ] == cases[1]["current_revision_id"]
    rid = UUID(turn["assistant_message"]["metadata"]["workbench_agent"]["durable_run"]["id"])
    with get_session_factory()() as db:
        event = db.scalar(
            select(WorkbenchContinuation).where(
                WorkbenchContinuation.run_id == rid,
                WorkbenchContinuation.event_kind == "approval_completed",
            )
        )
        return rid, str(event.id), provider, cases, change


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [False, True])
async def test_exact_delete_terminal_without_model_and_duplicate(monkeypatch, keep):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rid, eid, provider, cases, _ = await approved(client, monkeypatch, keep=keep)
        calls = len(provider.observations)
        assert execute_workbench_continuation(eid)["status"] == "completed"
        assert execute_workbench_continuation(eid)["status"] == "ignored"
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, rid)
            assert run.cursor == 1 and bool(run.binding["sources"]) is keep
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.resource_id == UUID(cases[0]["id"]),
                        AuditEvent.action == "test_case.deleted",
                    )
                )
                == 1
            )


@pytest.mark.asyncio
async def test_followup_missing_scope_still_rejected(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rid, eid, provider, _, _ = await approved(client, monkeypatch, followup=True)
        calls = len(provider.observations)
        assert execute_workbench_continuation(eid)["status"] == "active"
        with get_session_factory()() as db:
            event = db.scalar(
                select(WorkbenchContinuation).where(
                    WorkbenchContinuation.run_id == rid,
                    WorkbenchContinuation.event_kind == "next_step",
                )
            )
            next_id = str(event.id)
        assert execute_workbench_continuation(next_id)["status"] == "ignored"
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, rid)
            assert run.cursor == 1 and run.status == "invalidated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper",
    [
        "missing",
        "epoch",
        "run",
        "action",
        "operation",
        "version",
        "kind",
        "partial",
        "effect",
        "event",
    ],
)
async def test_wrong_completion_proof_never_advances(monkeypatch, tamper):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rid, eid, provider, _, change_id = await approved(client, monkeypatch)
        calls = len(provider.observations)
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, rid)
            event = db.get(WorkbenchContinuation, UUID(eid))
            proof = deepcopy(run.checkpoint["applied_case_delete"])
            if tamper == "missing":
                run.checkpoint = {
                    k: v for k, v in run.checkpoint.items() if k != "applied_case_delete"
                }
            elif tamper in {"epoch", "run", "operation", "event"}:
                key = {
                    "epoch": "epoch",
                    "run": "run_id",
                    "operation": "operation_id",
                    "event": "event_id",
                }[tamper]
                proof[key] = 999 if tamper == "epoch" else str(uuid4())
                run.checkpoint = {**run.checkpoint, "applied_case_delete": proof}
            elif tamper == "action":
                plan = deepcopy(run.plan)
                plan["steps"][0]["action"] = "CASE_MODIFY"
                run.plan = plan
            elif tamper == "version":
                event.source_version = "wrong"
            elif tamper == "kind":
                event.payload = {**event.payload, "source_kind": "collection_proposal"}
            elif tamper == "partial":
                event.payload = {**event.payload, "outcome": "partial"}
            else:
                change = db.get(CaseChangeSet, UUID(change_id))
                items = deepcopy(change.items)
                items[0]["status"] = "pending"
                change.items = items
            db.commit()
        assert execute_workbench_continuation(eid)["status"] == "ignored"
        assert len(provider.observations) == calls
        with get_session_factory()() as db:
            run = db.get(WorkbenchRun, rid)
            assert run.cursor == 0 and run.status == "invalidated"
