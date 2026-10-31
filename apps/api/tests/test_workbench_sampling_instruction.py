"""Actual ASGI -> guarded job -> planning sampling; no injected test_setup authority."""
import asyncio
from uuid import UUID, uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import RequirementAnalysis, UsageMetadata
from casepilot_agent.providers.mock import MockProvider
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from test_workbench_bridge_integration import activate, setup

from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import GenerationJob
from casepilot_api.models import TestCase as CaseAsset

RULE = "验证码从生成起120秒过期；过期验证码拒绝。"
SAMPLING = "测试按整数秒采样"


class SamplingProvider(MockProvider):
    def __init__(self, literal="", step=None):
        self.literal, self.step = literal, step
        self.contexts = []
        self.label = "Initial"

    def complete(self, *, stage, payload, result_type, **kwargs):
        usage = UsageMetadata(model="offline-sampling")
        if stage == "output_quantity.interpreted":
            return result_type.model_validate({"test_point_count": 1}), usage
        base = getattr(result_type, "__planning_source_base__", result_type)
        if issubclass(base, RequirementAnalysis):
            return result_type.model_validate({"test_object": "Synthetic OTP",
                "test_object_specified": True, "summary": "Not a sampling instruction",
                "open_questions": [], "feature_points": [{"id": "rule", "name": "Expiry",
                    "module": "OTP", "description": RULE, "requirement_refs": []}]}), usage
        if stage == "test_point.generated":
            context = payload["context"]
            self.contexts.append(context)
            assert not context.get("test_setup")
            owner = payload["feature_points"]["feature_points"][0]["id"]
            pair = next(row for row in payload["primary_bindings"] if row["feature_id"] == owner)
            source = next(row for row in payload["source_catalog"]
                          if row["slot"] == pair["source_slot"])
            assert RULE in source["excerpt"]
            choices = [row for row in payload["boundary_evidence_bindings"]
                       if row["source_slot"] == source["slot"] and row["threshold"] == 120]
            evidence_binding = next((row["id"] for row in choices
                                     if row["sampling_step"] == self.step
                                     and row["sampling_literal"] == self.literal),
                                    next(row["id"] for row in choices
                                         if row["sampling_step"] is None))
            samples = [{"obligation_id": "expiry", "position": position,
                "initial_state": "未锁定；验证码刚生成", "assertion": assertion,
                "assertion_role": "primary", "assertion_binding": pair["id"]}
                for position, _, assertion in (
                    [("before", 120 - self.step, "未过期"), ("at", 120, "过期拒绝"),
                     ("after", 120 + self.step, "过期拒绝")] if self.step is not None
                    else [("at", 120, "过期拒绝")])]
            return result_type.model_validate({"test_points": [{"id": "expiry-point",
                "title": f"{self.label} expiry boundary",
                "objective": f"{self.label} observe expiry",
                "scenario": "Explicit initial state and supplied numeric boundary",
                "category": "boundary", "priority": "P1", "priority_reason": "Explicit rule",
                "primary_binding": pair["id"], "boundary_samples": samples}],
                "coverage_obligations": [{"id": "expiry", "feature_point_ids": [owner],
                    "dimension": "boundary", "basis": RULE, "point_ids": ["expiry-point"],
                    "boundary_contract": {"evidence_binding": evidence_binding,
                        "unit": "秒", "comparator": "gte", "axis": "验证码",
                        "time_origin": "生成", "sampling_step": self.step,
                        "sampling_literal": self.literal}}], "duplicate_suggestions": []}), usage
        return super().complete(stage=stage, payload=payload, result_type=result_type, **kwargs)


def install(monkeypatch, provider):
    monkeypatch.setattr(tasks, "create_provider", lambda *a, **kw: provider)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    activate(monkeypatch, [("prepare_generation", {})])


async def submit(client, cid, content):
    response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
        "content": content, "client_request_id": str(uuid4())})
    assert response.status_code == 202, response.text
    job_id = response.json()["action"]["job_id"]
    with get_session_factory()() as db:
        job = db.get(GenerationJob, UUID(job_id))
        assert job.input_payload["prompt"] == content
        assert job.input_payload.get("workbench_run_id")
    return job_id


