"""Real worker -> brief/API coverage projection; no provider/network or fake receipts."""
import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import RequirementAnalysis, UsageMetadata
from casepilot_agent.providers.mock import MockProvider
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import GenerationJob, WorkspaceTestBrief
from casepilot_api.models import TestCase as CaseAsset


class CoverageProvider(MockProvider):
    def __init__(self, mode):
        self.mode = mode
        self.stages = []

    def complete(self, *, stage, payload, result_type, **kwargs):
        self.stages.append(stage)
        if stage == "output_quantity.interpreted":
            quantity = {} if self.mode == "scope_limit" else {"test_point_count": 1}
            return result_type.model_validate(quantity), UsageMetadata(model="offline-coverage")
        base = getattr(result_type, "__planning_source_base__", result_type)
        if issubclass(base, RequirementAnalysis):
            data = {"test_object": "Synthetic rules", "test_object_specified": True,
                    "summary": "Explicit synthetic rules only", "open_questions": [],
                    "feature_points": [{"id": f"f{i}", "name": f"Rule {i}", "module": "Rules",
                        "description": "Input at limit is accepted", "requirement_refs": []}
                        for i in range(97 if self.mode == "scope_limit" else 1)]}
            return result_type.model_validate(data), UsageMetadata(model="offline-coverage")
        if stage == "test_point.generated":
            owner = payload["feature_points"]["feature_points"][0]["id"]
            data = {"test_points": [{"id": "p1", "title": "At limit", "objective": "Accepted",
                "scenario": "At supplied limit", "category": "boundary", "priority": "P1",
                "priority_reason": "Explicit rule", "feature_point_ids": [owner],
                "primary_binding": next(pair["id"] for pair in payload["primary_bindings"]
                                        if pair["feature_id"] == owner),
                "source_refs": [{"locator": payload["source_catalog"][0]["slot"],
                                 "label": "Input"}]}],
                "coverage_obligations": [
                    {"id": "at", "feature_point_ids": [owner], "dimension": "normal",
                     "basis": "Input at limit is accepted", "point_ids": ["p1"]},
                    {"id": "above", "feature_point_ids": [owner], "dimension": "exception",
                     "basis": "Input above limit is rejected", "point_ids": []}],
                "duplicate_suggestions": []}
            if self.mode == "unknown":
                data["coverage_obligations"] = [{"id": "at", "feature_point_ids": [owner],
                    "dimension": "boundary", "basis": "Input at limit is accepted",
                    "point_ids": [], "clarification": "请提供阈值与测试采样精度"}]
            if self.mode == "unresolved":
                data["coverage_obligations"] = [{"id": "at", "feature_point_ids": [owner],
                    "dimension": "boundary", "basis": "Input at limit is accepted",
                    "point_ids": [], "boundary_contract": {
                        "status": "unresolved", "reason": "尚未提供可核验的数值阈值与采样单位"}}]
            if self.mode == "boundary":
                source = next(row for row in payload["source_catalog"] if "120秒" in row["excerpt"])
                evidence_binding = next(row["id"] for row in payload["boundary_evidence_bindings"]
                                        if row["source_slot"] == source["slot"]
                                        and row["threshold"] == 120
                                        and row["sampling_step"] is None)
                literal = "验证码从生成起120秒过期"
                data["coverage_obligations"] = [{"id": "at", "feature_point_ids": [owner],
                    "dimension": "boundary", "basis": literal, "point_ids": ["p1"],
                    "boundary_contract": {"evidence_binding": evidence_binding, "unit": "秒",
                        "comparator": "gte", "axis": "验证码", "time_origin": "生成"}}]
                data["test_points"][0]["boundary_samples"] = [{
                    "obligation_id": "at", "position": "at", "value": 120,
                    "initial_state": "未锁定；验证码刚生成", "assertion": "拒绝过期验证码",
                    "assertion_role": "primary",
                    "assertion_binding": next(pair["id"] for pair in payload["primary_bindings"]
                                              if pair["feature_id"] == owner)}]
            return result_type.model_validate(data), UsageMetadata(model="offline-coverage")
        return super().complete(stage=stage, payload=payload, result_type=result_type, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["explicit", "scope_limit", "legacy", "boundary", "unknown",
                                 "unresolved"])
