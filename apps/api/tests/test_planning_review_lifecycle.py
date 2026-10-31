"""Real HTTP/PG lifecycle; deterministic providers only, never implicit approval."""

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest
from casepilot_agent.contracts import UsageMetadata
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import AuditEvent, GenerationJob, PlanningReview, WorkspaceTestBrief
from casepilot_api.planning_review import execute

SOURCE = {
    "source_id": None,
    "document_id": None,
    "chunk_id": None,
    "label": "Original",
    "locator": "user_input",
    "excerpt": "A accepts x. B rejects y.",
}
PLAN = {
    "feature_points": [
        dict(id=f, name=f, module=f, description=f, requirement_refs=[f], source_refs=[SOURCE])
        for f in ("A", "B")
    ],
    "test_points": [
        dict(
            id=p,
            title=p,
            scenario="original " + p,
            objective="outcome " + p,
            category="normal",
            priority="P1",
            priority_reason="test",
            executable=True,
            executable_analysis="",
            feature_point_ids=[f],
            primary_feature_id=f,
            source_refs=[SOURCE],
        )
        for p, f in [("p1", "A"), ("p2", "B")]
    ],
    "coverage_review": {
        "status": "pending_independent_review",
        "source": "model_proposed",
        "warnings": ["coverage_unverified"],
        "batches": [
            {
                "batch_index": 1,
                "obligations": [
                    {
                        "id": "o1",
                        "feature_point_ids": ["A"],
                        "dimension": "normal",
                        "basis": "A accepts x.",
                        "point_ids": ["p1"],
                        "clarification": "",
                    }
                ],
                "uncovered_ids": [],
                "clarifications": [],
                "duplicate_suggestions": [],
                "warnings": ["coverage_unverified"],
                "completion_attempted": False,
            }
        ],
    },
}


class Provider:
    def __init__(self, callback=None, bad=False):
        self.callback, self.bad, self.calls = callback, bad, 0

    def complete(self, *, result_type, stage, payload, **kwargs):
        self.request_guard()
        self.calls += 1
        assert len(payload["snapshot"]["planning"]["feature_points"]) == 2
        if self.callback:
            self.callback()
        if self.bad:
            raise ValueError("synthetic parse failure")
        if stage.endswith("audit"):
            value = {
                "findings": [
                    {
                        "id": "issue-1",
                        "kind": "contradiction",
                        "point_ids": ["p1"],
                        "obligation_keys": [],
                        "explanation": "Review p1 with full sources",
                        "citations": [{"span_id": payload["citation_catalog"][0]["span_id"]}],
                    }
                ],
                "unresolved": ["Needs human review"],
            }
        else:
            value = {
                "points": [
                    {
                        "point_id": "p1",
                        "action": "upsert",
                        "title": "revised p1",
                        "scenario": "reviewed scenario",
                        "objective": "reviewed outcome",
                        "feature_ids": ["A"],
                        "primary_feature_id": "A",
                        "sources": [0],
                        "issue_ids": ["issue-1"],
                    }
                ],
                "obligations": [],
                "unresolved": ["Still independent review pending"],
            }
        return result_type.model_validate(value), UsageMetadata(model="deterministic")


async def start(client):
    account, _, workspace = await setup(client)
    with get_session_factory()() as db:
        db.add(
            WorkspaceTestBrief(
                conversation_id=UUID(workspace["id"]),
                version=1,
                status="draft",
                created_by=UUID(account["id"]),
                content={"test_object": "Synthetic", "planning": deepcopy(PLAN)},
            )
        )
        db.commit()
    url = f"/api/v1/workspaces/{workspace['id']}/planning-reviews"
    response = await client.post(url, json={"base_version": 1})
    assert response.status_code == 202, response.text
    return url, response.json(), workspace