@pytest.mark.asyncio
@pytest.mark.parametrize("instruction,literal,step,valid", [
    (SAMPLING, SAMPLING, 1, True),
    ("", "", None, True),
    ("", SAMPLING, 1, False),
    ("撤销整数秒采样，不再按整数秒采样", "按整数秒采样", 1, False),
    ("测试按2秒采样", "测试按2秒采样", 2, True),
    ("不遗漏失败场景，按整数秒取样", "按整数秒取样", 1, True),
    (SAMPLING, f"{RULE}{SAMPLING}", 120, False),
    ("按1秒采样", "按1秒采样", 1, True),
    ("sample every 1 秒", "sample every 1 秒", 1, True),
    ("不按1秒采样", "按1秒采样", 1, False),
    ("按1秒采样，不采用上述采样步长", "按1秒采样", 1, False),
    ("Never sample every 1 秒", "sample every 1 秒", 1, False),
])
async def test_actual_nl_sampling_authority(monkeypatch, instruction, literal, step, valid):
    provider = SamplingProvider(literal, step)
    install(monkeypatch, provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        prompt = f"为Synthetic OTP生成测试点。{RULE}{instruction}"
        with get_session_factory()() as db:
            assets = set(db.scalars(select(CaseAsset.id)))
        job_id = await submit(client, cid, prompt)
        if not valid:
            with pytest.raises(ValidationError) as caught:
                await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
            assert any(error["type"] == "planning_boundary_sampling_invalid"
                       for error in caught.value.errors(include_input=False)), [
                       error["type"] for error in caught.value.errors(include_input=False)]
        else:
            await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        assert provider.contexts and provider.contexts[0]["user_input"] == prompt
        has_instruction = instruction in {
            SAMPLING, "测试按2秒采样", "不遗漏失败场景，按整数秒取样",
            "按1秒采样", "sample every 1 秒"}
        assert provider.contexts[0]["sampling_instruction_sources"] == (
            [{"origin": "user_input", "text": prompt}] if has_instruction else [])
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(job_id))
            assert job.status == ("completed" if valid else "failed")
            assert set(db.scalars(select(CaseAsset.id))) == assets
        view = (await client.get(f"/api/v1/conversations/{cid}")).json()
        if not valid:
            assert not view["test_briefs"]
            return
        plan = view["test_briefs"][-1]["content"]["planning"]
        batch = plan["coverage_review"]["batches"][0]
        contract = batch["obligations"][0]["boundary_contract"]
        assert contract["sampling_step"] == step
        assert contract["sampling_literal"] == literal
        assert batch["uncovered_ids"] == ([] if step is not None else ["expiry"])
        assert len(plan["test_points"]) == 1
        assert batch["completion_attempted"] is False
        assert contract["source_ref"]["excerpt"] == prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidate", [None, "new_run", "collection"])
