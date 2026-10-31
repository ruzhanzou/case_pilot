"""Real source-review authority can narrow a pending must; model omission cannot."""
import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import UsageMetadata
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup
from test_workbench_collection_handoff import reuse_semantics
from test_workbench_reuse_journey import MixedReuseProvider, create_case

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import CollectionCaseMembership, GenerationJob, WorkspaceTestBrief
from casepilot_api.models import TestCase as CaseRecord
from casepilot_api.models import TestCaseRevision as CaseRevision


class RecoveryProvider(MixedReuseProvider):
    def complete(self, *, stage, payload, result_type, **kwargs):
        if stage == "output_quantity.interpreted" and self.reviewer_override:
            self.quantities.append({"required_reuse_source_keys": []})
            result = result_type.model_validate({
                "case_count": 2, "count_includes_reuse": True,
                "test_point_count": 2, "output_case_count": 2, "new_case_count": 1,
                "required_reuse_source_keys": [],
            })
            return result, UsageMetadata(model="offline-omitted-must")
        return super().complete(stage=stage, payload=payload, result_type=result_type, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("retain_source", [False, True])
async def test_actual_new_source_confirmation_recovers_pending_without_model_authority(
    monkeypatch, retain_source
):
    reuse_semantics(monkeypatch)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as foreign_client,
    ):
        account, origin, _ = await setup(client)
        _, foreign_origin, _ = await setup(foreign_client)
        source = await create_case(client, origin["id"], "Required login source")
        foreign = await create_case(foreign_client, foreign_origin["id"], "Foreign source")
        model = RecoveryProvider(f"asset:{source['id']}", force_all_new=True)
        monkeypatch.setattr(tasks, "create_provider", lambda *a, **kw: model)
        cid = (await client.post("/api/v1/conversations", json={
            "space_id": account["spaces"][0]["id"]})).json()["id"]
        points = [{"id": f"manual-point-{index}", "title": f"Reviewed scenario {index}",
                   "objective": "Reject invalid code", "scenario": "Registered account",
                   "category": "functional", "priority": "P1", "priority_reason": "Core rule",
                   "feature_point_ids": ["manual-feature"]} for index in range(2)]
        content = {"test_object": "Account system", "generation_strategy": "select_and_generate",
                   "planning": {"feature_points": [{"id": "manual-feature", "name": "Login",
                       "description": "Validate code", "module": "Account system",
                       "requirement_refs": []}], "test_points": points}}
        manual = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
            "content": content})
        assert manual.status_code == 201, manual.text
        original_ids = [point["id"] for point in points]
        with get_session_factory()() as db:
            cases_before = set(db.scalars(select(CaseRecord.id)))
            revisions_before = set(db.scalars(select(CaseRevision.id)))
            memberships_before = set(db.execute(select(
                CollectionCaseMembership.collection_id, CollectionCaseMembership.test_case_id)))

        async def review(round_number):
            activate(monkeypatch, [("prepare_reuse", {"strategy": "select_and_generate"})])
            turn = await client.post(f"/api/v1/conversations/{cid}/messages", json={
                "content": ("测试对象Account system。保留已有测试点范围，"
                            "重新确认原样复用来源并新增缺口。"),
                "source_collection_ids": [origin["id"]], "client_request_id": str(uuid4())})
            assert turn.status_code == 202, turn.text
            action = turn.json()["action"]
            if action["type"] == "collection_confirmation":
                operation = turn.json()["operation_plan"]["operations"][0]
                bound = await client.post(
                    f"/api/v1/conversation-operations/{operation['id']}/confirm-collection",
                    json={"create_collection_name": f"Pending review {round_number}"})
                assert bound.status_code == 202, bound.text
                action = bound.json()["action"]
            await asyncio.to_thread(tasks.draft_test_brief.run, action["job_id"])
            state = (await client.get(f"/api/v1/conversations/{cid}")).json()
            brief = state["test_briefs"][-1]
            assert brief["content"]["asset_selection"]["status"] == "awaiting_confirmation"
            return brief

        async def confirm(brief, selected):
            endpoint = f"/api/v1/workspaces/{cid}/generation-assets/confirm"
            for version, ids, expected in [
                (brief["version"] - 1, selected, 409),
                (brief["version"], [foreign["id"]], 422),
                (brief["version"], [str(uuid4())], 422),
            ]:
                rejected = await client.post(endpoint, json={"version": version,
                    "case_ids": ids, "test_point_ids": original_ids})
                assert rejected.status_code == expected, rejected.text
            result = await client.post(endpoint, json={"version": brief["version"],
                "case_ids": selected, "test_point_ids": original_ids})
            assert result.status_code == 200, result.text
            job_id = result.json()["action"]["job_id"]
            with get_session_factory()() as db:
                job = db.get(GenerationJob, UUID(job_id))
                assert job.input_payload["asset_selection_confirmed"] is True
                assert [s["case_id"] for s in
                        job.input_payload["confirmed_asset_sources"]] == selected
                plan = job.input_payload["current_test_brief"]["planning"]
                assert set(plan["point_review_receipt"]["point_ids"]) == set(original_ids)
                approved = db.get(WorkspaceTestBrief, UUID(brief["id"]))
                assert approved.confirmed_by == UUID(account["id"])
            await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
            state = (await client.get(f"/api/v1/conversations/{cid}")).json()
            return state["test_briefs"][-1]

        first_review = await review(1)
        blocked = await confirm(first_review, [source["id"]])
        plan = blocked["content"]["planning"]
        assert plan["pending_reserved_outputs"]["reason"] == (
            "reserved_reuse_mapping_requires_clarification")
        before_points = deepcopy(plan["test_points"])
        assert [p["id"] for p in before_points] == original_ids
        assert any(q["blocking"] for q in blocked["content"]["open_questions"])
        model.reviewer_override = "model_omits_required_sources"
        second_review = await review(2)
        recovered = await confirm(second_review, [source["id"]] if retain_source else [])
        plan = recovered["content"]["planning"]
        assert model.quantities[-1]["required_reuse_source_keys"] == []
        assert plan["test_points"] == before_points
        if retain_source:
            assert plan["pending_reserved_outputs"]["quantity"]["required_reuse_source_keys"] == [
                f"asset:{source['id']}"]
            assert any(q["blocking"] for q in recovered["content"]["open_questions"])
        else:
            assert not any(q.get("blocking") for q in recovered["content"]["open_questions"])
            assert not plan.get("pending_reserved_outputs")
            assert not plan.get("reserved_reuse_outputs")
            assert plan["output_obligations"]["required_reuse_source_keys"] == []
        with get_session_factory()() as db:
            assert set(db.scalars(select(CaseRecord.id))) == cases_before
            assert set(db.scalars(select(CaseRevision.id))) == revisions_before
            assert set(db.execute(select(
                CollectionCaseMembership.collection_id,
                CollectionCaseMembership.test_case_id))) == memberships_before
