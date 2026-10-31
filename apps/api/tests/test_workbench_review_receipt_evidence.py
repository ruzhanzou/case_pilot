"""Real API/worker evidence: source approval and point approval are distinct facts."""
import asyncio
from uuid import UUID, uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import RequirementAnalysis, UsageMetadata
from casepilot_agent.providers.mock import MockProvider
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup
from test_workbench_collection_handoff import reuse_semantics
from test_workbench_reuse_journey import create_case

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import ConversationMessage, GenerationJob, WorkspaceTestBrief


class ReferenceOnlyProvider(MockProvider):
    """Deterministic planning, no mandatory reuse implied by permitted references."""
    def complete(self, *, stage, payload, result_type, **kwargs):
        if stage == "output_quantity.interpreted":
            value = result_type.model_validate({"test_point_count": 2})
        elif stage == "reuse.compared":
            value = result_type.model_validate({"decisions": [
                {"point_id": point["id"], "action": "new", "source_key": None,
                 "reason": "Reference permission is not mandatory unchanged output"}
                for point in payload["test_points"]]})
        else:
            value, usage = super().complete(stage=stage, payload=payload,
                                            result_type=result_type, **kwargs)
            if isinstance(value, RequirementAnalysis):
                value.test_object = "Account system"
                value.test_object_specified = True
                value.open_questions = []
            return value, usage
        return value, UsageMetadata(model="offline-reference-only")


@pytest.mark.asyncio
async def test_source_receipt_does_not_confirm_future_automatic_points(monkeypatch):
    reuse_semantics(monkeypatch)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    monkeypatch.setattr(tasks, "create_provider", lambda *a, **k: ReferenceOnlyProvider())
    activate(monkeypatch, [("prepare_reuse", {"strategy": "select_and_generate"})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, origin, _ = await setup(client)
        source = await create_case(client, origin["id"], "Login reference")
        workspace = (await client.post("/api/v1/conversations", json={
            "space_id": account["spaces"][0]["id"]})).json()
        cid = workspace["id"]
        turn = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": "参考登录用例，为Account system规划2个测试点，组成新集合。",
            "source_collection_ids": [origin["id"]], "client_request_id": str(uuid4())})
        assert turn.status_code == 202, turn.text
        operation = turn.json()["operation_plan"]["operations"][0]
        destination = await client.post(
            f"/api/v1/conversation-operations/{operation['id']}/confirm-collection",
            json={"create_collection_name": "Review boundaries"})
        assert destination.status_code == 202, destination.text
        await asyncio.to_thread(tasks.draft_test_brief.run, destination.json()["action"]["job_id"])
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        source_brief = state["test_briefs"][-1]
        assert not source_brief["content"].get("asset_base_planning", {}).get("test_points")
        invented_point = await client.post(
            f"/api/v1/workspaces/{cid}/generation-assets/confirm", json={
                "version": source_brief["version"], "case_ids": [source["id"]],
                "test_point_ids": ["not-yet-planned"]})
        assert invented_point.status_code == 422
        assert invented_point.json()["detail"] == "asset_target_scope_invalid"
        selected = await client.post(f"/api/v1/workspaces/{cid}/generation-assets/confirm", json={
            "version": source_brief["version"], "case_ids": [source["id"]]})
        assert selected.status_code == 200, selected.text
        second_job_id = UUID(selected.json()["action"]["job_id"])
        with get_session_factory()() as db:
            approved = db.scalar(select(WorkspaceTestBrief).where(
                WorkspaceTestBrief.conversation_id == UUID(cid),
                WorkspaceTestBrief.version == source_brief["version"]))
            assert approved.status == "confirmed" and approved.confirmed_by == UUID(account["id"])
            job = db.get(GenerationJob, second_job_id)
            assert job.input_payload["current_test_brief_version"] == approved.version
            assert job.input_payload["asset_selection_confirmed"] is True
            assert not job.input_payload["current_test_brief"]["planning"].get("test_points")
            sources = job.input_payload["confirmed_asset_sources"]
            assert len(sources) == 1 and sources[0]["key"] == f"asset:{source['id']}"
            assert sources[0]["snapshot"]["current_revision_id"] == source["current_revision_id"]
        await asyncio.to_thread(tasks.draft_test_brief.run, str(second_job_id))
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        point_brief = state["test_briefs"][-1]
        point_ids = [point["id"] for point in point_brief["content"]["planning"]["test_points"]]
        assert len(point_ids) == 2 and point_brief["version"] > source_brief["version"]
        with get_session_factory()() as db:
            draft = db.scalar(select(WorkspaceTestBrief).where(
                WorkspaceTestBrief.conversation_id == UUID(cid),
                WorkspaceTestBrief.version == point_brief["version"]))
            assert draft.status == "draft"
            assert draft.confirmed_by is None and draft.confirmed_at is None
            assert not draft.content["planning"].get("selection_context")
        stale = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
            "version": source_brief["version"], "selected_test_point_ids": [point_ids[0]]})
        assert stale.status_code == 409
        confirmed = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
            "version": point_brief["version"], "selected_test_point_ids": [point_ids[0]]})
        assert confirmed.status_code == 202, confirmed.text
        with get_session_factory()() as db:
            reviewed = db.scalar(select(WorkspaceTestBrief).where(
                WorkspaceTestBrief.conversation_id == UUID(cid),
                WorkspaceTestBrief.version == point_brief["version"]))
            assert reviewed.status == "confirmed"
            assert reviewed.confirmed_by == UUID(account["id"])
            assert reviewed.confirmed_at is not None
            job = db.get(GenerationJob, UUID(confirmed.json()["action"]["job_id"]))
            assert job.input_payload["confirmed_test_brief_version"] == point_brief["version"]
            plan = job.input_payload["confirmed_plan"]
            assert [point["id"] for point in plan["test_points"]] == [point_ids[0]]
            assert plan["selection_context"]["selected_test_point_ids"] == [point_ids[0]]
            assert set(plan["selection_context"]["original_test_point_ids"]) == set(point_ids)
            approvals = list(db.scalars(select(ConversationMessage).where(
                ConversationMessage.conversation_id == UUID(cid))))
            assert any(item.message_metadata.get("generation_asset_confirmation")
                       for item in approvals)