async def test_same_run_continuation_inherits_only_its_original_instruction(
    monkeypatch, invalidate,
):
    from test_workbench_continuation_runtime import event_id, execute, run_state

    provider = SamplingProvider(SAMPLING, 1)
    install(monkeypatch, provider)
    activate(monkeypatch, [
        ("plan_work", {"steps": ["查询用例", "规划测试点"],
                       "plan_actions": ["CASE_QUERY", "CASE_GENERATE"]}),
        ("query_assets", {"scope": "current_collection", "search": ""}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        account, _, workspace = await setup(client)
        cid = workspace["id"]
        prompt = f"先查询当前集合内用例，再为Synthetic OTP生成测试点。{RULE}{SAMPLING}"
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": prompt, "client_request_id": str(uuid4())})
        assert response.status_code == 202, response.text
        state = run_state(cid)
        pending = event_id(state["id"], "next_step")
        if invalidate == "new_run":
            provider.literal, provider.step = "", None
            activate(monkeypatch, [("prepare_generation", {})])
            new_job = await submit(client, cid, f"为Synthetic OTP另行规划测试点。{RULE}")
            await asyncio.to_thread(tasks.draft_test_brief.run, new_job)
            assert provider.contexts[-1]["sampling_instruction_sources"] == []
        elif invalidate == "collection":
            created = await client.post(
                f"/api/v1/spaces/{account['spaces'][0]['id']}/collections",
                json={"name": "Other sampling scope"})
            assert created.status_code == 201, created.text
            changed = await client.patch(f"/api/v1/workspaces/{cid}/selection", json={
                "base_version": 0, "action": "replace", "sources": [],
                "active_collection_id": created.json()["id"]})
            assert changed.status_code == 200, changed.text
        second = activate(monkeypatch, [("prepare_generation", {})])
        if invalidate:
            result = await execute(pending)
            assert result["status"] in {"ignored", "invalidated", "requires_selection"}, result
            assert not second.observations
            return
        result = await execute(pending)
        assert result["status"] in {"waiting_job", "waiting_worker"}, result
        current = run_state(cid)
        assert current["id"] == state["id"]
        job_id = current["checkpoint"]["waiting_job_id"]
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(job_id))
            assert job.input_payload["prompt"] == prompt
            assert job.input_payload["workbench_run_id"] == str(state["id"])
        await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        assert provider.contexts[-1]["sampling_instruction_sources"] == [
            {"origin": "user_input", "text": prompt}]
        view = (await client.get(f"/api/v1/conversations/{cid}")).json()
        contract = view["test_briefs"][-1]["content"]["planning"]["coverage_review"][
            "batches"][0]["obligations"][0]["boundary_contract"]
        assert contract["sampling_step"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("new_instruction,new_literal,new_step", [
    ("", "", None), ("撤销此前采样设置", "", None),
    ("测试按2秒采样", "测试按2秒采样", 2),
])
async def test_new_mutating_round_never_uses_prior_sampling_as_current_authority(
    monkeypatch, new_instruction, new_literal, new_step,
):
    from test_workbench_continuation_runtime import run_state

    provider = SamplingProvider(SAMPLING, 1)
    install(monkeypatch, provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        initial = await submit(client, cid, f"为Synthetic OTP生成测试点。{RULE}{SAMPLING}")
        await asyncio.to_thread(tasks.draft_test_brief.run, initial)
        first_run = run_state(cid)["id"]
        provider.literal, provider.step, provider.label = new_literal, new_step, "New round"
        activate(monkeypatch, [("prepare_generation", {})])
        prompt = f"为Synthetic OTP补充另一组测试点。{RULE}{new_instruction}"
        job_id = await submit(client, cid, prompt)
        await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        with get_session_factory()() as db:
            job = db.get(GenerationJob, UUID(job_id))
            assert job.input_payload["workbench_run_id"] != str(first_run)
        assert provider.contexts[-1]["sampling_instruction_sources"] == (
            [{"origin": "user_input", "text": prompt}] if new_step else [])
        view = (await client.get(f"/api/v1/conversations/{cid}")).json()
        plan = view["test_briefs"][-1]["content"]["planning"]
        batch = plan["coverage_review"]["batches"][0]
        obligation = batch["obligations"][0]
        assert obligation["boundary_contract"]["sampling_step"] == new_step
        assert obligation["boundary_contract"]["sampling_literal"] == new_literal
        assert batch["uncovered_ids"] == ([] if new_step else ["expiry"])
        current = [p for p in plan["test_points"] if p["id"] in obligation["point_ids"]]
        assert current and all(p["title"].startswith("New round") for p in current)
        assert all(sample["assertion_source_ref"]["excerpt"] == prompt
                   for point in current for sample in point["boundary_samples"])


@pytest.mark.asyncio
async def test_actual_attachment_text_cannot_authorize_sampling(monkeypatch, tmp_path):
    from casepilot_api import knowledge

    provider = SamplingProvider(SAMPLING, 1)
    install(monkeypatch, provider)
    monkeypatch.setattr(knowledge.settings, "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(tasks.settings, "knowledge_storage_path", str(tmp_path))
    monkeypatch.setattr(knowledge, "enqueue_task", lambda *a, **kw: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        uploaded = await client.post(f"/api/v1/conversations/{cid}/attachments", files={
            "files": ("reference.txt", f"{RULE}{SAMPLING}".encode(), "text/plain")})
        assert uploaded.status_code == 202, uploaded.text
        await asyncio.to_thread(tasks.index_knowledge_source.run, uploaded.json()["source"]["id"])
        prompt = f"参考附件，为Synthetic OTP生成测试点。{RULE}"
        response = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": prompt, "document_ids": uploaded.json()["document_ids"],
            "client_request_id": str(uuid4())})
        assert response.status_code == 202, response.text
        job_id = response.json()["action"]["job_id"]
        with pytest.raises(ValidationError) as caught:
            await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        assert any(error["type"] == "planning_boundary_sampling_invalid"
                   for error in caught.value.errors(include_input=False)), [
                       error["type"] for error in caught.value.errors(include_input=False)]
        context = provider.contexts[-1]
        assert context["sampling_instruction_sources"] == []
        assert any(SAMPLING in item["excerpt"] for item in context["evidence"])


@pytest.mark.asyncio
async def test_invalid_reconciled_quantity_graph_never_persists_or_completes(monkeypatch):
    from copy import deepcopy

    provider = SamplingProvider(SAMPLING, 1)
    install(monkeypatch, provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        initial = await submit(client, cid, f"为Synthetic OTP生成测试点。{RULE}{SAMPLING}")
        await asyncio.to_thread(tasks.draft_test_brief.run, initial)
        before = (await client.get(f"/api/v1/conversations/{cid}")).json()["test_briefs"]
        provider.literal, provider.step, provider.label = "", None, "New round"
        activate(monkeypatch, [("prepare_generation", {})])
        original = tasks.reconcile_planning

        def broken(*args):
            result = deepcopy(original(*args))
            result["coverage_review"]["batches"] = []
            return result

        monkeypatch.setattr(tasks, "reconcile_planning", broken)
        job_id = await submit(client, cid, f"为Synthetic OTP补充另一组测试点。{RULE}")
        with pytest.raises(ValueError, match="planning_boundary_binding_conflict"):
            await asyncio.to_thread(tasks.draft_test_brief.run, job_id)
        with get_session_factory()() as db:
            assert db.get(GenerationJob, UUID(job_id)).status == "failed"
        after = (await client.get(f"/api/v1/conversations/{cid}")).json()["test_briefs"]
        assert after == before
