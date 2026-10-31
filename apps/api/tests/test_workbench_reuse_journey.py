"""Controlled tool + real ASGI/domain workers; deterministic model, never live calls."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import RequirementAnalysis, UsageMetadata
from casepilot_agent.providers.mock import MockProvider
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup

from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.generation_strategy import interpret_generation_choice
from casepilot_api.main import app
from casepilot_api.models import (
    AuditEvent,
    CollectionCaseMembership,
    GenerationJob,
    WorkspaceTestBrief,
)
from casepilot_api.models import (
    TestCase as CaseRecord,
)
from casepilot_api.models import (
    TestCaseRevision as CaseRevision,
)


class MixedReuseProvider(MockProvider):
    """Model seam only: explicit original + one new gap, not fabricated persisted plans."""

    def __init__(self, source_key, *, force_all_new=False):
        self.reviewer_override = None
        self.background_only = False
        self.new_count_basis = False
        self.quantities = []
        self.force_all_new = force_all_new
        self.source_key = source_key
        self.stages = []

    def complete(self, *, stage, payload, result_type, **kwargs):
        self.stages.append(stage)
        if stage == "output_quantity.interpreted":
            count = (len(payload["confirmed_test_points"]) if self.reviewer_override
                     else 1 if self.background_only else 2)
            result = result_type.model_validate({
                "case_count": 1 if self.new_count_basis else count,
                "count_includes_reuse": not self.new_count_basis,
                "test_point_count": count, "output_case_count": count,
                "new_case_count": count if self.reviewer_override or self.background_only else 1,
                "required_reuse_source_keys": [] if self.reviewer_override or self.background_only
                else [self.source_key],
            })
            self.quantities.append(result.model_dump(mode="json"))
        elif stage == "reuse.compared":
            source_backed = {point["id"] for point in payload["test_points"]
                             if any(self.source_key in ref.get("excerpt", "")
                                    for ref in point.get("source_refs", []))}

            def reuse(point):
                return not self.force_all_new and (
                    point["id"] in source_backed if source_backed else "主流程" in point["title"])

            result = result_type.model_validate({"decisions": [
                {"point_id": point["id"],
                 "action": "reuse"
                 if reuse(point) else "new",
                 "source_key": self.source_key
                 if reuse(point) else None,
                 "test_object_match": "same", "reason": "原样保留主流程，新增异常缺口"}
                for point in payload["test_points"]
            ]})
        else:
            from casepilot_agent.contracts import TestPointPlan

            # This deterministic seam chooses its quota before validating the
            # actual dynamic response, just as a provider must do on the wire.
            response_type = TestPointPlan if stage == "test_point.generated" else result_type
            result, usage = super().complete(
                stage=stage, payload=payload, result_type=response_type, **kwargs
            )
            if stage == "test_point.generated":
                # MockProvider predates per-batch quotas. Emit a valid model
                # response for this fixture's explicitly requested remaining gap.
                count = payload["batch_count"]
                points = [point.model_dump(mode="json") for point in result.test_points[:count]]
                if count == 1:
                    points[0].update(title="验证码无效异常缺口", objective="无效验证码被拒绝",
                        feature_point_ids=[f["id"]
                                           for f in payload["feature_points"]["feature_points"]])
                point_schema = result_type.model_fields["test_points"].annotation.__args__[0]
                if "primary_binding" in point_schema.model_fields:
                    for point in points:
                        point.pop("primary_feature_id", None)
                        point["primary_binding"] = next(pair["id"]
                            for pair in payload["primary_bindings"]
                            if pair["feature_id"] == point["feature_point_ids"][0])
                result = result_type.model_validate({"test_points": points, "coverage_matrix": []})
            if issubclass(result_type, RequirementAnalysis):
                result.test_object = "Account system"
                result.test_object_specified = True
                result.open_questions = []
            return result, usage
        return result, UsageMetadata(model="deterministic-reuse")


async def create_case(client, collection, title):
    response = await client.post(f"/api/v1/collections/{collection}/test-cases", json={
        "title": title, "module": "Account system", "priority": "P1",
        "case_type": "functional", "preconditions": ["Registered account"],
        "steps": [{"action": "Login with valid code", "expected": "Success"}],
    })
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_source_after_review,force_all_new,review_mode", [
    (False, False, None), (True, False, None), (False, True, None),
    (False, True, "partial"), (False, True, "new"), (False, True, "exclude"),
    (False, True, "background"), (False, True, "new_count_basis"),
    (False, True, "fresh"),
])
async def test_controlled_mixed_reuse_new_destination_exact_review_and_adoption(
    monkeypatch, change_source_after_review, force_all_new, review_mode
):
    model_choice = interpret_generation_choice(
        "策略：select_and_generate。测试对象：Account system",
        SimpleNamespace(agent_provider="mock"),
    )
    model_choice.test_object = "Account system"
    monkeypatch.setattr(conversations, "interpret_generation_choice", lambda *a, **kw: model_choice)
    monkeypatch.setattr(conversations.settings, "agent_provider", "openai_compatible")
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as foreign_client,
    ):
        account, origin, _ = await setup(client)
        _, foreign_collection, _ = await setup(foreign_client)
        source = await create_case(client, origin["id"], "Reuse original login")
        unrelated = await create_case(client, origin["id"], "Protected unrelated")
        foreign = await create_case(foreign_client, foreign_collection["id"], source["title"])
        protected_ids = [UUID(case["id"]) for case in (source, unrelated, foreign)]
        with get_session_factory()() as db:
            original_revisions = set(db.scalars(select(CaseRevision.id).where(
                CaseRevision.test_case_id.in_(protected_ids))))
            original_audits = set(db.scalars(select(AuditEvent.id).where(
                AuditEvent.resource_id.in_(protected_ids))))
            original_case_ids = set(db.scalars(select(CaseRecord.id)))
        source_key = f"asset:{source['id']}"
        model = MixedReuseProvider(source_key, force_all_new=force_all_new)
        model.background_only = review_mode == "background"
        model.new_count_basis = review_mode == "new_count_basis"
        monkeypatch.setattr(tasks, "create_provider", lambda *a, **kw: model)
        workspace = (await client.post("/api/v1/conversations", json={
            "space_id": account["spaces"][0]["id"],
        })).json()
        cid = workspace["id"]
        provider = activate(monkeypatch, [
            ("query_assets", {"search": source["title"], "scope": "space"}),
            ("prepare_reuse", {"strategy": "select_and_generate"}),
        ])
        turn = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": ("测试对象：Account system。仅把 Reuse original login 作为背景参考，"
                        "不要求原样复用输出，只新增1条验证码无效的异常用例和1个测试点，组成新集合。"
                        if review_mode == "background" else
                        "测试对象：Account system。原样复用 Reuse original login 这1条主流程，"
                        "再新增1条验证码无效的异常缺口，共2条用例和2个测试点，组成新集合。"),
            "source_collection_ids": [origin["id"]], "client_request_id": str(uuid4()),
        })
        assert turn.status_code == 202, turn.text
        observations = json.dumps(provider.observations)
        assert source["id"] in observations
        assert foreign["id"] not in observations
        operation = turn.json()["operation_plan"]["operations"][0]
        assert operation["payload"]["prepared_request"]["generation_strategy"] == (
            "select_and_generate"
        )
        assert turn.json()["user_message"]["metadata"]["request"]["generation_strategy"] is None
        endpoint = f"/api/v1/conversation-operations/{operation['id']}/confirm-collection"
        blocked = await client.post(endpoint, json={"collection_id": origin["id"]})
        assert blocked.status_code == 422, blocked.text
        assert blocked.json()["detail"] == "generation_new_collection_required"
        choice = {"create_collection_name": "Mixed reuse exact output"}
        bound = await client.post(endpoint, json=choice)
        assert bound.status_code == 202, bound.text
        replay = await client.post(endpoint, json=choice)
        assert replay.status_code == 202, replay.text
        assert replay.json()["action"] == bound.json()["action"]
        with get_session_factory()() as db:
            draft_job = db.get(GenerationJob, UUID(bound.json()["action"]["job_id"]))
            destination = draft_job.collection_id
            assert str(destination) not in {origin["id"], foreign_collection["id"]}
        wrong = await client.post(endpoint, json={"create_collection_name": "Wrong name"})
        assert wrong.status_code == 409, wrong.text
        await asyncio.to_thread(tasks.draft_test_brief.run, bound.json()["action"]["job_id"])
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        brief = state["test_briefs"][-1]
        assert brief["content"]["asset_selection"]["status"] == "awaiting_confirmation", state
        asset_endpoint = f"/api/v1/workspaces/{cid}/generation-assets/confirm"
        stale = await client.post(asset_endpoint, json={"version": 999, "case_ids": [source["id"]]})
        assert stale.status_code == 409, stale.text
        denied = await client.post(asset_endpoint, json={
            "version": brief["version"], "case_ids": [foreign["id"]],
        })
        assert denied.status_code == 422, denied.text
        if change_source_after_review:
            changed = await client.patch(f"/api/v1/test-cases/{source['id']}", json={
                "base_revision_id": source["current_revision_id"], "title": "Changed externally",
                "steps": source["steps"],
            })
            assert changed.status_code == 200, changed.text
            with get_session_factory()() as db:
                jobs_before = set(db.scalars(select(GenerationJob.id)))
            rejected = await client.post(asset_endpoint, json={
                "version": brief["version"], "case_ids": [source["id"]],
            })
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"] == "generation_asset_changed"
            with get_session_factory()() as db:
                assert set(db.scalars(select(GenerationJob.id))) == jobs_before
                assert db.get(CaseRecord, UUID(source["id"])).current_revision_id == UUID(
                    changed.json()["current_revision_id"]
                )
                assert set(db.scalars(select(CollectionCaseMembership.test_case_id).where(
                    CollectionCaseMembership.collection_id == destination))) == set()
            return
        selected = await client.post(asset_endpoint, json={
            "version": brief["version"], "case_ids": [source["id"]],
        })
        assert selected.status_code == 200, selected.text
        await asyncio.to_thread(tasks.draft_test_brief.run, selected.json()["action"]["job_id"])
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        brief = state["test_briefs"][-1]
        if force_all_new and review_mode is None:
            with get_session_factory()() as db:
                jobs_before_review = set(db.scalars(select(GenerationJob.id)))
            # Client-supplied reservations, snapshots, or point authority cannot
            # replace the server-owned exact source even at the same revision.
            for tamper in ("source", "snapshot", "point_snapshots"):
                content = deepcopy(brief["content"])
                reservation = content["planning"]["reserved_reuse_outputs"][0]
                if tamper == "source":
                    reservation["source"]["key"] = f"asset:{foreign['id']}"
                elif tamper == "snapshot":
                    reservation["source"]["snapshot"]["title"] = "Forged source snapshot"
                else:
                    reservation["point_snapshots"] = {}
                rejected = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                    "base_version": brief["version"], "content": content,
                })
                assert rejected.status_code == 409, rejected.text
                assert rejected.json()["detail"] == "reserved_reuse_authority_changed"
            content = deepcopy(brief["content"])
            content["planning"]["point_review_receipt"] = {
                "brief_id": brief["id"], "version": brief["version"], "kind": "points",
                "point_ids": [p["id"] for p in content["planning"]["test_points"]],
            }
            receipt_edit = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                "base_version": brief["version"], "content": content,
            })
            assert receipt_edit.status_code == 201, receipt_edit.text
            brief = receipt_edit.json()
            assert brief["status"] == "draft"
            assert brief.get("confirmed_by") is None
            assert not brief["content"]["planning"].get("point_review_receipt")
            with get_session_factory()() as db:
                assert set(db.scalars(select(GenerationJob.id))) == jobs_before_review
                assert set(db.scalars(select(CaseRecord.id))) == original_case_ids
                saved_brief = db.get(WorkspaceTestBrief, UUID(brief["id"]))
                assert saved_brief.status == "draft" and saved_brief.confirmed_by is None
                assert saved_brief.confirmed_at is None
        draft_plan = brief["content"]["planning"]
        reservations = draft_plan.get("reserved_reuse_outputs", [])
        if force_all_new and review_mode != "background":
            assert len(reservations) == 1
            assert reservations[0]["source"]["key"] == source_key
            assert reservations[0]["source"]["revision"] == source["current_revision_id"]
            assert reservations[0]["action"] == "reuse"
            assert reservations[0]["point_ids"]
            assert set(reservations[0]["point_ids"]) <= {
                point["id"] for point in draft_plan["test_points"]}
        if review_mode == "background":
            assert reservations == []
        if review_mode == "partial":
            protected_points = set(reservations[0]["point_ids"])
            gap_points = [p["id"] for p in draft_plan["test_points"]
                          if p["id"] not in protected_points]
            assert gap_points
            with get_session_factory()() as db:
                jobs_before = set(db.scalars(select(GenerationJob.id)))
            blocked = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
                "version": brief["version"], "selected_test_point_ids": gap_points,
            })
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["detail"] == "reserved_reuse_selection_conflict"
            with get_session_factory()() as db:
                assert set(db.scalars(select(GenerationJob.id))) == jobs_before
                assert set(db.scalars(select(CaseRecord.id))) == original_case_ids
                assert set(db.scalars(select(CaseRevision.id).where(
                    CaseRevision.test_case_id.in_(protected_ids)))) == original_revisions
                assert set(db.scalars(select(AuditEvent.id).where(
                    AuditEvent.resource_id.in_(protected_ids)))) == original_audits
            unchanged = (await client.get(f"/api/v1/conversations/{cid}")).json()["test_briefs"][-1]
            assert unchanged["version"] == brief["version"]
            assert unchanged["content"]["planning"] == draft_plan
            return
        if review_mode in {"new", "exclude"}:
            content = deepcopy(brief["content"])
            content["planning"]["reuse"]["user_choices"] = {
                point: review_mode for point in reservations[0]["point_ids"]}
            edited = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                "base_version": brief["version"], "content": content,
            })
            assert edited.status_code == 201, edited.text
            brief = edited.json()
            model.reviewer_override = review_mode
        if review_mode == "fresh":
            model.reviewer_override = "fresh"  # Quantity interpretation only, no choice pre-write.
        confirmed = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
            "version": brief["version"],
            **({"reuse_confirmation": "fresh"} if review_mode == "fresh" else {}),
        })
        assert confirmed.status_code == 202, confirmed.text
        job_id = confirmed.json()["action"]["job_id"]
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(job_id))
            plan = job.input_payload["confirmed_plan"]
            receipt = plan["point_review_receipt"]
            assert receipt["brief_id"] == brief["id"] and receipt["version"] == brief["version"]
            assert receipt["kind"] == "points"
            assert receipt["point_ids"] == [point["id"] for point in plan["test_points"]]
            if review_mode in {"new", "exclude", "background", "fresh"}:
                assert not plan.get("reserved_reuse_outputs")
                assert source_key not in plan.get("output_obligations", {}).get(
                    "required_reuse_source_keys", [])
            else:
                assert len(plan["test_points"]) == 2
                assert plan["output_obligations"]["required_reuse_source_keys"] == [source_key]
                assert plan["output_obligations"]["output_case_count"] == 2
                assert plan["output_obligations"]["new_case_count"] == 1
            assert [s["key"] for s in plan["approved_source_catalog"]] == [source_key]
            assert plan["approved_source_catalog"][0]["revision"] == source["current_revision_id"]
            if not force_all_new:
                assert plan["reuse"]["summary"] == {"reuse": 1, "new": 1}
        await asyncio.to_thread(tasks.generate_test_cases.run, job_id)
        state = (await client.get(f"/api/v1/conversations/{cid}")).json()
        candidates = state["candidates"]
        if review_mode in {"new", "exclude", "background", "fresh"}:
            expected = 2 if review_mode in {"new", "fresh"} else 1
            assert len(candidates) == expected
            assert all(c["snapshot"]["title"] != source["title"] for c in candidates)
            adopted = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={
                "candidate_ids": [c["id"] for c in candidates],
                "candidate_versions": {c["id"]: c["version"] for c in candidates},
            })
            assert adopted.status_code == 200, adopted.text
            assert len(adopted.json()) == expected
            assert source["id"] not in {c["id"] for c in adopted.json()}
            with get_session_factory()() as db:
                assert set(db.scalars(select(CaseRevision.id).where(
                    CaseRevision.test_case_id.in_(protected_ids)))) == original_revisions
                assert set(db.scalars(select(AuditEvent.id).where(
                    AuditEvent.resource_id.in_(protected_ids)))) == original_audits
                assert len(set(db.scalars(select(CaseRecord.id))) - original_case_ids) == expected
            return
        assert len(candidates) == 2, state
        reused = [candidate for candidate in candidates
                  if candidate["snapshot"]["title"] == source["title"]]
        assert len(reused) == 1
        for field in ("title", "module", "priority", "preconditions"):
            assert reused[0]["snapshot"][field] == source[field]
        assert reused[0]["snapshot"]["steps"] == [
            {key: step[key] for key in ("action", "expected")} for step in source["steps"]
        ]
        with get_session_factory()() as db:
            assert db.get(GenerationJob, UUID(job_id)).status == "completed"
            assert set(db.scalars(select(CaseRecord.id))) == original_case_ids
        stale = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={
            "candidate_ids": [c["id"] for c in candidates],
            "candidate_versions": {c["id"]: c["version"] + 1 for c in candidates},
        })
        assert stale.status_code == 409, stale.text
        adopted = await client.post(f"/api/v1/workspaces/{cid}/candidates/commit", json={
            "candidate_ids": [c["id"] for c in candidates],
            "candidate_versions": {c["id"]: c["version"] for c in candidates},
        })
        assert adopted.status_code == 200, adopted.text
        assert len(adopted.json()) == 2
        assert source["id"] in {c["id"] for c in adopted.json()}
        for owner, case in [(client, source), (client, unrelated), (foreign_client, foreign)]:
            after = (await owner.get(f"/api/v1/test-cases/{case['id']}")).json()
            assert after["current_revision_id"] == case["current_revision_id"]
            assert after["title"] == case["title"]
        with get_session_factory()() as db:
            assert set(db.scalars(select(CaseRevision.id).where(
                CaseRevision.test_case_id.in_(protected_ids)))) == original_revisions
            assert set(db.scalars(select(AuditEvent.id).where(
                AuditEvent.resource_id.in_(protected_ids)))) == original_audits
            assert len(set(db.scalars(select(CaseRecord.id))) - original_case_ids) == 1
            assert set(db.scalars(select(CollectionCaseMembership.test_case_id).where(
                CollectionCaseMembership.collection_id == destination))) == {
                    UUID(case["id"]) for case in adopted.json()
                }
        assert "reuse.compared" in model.stages
        assert "test_case.generated" in model.stages
        assert model.quantities
        assert all(quantity["case_count"] == (1 if model.new_count_basis else 2)
                   and quantity["count_includes_reuse"] is not model.new_count_basis
                   and quantity["test_point_count"] == 2
                   and quantity["output_case_count"] == 2
                   and quantity["new_case_count"] == 1
                   for quantity in model.quantities)


@pytest.mark.asyncio
async def test_pending_reservation_question_cannot_be_removed_by_client_draft_edit():
    """A real stored server blocker survives edits and cannot authorize a job."""
    from casepilot_agent.reuse import normalize_sources

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, origin, workspace = await setup(client)
        source = await create_case(client, origin["id"], "Pending exact source")
        cid = workspace["id"]
        sources = normalize_sources([{
            "ref": source["id"], "snapshot": source, "target_type": "formal",
        }], [])
        blocker = {
            "id": "reserved_reuse_point_budget_requires_clarification",
            "question": "请明确原样复用及新增缺口如何对应唯一测试点，或调整测试点预算。",
            "blocking": True, "impact": "保留精确来源与预算，等待明确范围。",
        }
        content = {
            "test_object": "Account system", "generation_strategy": "select_and_generate",
            "open_questions": [blocker],
            "planning": {
                "feature_points": [], "test_points": [],
                "approved_source_catalog": [{"key": sources[0]["key"],
                                             "revision": source["current_revision_id"]}],
                "pending_reserved_outputs": {
                    "reason": blocker["id"], "required_sources": sources,
                    "quantity": {"test_point_count": 1, "output_case_count": 2,
                                 "new_case_count": 1,
                                 "required_reuse_source_keys": [sources[0]["key"]]},
                },
            },
        }
        with get_session_factory()() as db:
            db.add(WorkspaceTestBrief(conversation_id=UUID(cid), version=1,
                content=content, markdown_content="Synthetic server clarification",
                status="draft", created_by=UUID(account["id"])))
            db.commit()
            original_cases = set(db.scalars(select(CaseRecord.id)))
            original_jobs = set(db.scalars(select(GenerationJob.id)))
            original_revisions = set(db.scalars(select(CaseRevision.id)))
            original_audits = set(db.scalars(select(AuditEvent.id).where(
                AuditEvent.resource_id == UUID(source["id"]))))
        for invalid_shape in ("unknown_reason", "ordinary_empty"):
            invalid = deepcopy(content)
            if invalid_shape == "unknown_reason":
                invalid["planning"]["pending_reserved_outputs"]["reason"] = "not_a_server_reason"
            else:
                invalid["planning"] = {"feature_points": [], "test_points": []}
            rejected = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                "base_version": 1, "content": invalid,
            })
            assert rejected.status_code == 422, rejected.text
        edited = deepcopy(content)
        edited["open_questions"] = []
        response = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
            "base_version": 1, "content": edited,
        })
        assert response.status_code == 201, response.text
        brief = response.json()
        assert brief["version"] == 2 and brief["status"] == "draft"
        assert brief["content"]["open_questions"] == [blocker]
        assert brief["content"]["planning"]["pending_reserved_outputs"] == (
            content["planning"]["pending_reserved_outputs"])
        confirmation = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
            "version": brief["version"],
        })
        assert confirmation.status_code == 409, confirmation.text
        assert confirmation.json()["detail"] == "reserved_reuse_clarification_required"
        with get_session_factory()() as db:
            saved = db.get(WorkspaceTestBrief, UUID(brief["id"]))
            assert saved.status == "draft" and saved.confirmed_by is None
            assert saved.confirmed_at is None
            assert saved.content["open_questions"] == [blocker]
            assert set(db.scalars(select(GenerationJob.id))) == original_jobs
            assert set(db.scalars(select(CaseRecord.id))) == original_cases
            assert set(db.scalars(select(CaseRevision.id))) == original_revisions
            assert set(db.scalars(select(AuditEvent.id).where(
                AuditEvent.resource_id == UUID(source["id"])))) == original_audits