async def test_coverage_metadata_survives_worker_and_api_without_false_full_coverage(
    monkeypatch, mode
):
    model = CoverageProvider(mode)
    monkeypatch.setattr(tasks, "create_provider", lambda *a, **kw: model)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    activate(monkeypatch, [("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        turn = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": ("为Synthetic rules规划测试：验证码从生成起120秒过期；过期验证码拒绝。"
                        if mode == "boundary" else
                        "为Synthetic rules规划测试：到达给定阈值接受，超过阈值拒绝。"),
            "client_request_id": str(uuid4())})
        assert turn.status_code == 202, turn.text
        job_id = turn.json()["action"]["job_id"]
        await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        response = await client.get(f"/api/v1/conversations/{cid}")
        assert response.status_code == 200, response.text
        brief = response.json()["test_briefs"][-1]
        plan = brief["content"]["planning"]
        coverage = plan["coverage_review"]
        assert coverage["status"] == "pending_independent_review"
        assert coverage["source"] == "model_proposed"
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(job_id))
            assert job.status == "completed"
            assert job.output_payload["test_brief"]["planning"]["coverage_review"] == coverage
        if mode == "legacy":
            from casepilot_agent.contracts import FeaturePoint, TestPoint
            from casepilot_agent.output_obligations import plan_fingerprint
            from casepilot_agent.planning import planned_module

            legacy_content = deepcopy(brief["content"])
            legacy_plan = legacy_content["planning"]
            first = legacy_plan["feature_points"][0]
            second = {**deepcopy(first), "id": "legacy-secondary", "name": "Secondary"}
            legacy_plan["feature_points"].append(second)
            legacy_point = legacy_plan["test_points"][0]
            legacy_point.pop("primary_feature_id")
            legacy_point["feature_point_ids"] = [second["id"], first["id"]]
            fingerprint = plan_fingerprint(legacy_plan)
            module = planned_module(TestPoint.model_validate(legacy_point),
                                    [FeaturePoint.model_validate(f)
                                     for f in legacy_plan["feature_points"]])
            assert module != "Rules/Secondary"
            edited = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                "base_version": brief["version"], "content": legacy_content})
            assert edited.status_code == 201, edited.text
            brief = edited.json()
            recovered = await client.get(f"/api/v1/conversations/{cid}")
            plan = recovered.json()["test_briefs"][-1]["content"]["planning"]
            assert "primary_feature_id" not in plan["test_points"][0]
            assert plan_fingerprint(plan) == fingerprint
            assert plan["test_points"] == legacy_plan["test_points"]
        if mode in {"explicit", "legacy", "boundary", "unknown", "unresolved"}:
            point = plan["test_points"][0]
            if mode == "explicit":
                assert point["primary_feature_id"] == point["feature_point_ids"][0]
                assert point["primary_feature_id"] in {f["id"] for f in plan["feature_points"]}
            with get_session_factory()() as db:
                stored = db.get(WorkspaceTestBrief, UUID(brief["id"]))
                assert stored.content["planning"]["test_points"] == plan["test_points"]
                asset_ids = set(db.scalars(select(CaseAsset.id)))
            for invalid in ("foreign-feature", "", "   ", None, 123):
                invalid_content = deepcopy(brief["content"])
                invalid_content["planning"]["test_points"][0]["primary_feature_id"] = invalid
                rejected = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                    "base_version": brief["version"], "content": invalid_content})
                assert rejected.status_code == 422, rejected.text
            assert len(plan["test_points"]) == 1
            assert model.stages.count("test_point.generated") == 1
            batch = coverage["batches"][0]
            if mode in {"unknown", "unresolved"}:
                assert batch["uncovered_ids"] == []
                reason = ("尚未提供可核验的数值阈值与采样单位" if mode == "unresolved"
                          else "请提供阈值与测试采样精度")
                assert batch["clarifications"] == [reason]
                assert batch["obligations"][0]["point_ids"] == []
                if mode == "unresolved":
                    assert not batch["obligations"][0].get("boundary_contract")
                    assert not point.get("boundary_samples")
                    assert point["title"] == "At limit"
                    assert point["scenario"] == "At supplied limit"
                    assert point["source_refs"]
                    assert point["primary_feature_id"] in point["feature_point_ids"]
            else:
                assert batch["uncovered_ids"] == (["at"] if mode == "boundary" else ["above"])
            if mode == "boundary":
                from casepilot_agent.planning_boundary import point_boundary_markdown
                contract = batch["obligations"][0]["boundary_contract"]
                sample = point["boundary_samples"][0]
                assert contract["sampling_step"] is None
                assert contract["status"] == "model_proposed"
                assert contract["quantity_axis_id"].startswith("qaxis:")
                assert sample["quantity_axis_id"] == contract["quantity_axis_id"]
                assert "boundary_semantics_requires_review" in batch["warnings"]
                assert "source_slot" not in contract
                original_prompt = (
                    "为Synthetic rules规划测试：验证码从生成起120秒过期；过期验证码拒绝。")
                assert contract["source_ref"]["excerpt"] == original_prompt
                assert sample["value"] == 120 and sample["unit"] == "秒"
                assert sample["assertion_feature_id"] == point["primary_feature_id"]
                assert "assertion_binding" not in sample
                assert "assertion_source_slot" not in sample
                assert sample["assertion_source_ref"]["excerpt"] == original_prompt
                exported_lines = {line.strip() for line in brief["markdown_content"].splitlines()}
                assert all(line.strip() in exported_lines
                           for line in point_boundary_markdown(point).splitlines())
                for tamper in ("missing_sample_ref", "sample_slot", "sample_binding",
                               "missing_contract_ref", "contract_slot", "unknown_field",
                               "contract_quantity_id", "sample_quantity_id",
                               "missing_sample_quantity_id", "missing_contract_quantity_id",
                               "quantity_unit", "sample_unit", "sample_value"):
                    malformed = deepcopy(brief["content"])
                    bad_point = malformed["planning"]["test_points"][0]
                    bad_sample = bad_point["boundary_samples"][0]
                    bad_contract = malformed["planning"]["coverage_review"]["batches"][0][
                        "obligations"][0]["boundary_contract"]
                    if tamper == "missing_sample_ref":
                        bad_sample["assertion_source_ref"] = None
                    elif tamper == "sample_slot":
                        bad_sample["assertion_source_slot"] = "source:0"
                    elif tamper == "sample_binding":
                        bad_sample["assertion_binding"] = "primary:0"
                    elif tamper == "missing_contract_ref":
                        bad_contract["source_ref"] = None
                    elif tamper == "contract_slot":
                        bad_contract["source_slot"] = "source:0"
                    elif tamper == "contract_quantity_id":
                        bad_contract["quantity_axis_id"] = "qaxis:" + "0" * 64
                    elif tamper == "sample_quantity_id":
                        bad_sample["quantity_axis_id"] = "qaxis:" + "0" * 64
                    elif tamper == "missing_sample_quantity_id":
                        bad_sample.pop("quantity_axis_id")
                    elif tamper == "missing_contract_quantity_id":
                        bad_contract.pop("quantity_axis_id")
                    elif tamper == "quantity_unit":
                        bad_contract["unit"] = "次"
                    elif tamper == "sample_unit":
                        bad_sample["unit"] = "days"
                    elif tamper == "sample_value":
                        bad_sample["value"] = 9999
                    else:
                        bad_sample["raw_response"] = "secret"
                    invalid_response = await client.post(
                        f"/api/v1/workspaces/{cid}/test-briefs", json={
                            "base_version": brief["version"], "content": malformed})
                    assert invalid_response.status_code == 422, invalid_response.text
                for tamper in ("downgrade_to_legacy", "replace_sampling_authority"):
                    changed = deepcopy(brief["content"])
                    changed_sample = changed["planning"]["test_points"][0]["boundary_samples"][0]
                    changed_contract = changed["planning"]["coverage_review"]["batches"][0][
                        "obligations"][0]["boundary_contract"]
                    if tamper == "downgrade_to_legacy":
                        changed_sample.pop("quantity_axis_id")
                        changed_contract.pop("quantity_axis_id")
                    else:
                        changed_contract.update(sampling_step=2, sampling_literal="按2秒采样")
                    rejected = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                        "base_version": brief["version"], "content": changed})
                    assert rejected.status_code == 409, rejected.text
                    assert rejected.json()["detail"] == (
                        "planning_boundary_quantity_identity_changed")
                edited = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                    "base_version": brief["version"], "content": deepcopy(brief["content"])})
                assert edited.status_code == 201, edited.text
                brief = edited.json()
                assert all(line.strip() in {line.strip() for line in
                           brief["markdown_content"].splitlines()}
                           for line in point_boundary_markdown(point).splitlines())
            assert batch["completion_attempted"] is False
            forged = deepcopy(brief["content"])
            forged["planning"]["test_points"] = []
            forged["planning"]["pending_planning_clarification"] = {
                "reason": "coverage_scope_limit"}
            forged["planning"]["coverage_review"]["warnings"] = ["coverage_scope_limit"]
            rejected = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                "base_version": brief["version"], "content": forged})
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["detail"] == "planning_clarification_authority_changed"
            confirmed = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
                "version": brief["version"]})
            assert confirmed.status_code == 202, confirmed.text
            with get_session_factory()() as db:
                generation = db.get(GenerationJob, UUID(confirmed.json()["action"]["job_id"]))
                assert generation.input_payload["confirmed_plan"]["coverage_review"] == coverage
                assert (generation.input_payload["confirmed_plan"]["test_points"]
                        == plan["test_points"])
                if mode == "legacy":
                    assert (plan_fingerprint(generation.input_payload["confirmed_plan"])
                            == fingerprint)
                    assert planned_module(TestPoint.model_validate(plan["test_points"][0]),
                                          [FeaturePoint.model_validate(f)
                                           for f in plan["feature_points"]]) == module
                assert set(db.scalars(select(CaseAsset.id))) == asset_ids
                assert len(generation.input_payload["confirmed_plan"]["test_points"]) == 1
        else:
            assert not plan["test_points"]
            assert "coverage_scope_limit" in coverage["warnings"]
            assert any(q["blocking"] for q in brief["content"]["open_questions"])
            assert "test_point.generated" not in model.stages
            with get_session_factory()() as db:
                job_ids = set(db.scalars(select(GenerationJob.id)))
            # Neither arbitrary empty plans nor a changed server marker gain authority.
            for tamper, status in (("ordinary_empty", 422), ("unknown_reason", 422)):
                content = deepcopy(brief["content"])
                if tamper == "ordinary_empty":
                    content["planning"].pop("pending_planning_clarification")
                else:
                    content["planning"]["pending_planning_clarification"] = {"reason": "invented"}
                rejected = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                    "base_version": brief["version"], "content": content})
                assert rejected.status_code == status, rejected.text
            content = deepcopy(brief["content"])
            content["open_questions"] = []
            edited = await client.post(f"/api/v1/workspaces/{cid}/test-briefs", json={
                "base_version": brief["version"], "content": content})
            assert edited.status_code == 201, edited.text
            brief = edited.json()
            assert any(q["id"] == "coverage_scope_limit" and q["blocking"]
                       for q in brief["content"]["open_questions"])
            confirmed = await client.post(f"/api/v1/workspaces/{cid}/test-briefs/confirm", json={
                "version": brief["version"]})
            assert confirmed.status_code == 409, confirmed.text
            assert confirmed.json()["detail"] == "planning_scope_clarification_required"
            with get_session_factory()() as db:
                assert set(db.scalars(select(GenerationJob.id))) == job_ids
