"""Short NL probe's real ASGI/domain protocol with explicit offline provider seams."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from casepilot_agent import tasks
from casepilot_agent.contracts import RequirementAnalysis, UsageMetadata
from casepilot_agent.providers.mock import MockProvider
from httpx import ASGITransport, AsyncClient
from test_workbench_bridge_integration import activate

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/qa"))
import workbench_agent_live_sampling_probe as probe


class DomainProvider(MockProvider):
    def __init__(self, empty=False):
        self.empty = empty
        self.contexts = []

    def complete(self, *, stage, payload, result_type, **kwargs):
        usage = UsageMetadata(model="offline-nl-protocol")
        if stage == "output_quantity.interpreted":
            return result_type.model_validate({"test_point_count": 1}), usage
        base = getattr(result_type, "__planning_source_base__", result_type)
        if issubclass(base, RequirementAnalysis):
            return result_type.model_validate({"test_object": "Synthetic OTP",
                "test_object_specified": True, "summary": "Explicit synthetic requirement",
                "open_questions": [], "feature_points": [{"id": "unlock", "module": "OTP",
                    "name": "Lock duration", "description": probe.RULES["OTP-3"],
                    "requirement_refs": ["OTP-3"]}]}), usage
        if stage == "test_point.generated":
            context = payload["context"]
            self.contexts.append(context)
            assert context["user_input"] == probe.PROMPT
            assert not context.get("test_setup")
            assert context["sampling_instruction_sources"] == [
                {"origin": "user_input", "text": probe.PROMPT}]
            pair = payload["primary_bindings"][0]
            owner = pair["feature_id"]
            evidence_binding = next(row["id"] for row in payload["boundary_evidence_bindings"]
                                    if row["source_slot"] == pair["source_slot"]
                                    and row["threshold"] == 600
                                    and row["sampling_step"] == 1
                                    and "触发锁定起" in row["source_literal"])
            # This is a protocol fixture, not an independent coverage verdict.
            # Use the stated single-threshold lock rule; compound ranges remain unverified.
            point = {"id": "unlock", "title": "Lock duration boundary",
                "objective": "Validate unlock",
                "scenario": ("Locked at zero; preseed a correct fresh code "
                             "without changing counters"),
                "category": "boundary",
                "priority": "P1", "priority_reason": "Core rule", "primary_binding": pair["id"]}
            if not self.empty:
                point["boundary_samples"] = [{"obligation_id": "unlock", "position": position,
                    "initial_state": "从0秒触发锁定；预置正确新鲜验证码且不改变计数",
                    "assertion": assertion, "assertion_role": "primary",
                    "assertion_binding": pair["id"]}
                    for position, _, assertion in [("before", 599, "锁定期间拒绝"),
                        ("at", 600, "解除锁定"), ("after", 601, "已解除锁定")]]
            return result_type.model_validate({"test_points": [point], "coverage_obligations": [{
                "id": "unlock", "feature_point_ids": [owner], "dimension": "boundary",
                "basis": probe.RULES["OTP-3"], "point_ids": ["unlock"], "boundary_contract": {
                    "evidence_binding": evidence_binding,
                    "unit": "秒", "comparator": "gte", "axis": "锁定",
                    "time_origin": "触发锁定起"}}],
                "duplicate_suggestions": []}), usage
        return super().complete(stage=stage, payload=payload, result_type=result_type, **kwargs)


class RangeUnverifiedProvider(DomainProvider):
    """Same full NL prompt; unsupported range is visible, never certified by mock."""
    def complete(self, *, stage, payload, result_type, **kwargs):
        if stage == "test_point.generated":
            assert payload["context"]["user_input"] == probe.PROMPT
            assert not payload["context"].get("test_setup")
            pair = payload["primary_bindings"][0]
            return result_type.model_validate({"test_points": [{
                "id": "range-review", "title": "Review expiry range before certification",
                "objective": "Check the supplied expiry rule without inventing coordinates",
                "scenario": "Use a correct code in an unlocked state; numeric range needs review",
                "category": "boundary", "priority": "P1", "priority_reason": "Explicit rule",
                "primary_binding": pair["id"]}], "coverage_obligations": [{
                    "id": "expiry-range", "feature_point_ids": [pair["feature_id"]],
                    "dimension": "boundary", "basis": probe.RULES["OTP-1"], "point_ids": [],
                    "boundary_contract": {"status": "unresolved",
                        "reason": "0≤t<120秒复合范围暂未结构核验；120与121秒覆盖仍需独立复核"}}],
                "duplicate_suggestions": []}), UsageMetadata(model="offline-range-unverified")
        base = getattr(result_type, "__planning_source_base__", result_type)
        if issubclass(base, RequirementAnalysis):
            return result_type.model_validate({"test_object": "Synthetic OTP",
                "test_object_specified": True, "summary": "Explicit synthetic requirement",
                "open_questions": [], "feature_points": [{"id": "expiry", "module": "OTP",
                    "name": "Expiry", "description": probe.RULES["OTP-1"],
                    "requirement_refs": ["OTP-1"]}]}), UsageMetadata(
                        model="offline-range-unverified")
        return super().complete(stage=stage, payload=payload, result_type=result_type, **kwargs)


@pytest.mark.asyncio
async def test_original_full_nl_prompt_returns_honest_unverified_range_without_formal_write(
    monkeypatch,
):
    from sqlalchemy import select
    from test_workbench_bridge_integration import setup

    from casepilot_api.database import get_session_factory
    from casepilot_api.main import app
    from casepilot_api.models import TestCase, TestCaseRevision

    model = RangeUnverifiedProvider()
    monkeypatch.setattr(tasks, "create_provider", lambda *a, **kw: model)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    activate(monkeypatch, [("prepare_generation", {})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, workspace = await setup(client)
        cid = workspace["id"]
        with get_session_factory()() as db:
            before = [set(db.scalars(select(kind.id))) for kind in (TestCase, TestCaseRevision)]
        submitted = await client.post(f"/api/v1/conversations/{cid}/messages", json={
            "content": probe.PROMPT, "client_request_id": str(uuid4())})
        assert submitted.status_code == 202, submitted.text
        await asyncio.to_thread(tasks.draft_test_brief.run, submitted.json()["action"]["job_id"])
        view = (await client.get(f"/api/v1/conversations/{cid}")).json()
        plan = view["test_briefs"][-1]["content"]["planning"]
        assert len(plan["test_points"]) == 1
        point = plan["test_points"][0]
        assert point["title"] == "Review expiry range before certification"
        assert not point.get("boundary_samples") and point["source_refs"]
        batch = plan["coverage_review"]["batches"][0]
        assert batch["obligations"][0]["point_ids"] == []
        assert not batch["obligations"][0].get("boundary_contract")
        assert batch["clarifications"] == [
            "0≤t<120秒复合范围暂未结构核验；120与121秒覆盖仍需独立复核"]
        assert "coverage_unverified" in batch["warnings"]
        assert batch["completion_attempted"] is False
        with get_session_factory()() as db:
            after = [set(db.scalars(select(kind.id))) for kind in (TestCase, TestCaseRevision)]
            assert after == before


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_real_nl_probe_protocol_and_no_formal_write(monkeypatch, tmp_path, capsys, empty):
    from sqlalchemy import func, select

    from casepilot_api.database import get_session_factory
    from casepilot_api.main import app
    from casepilot_api.models import GenerationJob, TestCase, TestCaseRevision

    with get_session_factory()() as db:
        before = [db.scalar(select(func.count()).select_from(model))
                  for model in (TestCase, TestCaseRevision, GenerationJob)]

    model = DomainProvider(empty)
    monkeypatch.setattr(tasks, "create_provider", lambda *a, **kw: model)
    monkeypatch.setattr(tasks.settings, "provider", "mock")
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    monkeypatch.setattr(tasks.celery_app, "send_task",
                        lambda *a, **kw: pytest.fail("unexpected external worker dispatch"))
    control = activate(monkeypatch, [("prepare_generation", {})])
    report = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if empty:
            with pytest.raises(probe.ProbeFailure) as caught:
                await probe.protocol(client, report, "a" * 40)
            assert caught.value.code == "sampling_probe_samples_missing"
            assert not report.get("protocol_passed")
        else:
            artifact = await probe.protocol(client, report, "a" * 40)
            path = probe.write_artifact(tmp_path / "nl-only.json", artifact)
            restored = probe.SamplingArtifact.model_validate_json(path.read_text())
            assert restored == artifact
            assert report["protocol_passed"] and report["worker_count"] == 1
            assert report["sample_count"] == 3
            assert artifact.original_prompt_fixture_sha256 == probe.PROMPT_SHA256
            assert all(sample.assertion_source_ref.excerpt == probe.PROMPT
                       for point in artifact.test_points for sample in point.boundary_samples or [])
    with get_session_factory()() as db:
        after = [db.scalar(select(func.count()).select_from(model))
                 for model in (TestCase, TestCaseRevision, GenerationJob)]
        assert after == [before[0], before[1], before[2] + 1]
    assert model.contexts and control.observations
    for line in capsys.readouterr().out.splitlines():
        if line.startswith("{"):
            event = json.loads(line)
            assert "test_points" not in event and "raw_response" not in event
            assert probe.PROMPT not in line