@pytest.mark.asyncio
async def test_review_revision_apply_and_replay_no_generation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, ws = await start(client)
        assert (await client.post(url, json={"base_version": 1})).json()["id"] == row["id"]
        provider = Provider()
        assert await asyncio.to_thread(execute, row["id"], "audit", provider) == "reviewed"
        assert await asyncio.to_thread(execute, row["id"], "audit", provider) == "ignored"
        result = await client.post(
            f"{url}/{row['id']}/revise", json={"base_version": 1, "issue_ids": ["issue-1"]}
        )
        assert result.status_code == 200, result.text
        assert await asyncio.to_thread(execute, row["id"], "revision", provider) == "proposed"
        row = (await client.get(url)).json()[0]
        assert row["requests_used"] == 2 and provider.calls == 2
        body = {"base_version": 1, "confirm": True, "proposal_hash": row["proposal_hash"]}
        denied = await client.post(f"{url}/{row['id']}/apply", json={**body, "confirm": False})
        assert denied.status_code == 409
        applied = await client.post(f"{url}/{row['id']}/apply", json=body)
        assert applied.status_code == 200, applied.text
        replay = await client.post(f"{url}/{row['id']}/apply", json=body)
        assert replay.json()["applied_brief_id"] == applied.json()["applied_brief_id"]
        with get_session_factory()() as db:
            brief = db.get(WorkspaceTestBrief, UUID(applied.json()["applied_brief_id"]))
            assert brief.status == "draft" and brief.confirmed_by is None
            assert brief.content["planning"]["test_points"][1] == PLAN["test_points"][1]
            assert (
                brief.content["planning"]["coverage_review"]["status"]
                == "pending_independent_review"
            )
            assert "coverage_unverified" in brief.content["planning"]["coverage_review"]["warnings"]
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(GenerationJob)
                    .where(GenerationJob.collection_id == UUID(ws["collection_id"]))
                )
                == 0
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.resource_id == UUID(row["id"]))
                )
                == 1
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "new_version", "parse", "budget"])
async def test_late_result_and_failure_never_apply(mode):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, ws = await start(client)

        def callback():
            with get_session_factory()() as db:
                r = db.get(PlanningReview, UUID(row["id"]))
                if mode == "cancel":
                    r.status = "cancelled"
                if mode == "new_version":
                    db.add(
                        WorkspaceTestBrief(
                            conversation_id=UUID(ws["id"]),
                            version=2,
                            status="draft",
                            content={"test_object": "Synthetic", "planning": deepcopy(PLAN)},
                        )
                    )
                db.commit()

        if mode == "budget":
            with get_session_factory()() as db:
                db.get(PlanningReview, UUID(row["id"])).requests_used = 2
                db.commit()
        provider = Provider(
            callback if mode in {"cancel", "new_version"} else None, bad=mode == "parse"
        )
        assert await asyncio.to_thread(execute, row["id"], "audit", provider) in {
            "ignored",
            "failed",
        }
        assert await asyncio.to_thread(execute, row["id"], "audit", provider) == "ignored"
        state = (await client.get(url)).json()[0]
        assert (
            state["status"] in {"failed", "cancelled", "invalidated"} and state["proposal"] is None
        )
        assert provider.calls <= 1


@pytest.mark.asyncio
async def test_apply_stale_version_foreign_account_and_double_reservation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, ws = await start(client)

        class Double(Provider):
            def complete(self, **kwargs):
                self.request_guard()
                return super().complete(**kwargs)

        provider = Double()
        assert await asyncio.to_thread(execute, row["id"], "audit", provider) == "failed"
        assert provider.calls == 0
        assert (await client.get(url)).json()[0]["requests_used"] == 1
        # Foreign logged-in account must not observe or cancel another workspace's review.
        await setup(client)
        assert (await client.get(url)).status_code == 404
        assert (
            await client.post(f"{url}/{row['id']}/cancel", json={"base_version": 1})
        ).status_code == 404


@pytest.mark.asyncio
async def test_new_version_after_proposal_invalidates_exact_confirmation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, ws = await start(client)
        provider = Provider()
        await asyncio.to_thread(execute, row["id"], "audit", provider)
        await client.post(
            f"{url}/{row['id']}/revise", json={"base_version": 1, "issue_ids": ["issue-1"]}
        )
        await asyncio.to_thread(execute, row["id"], "revision", provider)
        proposed = (await client.get(url)).json()[0]
        with get_session_factory()() as db:
            db.add(
                WorkspaceTestBrief(
                    conversation_id=UUID(ws["id"]),
                    version=2,
                    status="draft",
                    content={"test_object": "Synthetic", "planning": deepcopy(PLAN)},
                )
            )
            db.commit()
        result = await client.post(
            f"{url}/{row['id']}/apply",
            json={"base_version": 1, "confirm": True, "proposal_hash": proposed["proposal_hash"]},
        )
        assert result.status_code == 409
        assert (await client.get(url)).json()[0]["status"] == "invalidated"


