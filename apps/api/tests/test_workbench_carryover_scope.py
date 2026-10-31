"""Canonical selection changes cannot resurrect old sibling proposal writes."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_workbench_bridge_integration import activate, setup
from test_workbench_collection_selection import post, seed

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import AuditEvent, GenerationJob


def audit_count(case_id):
    with get_session_factory()() as db:
        return db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.resource_type == "test_case", AuditEvent.resource_id == UUID(case_id))
        )


async def select_cases(client, cid, version, cases):
    response = await client.patch(
        f"/api/v1/workspaces/{cid}/selection",
        json={
            "base_version": version,
            "action": "replace",
            "sources": [
                {"ref": f"asset:{case['id']}", "version": case["current_revision_id"]}
                for case in cases
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def prepare_draft(
    client, monkeypatch, cid, version, priority, *, instruction=None, source_operation_id=None
):
    activate(monkeypatch, [("prepare_rewrite", {})])
    turn = await post(
        client,
        f"/conversations/{cid}/messages",
        {
            "content": instruction or f"把选中用例优先级改为{priority}",
            **({"source_operation_id": source_operation_id} if source_operation_id else {}),
            "selection_version": version,
            "client_request_id": str(uuid4()),
        },
    )
    operation = turn["operation_plan"]["operations"][0]
    assert "job_id" in turn["action"], turn
    assert operation["payload"]["preparation_mode"] == "canonical_draft_compute"
    assert not operation["payload"].get("last_confirmed_modification")
    return operation, turn["action"]["job_id"]


async def finish_worker(client, cid, operation, job_id):
    from casepilot_agent import tasks

    await asyncio.to_thread(tasks.rewrite_test_cases_batch.run, job_id)
    workspace = (await client.get(f"/api/v1/conversations/{cid}")).json()
    saved = next(row for row in workspace["operation_history"] if row["id"] == operation["id"])
    change_id = saved["related_change_set_id"]
    response = await client.get(f"/api/v1/case-change-sets/{change_id}")
    assert response.status_code == 200, response.text
    change = response.json()
    assert change["status"] == "ready", change
    return change


@pytest.mark.asyncio
@pytest.mark.parametrize("simulate_inflight_old_worker", [False, True])
async def test_narrowed_selection_worker_carryover_and_partial_apply(
    monkeypatch, simulate_inflight_old_worker
):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        first, excluded, untouched = [
            await seed(client, collection["id"], title) for title in ["A", "B", "Outside"]
        ]
        before_audits = {
            case["id"]: audit_count(case["id"]) for case in [first, excluded, untouched]
        }
        await select_cases(client, cid, 0, [first, excluded])
        original_op, job = await prepare_draft(client, monkeypatch, cid, 1, "P2")
        original = await finish_worker(client, cid, original_op, job)
        assert {item["ref"] for item in original["items"]} == {first["id"], excluded["id"]}
        await select_cases(client, cid, 1, [first])
        current_op, job = await prepare_draft(
            client, monkeypatch, cid, 2, "P0", source_operation_id=original_op["id"]
        )
        assert current_op["target"]["case_ids"] == [first["id"]]
        assert current_op["payload"]["task_id"] != original_op["payload"]["task_id"]
        with get_session_factory()() as db:
            record = db.get(GenerationJob, UUID(job))
            assert not record.input_payload.get("previous_proposals")
            if simulate_inflight_old_worker:
                # Reproduce a job queued by the old implementation: exercise the
                # real worker merge, not a fabricated API-only changeset.
                record.input_payload = {
                    **record.input_payload,
                    "previous_proposals": {
                        item["ref"]: deepcopy(item) for item in original["items"]
                    },
                    "previous_change_set_id": original["id"],
                }
                db.commit()
        current = await finish_worker(client, cid, current_op, job)
        refs = {item["ref"] for item in current["items"]}
        assert refs == (
            {first["id"], excluded["id"]} if simulate_inflight_old_worker else {first["id"]}
        )
        url = f"/api/v1/case-change-sets/{current['id']}/apply"
        if simulate_inflight_old_worker:
            rejected = await client.post(url, json={})
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"] == "workbench_selection_target_conflict"
            for case in [first, excluded, untouched]:
                now = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
                assert now["current_revision_id"] == case["current_revision_id"]
                assert audit_count(case["id"]) == before_audits[case["id"]]
        approved = await client.post(url, json={"review_refs": [first["id"]]})
        assert approved.status_code == 200, approved.text
        now = (await client.get(f"/api/v1/test-cases/{first['id']}")).json()
        assert now["current_revision_id"] != first["current_revision_id"]
        assert now["priority"] == "P0"
        assert audit_count(first["id"]) == before_audits[first["id"]] + 1
        if simulate_inflight_old_worker:
            rejected = await client.post(url, json={"review_refs": [excluded["id"]]})
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"] == "workbench_selection_target_conflict"
        for case in [excluded, untouched]:
            now = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert now["current_revision_id"] == case["current_revision_id"]
            assert now["priority"] == case["priority"]
            assert now["title"] == case["title"]
            assert audit_count(case["id"]) == before_audits[case["id"]]


@pytest.mark.parametrize("candidate", [False, True])
def test_canonical_write_guard_is_typed_and_versioned(candidate):
    ref, other, version = str(uuid4()), str(uuid4()), str(uuid4())
    kind = "candidate" if candidate else "asset"
    version = "3" if candidate else version
    conversation = SimpleNamespace(
        context={
            "workbench_selection": {
                "items": [{"ref": f"{kind}:{ref}", "kind": kind, "version": version}],
            }
        }
    )
    item = (
        {"target_type": "candidate", "ref": ref, "base_version": 3}
        if candidate
        else {"target_type": "formal", "ref": ref, "test_case_id": ref, "base_revision_id": version}
    )
    conversations._assert_canonical_write_items(conversation, [item])
    invalid = [
        {**item, "ref": other},
        {**item, "base_version" if candidate else "base_revision_id": "stale"},
        {**item, "target_type": "formal" if candidate else "candidate"},
    ]
    if not candidate:
        invalid.append({**item, "test_case_id": other})
    for bad in invalid:
        with pytest.raises(HTTPException) as error:
            conversations._assert_canonical_write_items(conversation, [bad])
        assert error.value.status_code == 409
    # Noncanonical legacy flows keep their existing domain review validation.
    conversations._assert_canonical_write_items(SimpleNamespace(context={}), invalid)


@pytest.mark.asyncio
async def test_same_canonical_scope_keeps_legitimate_multiround_task(monkeypatch):
    from casepilot_agent import tasks

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        cases = [await seed(client, collection["id"], title) for title in ["A", "B"]]
        await select_cases(client, cid, 0, cases)
        first_op, job = await prepare_draft(client, monkeypatch, cid, 1, "P2")
        first = await finish_worker(client, cid, first_op, job)
        second_op, job = await prepare_draft(client, monkeypatch, cid, 1, "P0")
        assert second_op["payload"]["task_id"] == first_op["payload"]["task_id"]
        with get_session_factory()() as db:
            record = db.get(GenerationJob, UUID(job))
            assert record.input_payload["previous_change_set_id"] == first["id"]
            assert set(record.input_payload["previous_proposals"]) == {case["id"] for case in cases}
        second = await finish_worker(client, cid, second_op, job)
        assert {item["ref"] for item in second["items"]} == {case["id"] for case in cases}
        approved = await client.post(f"/api/v1/case-change-sets/{second['id']}/apply", json={})
        assert approved.status_code == 200, approved.text
        for case in cases:
            current = (await client.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert current["priority"] == "P0"
            assert current["current_revision_id"] != case["current_revision_id"]


@pytest.mark.asyncio
async def test_same_selection_but_nl_subset_does_not_carry_excluded_old_proposal(monkeypatch):
    from casepilot_agent import tasks

    from casepilot_api.agent_router import CaseScopeDecision

    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, collection, workspace = await setup(client)
        cid = workspace["id"]
        cases = [
            await seed(client, collection["id"], title) for title in ["P0 protected", "P1 target"]
        ]
        # Seed an actual P0 record, then use its current revision in canonical selection.
        updated = await client.patch(
            f"/api/v1/test-cases/{cases[0]['id']}",
            json={
                "base_revision_id": cases[0]["current_revision_id"],
                "title": cases[0]["title"],
                "steps": cases[0]["steps"],
                "priority": "P0",
            },
        )
        assert updated.status_code == 200, updated.text
        cases[0] = updated.json()
        protected, target = cases
        await select_cases(client, cid, 0, cases)
        first_op, job = await prepare_draft(client, monkeypatch, cid, 1, "P2")
        first = await finish_worker(client, cid, first_op, job)
        assert {item["ref"] for item in first["items"]} == {case["id"] for case in cases}
        baseline = audit_count(protected["id"])
        monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
        monkeypatch.setattr(
            conversations,
            "select_case_scope",
            lambda *args, **kwargs: CaseScopeDecision(
                ids=[target["id"]],
                ambiguous=False,
                clarification="",
                reference="selection",
                referenced_case_keys=[],
                requested_count=None,
            ),
        )
        second_op, job = await prepare_draft(
            client,
            monkeypatch,
            cid,
            1,
            "P0",
            instruction="仅修改P1用例，把优先级改为P0；不要修改P0用例",
        )
        assert second_op["payload"]["task_id"] == first_op["payload"]["task_id"]
        with get_session_factory()() as db:
            record = db.get(GenerationJob, UUID(job))
            assert set(record.input_payload["previous_proposals"]) == {target["id"]}
        second = await finish_worker(client, cid, second_op, job)
        assert [item["ref"] for item in second["items"]] == [target["id"]]
        approved = await client.post(f"/api/v1/case-change-sets/{second['id']}/apply", json={})
        assert approved.status_code == 200, approved.text
        unchanged = (await client.get(f"/api/v1/test-cases/{protected['id']}")).json()
        assert unchanged["current_revision_id"] == protected["current_revision_id"]
        assert audit_count(protected["id"]) == baseline