@pytest.mark.asyncio
async def test_source_snapshot_change_rejects_proposal_apply():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, ws = await start(client)
        provider = Provider()
        await asyncio.to_thread(execute, row["id"], "audit", provider)
        await client.post(
            f"{url}/{row['id']}/revise", json={"base_version": 1, "issue_ids": ["issue-1"]}
        )
        await asyncio.to_thread(execute, row["id"], "revision", provider)
        proposed = (await client.get(url)).json()[0]
        with get_session_factory()() as db:
            brief = db.get(WorkspaceTestBrief, db.get(PlanningReview, UUID(row["id"])).brief_id)
            changed = deepcopy(brief.content)
            changed["planning"]["feature_points"][0]["source_refs"][0]["excerpt"] = "Changed source"
            brief.content = changed
            db.commit()
        response = await client.post(
            f"{url}/{row['id']}/apply",
            json={"base_version": 1, "confirm": True, "proposal_hash": proposed["proposal_hash"]},
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_real_outbox_routes_and_recovers_only_unclaimed_matching_phase(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from casepilot_agent import tasks

    from casepilot_api.models import TaskOutbox

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, ws = await start(client)
        delivered = []
        monkeypatch.setattr(
            tasks.celery_app, "send_task", lambda name, **kwargs: delivered.append((name, kwargs))
        )
        await asyncio.to_thread(tasks.dispatch_task_outbox.run)
        matching = [entry for entry in delivered if entry[1]["args"] == [row["id"], "audit"]]
        assert len(matching) == 1 and matching[0][1]["queue"] == "workbench"
        with get_session_factory()() as db:
            out = db.scalar(select(TaskOutbox).where(TaskOutbox.task_args == [row["id"], "audit"]))
            out.dispatched_at = datetime.now(UTC) - timedelta(seconds=90)
            db.commit()
        await asyncio.to_thread(tasks.recover_unclaimed_deliveries.run)
        with get_session_factory()() as db:
            out = db.scalar(select(TaskOutbox).where(TaskOutbox.task_args == [row["id"], "audit"]))
            assert out.status == "pending"
            out.status = "dispatched"
            out.dispatched_at = datetime.now(UTC) - timedelta(seconds=90)
            db.get(PlanningReview, UUID(row["id"])).status = "cancelled"
            db.commit()
        await asyncio.to_thread(tasks.recover_unclaimed_deliveries.run)
        assert await asyncio.to_thread(execute, row["id"], "audit", Provider()) == "ignored"
        with get_session_factory()() as db:
            out = db.scalar(select(TaskOutbox).where(TaskOutbox.task_args == [row["id"], "audit"]))
            assert out.status == "dispatched"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,phase,code",
    [
        ("reference", "reference_validation", "planning_review_span_invalid"),
        ("schema", "schema_validation", "planning_review_schema_invalid"),
        ("implementation", "result_serialization", "planning_review_serialization_failed"),
        ("storage", "result_persistence", "planning_review_persistence_failed"),
    ],
)
async def test_failures_have_exact_safe_stage_and_never_succeed(monkeypatch, mode, phase, code):
    from casepilot_agent.planning_review_diagnostics import observe_failures
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    class Fault(Provider):
        def complete(self, **kwargs):
            result, usage = super().complete(**kwargs)
            if mode == "reference":
                result.findings[0].citations[0].span_id = "span-0000000000000000"
            elif mode == "schema":
                result = {"findings": [{"citations": [{"source": "PRIVATE_INPUT"}]}]}
            elif mode == "implementation":
                usage = object()
            return result, usage

    original_commit = Session.commit
    failures = []

    def commit(db):
        if mode == "storage" and any(
            isinstance(r, PlanningReview) and r.status == "reviewed" for r in db.dirty
        ):
            raise OperationalError(
                "PRIVATE_SQL", {"password": "PRIVATE_VALUE"}, Exception("PRIVATE_DETAIL")
            )
        return original_commit(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url, row, _ = await start(client)
        monkeypatch.setattr(Session, "commit", commit)
        provider = Fault()
        with observe_failures(failures.append):
            assert await asyncio.to_thread(execute, row["id"], "audit", provider) == "failed"
        state = (await client.get(url)).json()[0]
        assert state["status"] == "failed" and state["review"] is None
        assert state["requests_used"] == 1 and provider.calls == 1
        assert state["diagnostic"] == failures[0]
        assert failures[0]["phase"] == phase and failures[0]["code"] == code
        assert "PRIVATE" not in str(failures)
        if mode == "reference":
            assert failures[0]["errors"][0]["path"] == ["findings", 0, "citations", 0, "span_id"]
        assert await asyncio.to_thread(execute, row["id"], "audit", provider) == "ignored"


@pytest.mark.asyncio
async def test_failure_record_database_error_still_reports_original_safe_diagnostic(monkeypatch):
    from casepilot_agent.planning_review_diagnostics import observe_failures
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, row, _ = await start(client)
        original_commit = Session.commit

        def commit(db):
            if any(isinstance(r, PlanningReview) and r.status == "failed" for r in db.dirty):
                raise OperationalError("PRIVATE_SQL", {}, Exception("PRIVATE_DETAIL"))
            return original_commit(db)

        monkeypatch.setattr(Session, "commit", commit)
        evidence = []
        with (
            observe_failures(evidence.append),
            pytest.raises(RuntimeError, match="^planning_review_failure_record_unavailable$"),
        ):
            await asyncio.to_thread(execute, row["id"], "audit", Provider(bad=True))
        assert [d["phase"] for d in evidence] == ["provider_call", "failure_persistence"]
        assert "PRIVATE" not in str(evidence)
        assert evidence[1]["code"] == "planning_review_failure_record_unavailable"
