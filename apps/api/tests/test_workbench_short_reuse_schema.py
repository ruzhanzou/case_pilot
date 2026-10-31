"""Actual ASGI approvals and both workers for the short schema probe; no live calls."""
import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from test_workbench_reuse_journey import MixedReuseProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/qa"))
import workbench_agent_short_reuse_schema as probe


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_compare", [False, True, "pending"])
async def test_short_probe_real_approval_worker_protocol(monkeypatch, capsys, fail_compare):
    from casepilot_agent import tasks
    from workbench_agent_live_journey import JourneyFailure

    from casepilot_api import conversations
    from casepilot_api.main import app

    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **kw: None)
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    monkeypatch.setattr(tasks.celery_app, "send_task",
                        lambda *a, **kw: pytest.fail("unexpected external dispatch"))

    class ObservedProvider:
        stages = []

        def complete(self, *, stage, payload, result_type, **kwargs):
            self.stages.append(stage)
            if fail_compare == "pending" and not hasattr(self, "original_assets"):
                from sqlalchemy import select

                from casepilot_api.database import get_session_factory
                from casepilot_api.models import TestCase, TestCaseRevision
                with get_session_factory()() as db:
                    self.original_assets = set(db.scalars(select(TestCase.id)))
                    self.original_revisions = set(db.scalars(select(TestCaseRevision.id)))
            if fail_compare is True and stage == "reuse.compared":
                raise ValueError("required_reuse_coverage_missing_replan_required")
            catalog = payload.get("approved_source_catalog") or payload.get("sources") or []
            if catalog:
                self.key = catalog[0]["key"]
            result, usage = MixedReuseProvider(getattr(self, "key", "")).complete(
                stage=stage, payload=payload, result_type=result_type, **kwargs)
            if fail_compare == "pending" and stage == "output_quantity.interpreted":
                result = result_type.model_validate({**result.model_dump(), "test_point_count": 1})
            return result, usage

    model = ObservedProvider()
    report = {"checks": [], "workspace_ids": [], "live_nl_chain": False}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if fail_compare == "pending":
            with pytest.raises(JourneyFailure) as caught:
                await probe.protocol(client, report, second_provider=model)
            assert caught.value.args == ("short_reuse_pending_clarification",)
            events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
                      if line.startswith("{")]
            pending = next(item for item in events
                           if item.get("event") == "pending_reserved_clarification")
            assert pending == {"event": "pending_reserved_clarification",
                "reason": "reserved_reuse_point_budget_requires_clarification",
                "required_source_count": 1, "reserved_source_count": 1,
                "fixture_requested_total_points": 2, "interpreted_test_point_count": 1,
                "generated_point_count": 0, "quantity": {
                    "case_count": 2, "test_point_count": 1, "output_case_count": 2,
                    "new_case_count": 1}}
            failure = next(item for item in events if item.get("event") == "domain_failure")
            assert failure["failure"]["code"] == "short_reuse_pending_clarification"
            assert failure["job"]["status"] == "completed"
            assert failure["job"]["feature_points_count"] == 0
            assert failure["job"]["test_points_count"] == 0
            assert report["last_stage"] == "second_draft_pending_clarification"
            assert len(report["checks"]) == 1  # Only setup passed, never the worker goal.
            assert "test_point.generated" not in model.stages
            from sqlalchemy import select

            from casepilot_api.database import get_session_factory
            from casepilot_api.models import TestCase, TestCaseRevision
            with get_session_factory()() as db:
                assert set(db.scalars(select(TestCase.id))) == model.original_assets
                assert set(db.scalars(select(TestCaseRevision.id))) == model.original_revisions
            return
        if fail_compare:
            with pytest.raises(ValueError, match="required_reuse_coverage_missing_replan_required"):
                await probe.protocol(client, report, second_provider=model)
            events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
                      if line.startswith("{")]
            failure = next(item for item in events if item.get("event") == "domain_failure")
            assert failure["failure"]["code"] == "required_reuse_coverage_missing_replan_required"
            assert failure["job"]["lookup"] == "ok"
            assert failure["job"]["status"] == "failed"
            assert failure["job"]["error_class"] == "ValueError"
            assert type(failure["job"]["persisted_stage_count"]) is int
            assert set(failure["job"]) <= {
                "lookup", "status", "error_class", "persisted_stage_count",
                "feature_points_count", "test_points_count"}
            return
        job_id = await probe.protocol(client, report, second_provider=model)
    assert job_id
    assert report["last_stage"] == "second_draft_worker_completed"
    assert len(report["checks"]) == 2
    assert report["live_nl_chain"] is False
    assert {"output_quantity.interpreted", "test_point.generated", "reuse.compared"} <= set(
        model.stages)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_identity", [False, True])
async def test_short_probe_through_real_generation_and_exact_adoption(
    monkeypatch, capsys, invalid_identity
):
    from casepilot_agent import tasks

    from casepilot_api import conversations
    from casepilot_api.main import app

    monkeypatch.setattr(conversations, "enqueue_task", lambda *a, **kw: None)
    monkeypatch.setattr(tasks.settings, "embedding_provider", "mock")
    monkeypatch.setattr(tasks.celery_app, "send_task",
                        lambda *a, **kw: pytest.fail("unexpected external dispatch"))

    class ThroughProvider:
        name = "mock"

        def __init__(self):
            self.stages = []
            self.key = ""

        def complete(self, *, stage, payload, result_type, **kwargs):
            self.stages.append(stage)
            catalog = payload.get("approved_source_catalog") or payload.get("sources") or []
            if catalog:
                self.key = catalog[0]["key"]
            base_type = getattr(result_type, "__planning_source_base__", result_type)
            result, usage = MixedReuseProvider(self.key).complete(
                stage=stage, payload=payload, result_type=base_type, **kwargs)
            if base_type is not result_type:
                data = result.model_dump(mode="json")
                assert payload["source_catalog"]
                for feature in data["feature_points"]:
                    feature["source_refs"] = [{"locator": payload["source_catalog"][0]["slot"],
                        "label": "MODEL UNTRUSTED LABEL", "excerpt": "MODEL UNTRUSTED EVIDENCE"}]
                if invalid_identity:
                    data["feature_points"][0]["source_refs"][0]["chunk_id"] = "unknown-chunk"
                result = result_type.model_validate(data)
            return result, usage

    provider = ThroughProvider()
    report = {"checks": [], "workspace_ids": [], "live_nl_chain": False}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if invalid_identity:
            from pydantic import ValidationError
            with pytest.raises(ValidationError) as caught:
                await probe.protocol(client, report, second_provider=provider,
                                     through_generation=True)
            assert caught.value.errors(include_input=False)[0]["type"] == "none_required"
            assert not any(stage == "test_case.generated" for stage in provider.stages)
            events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
                      if line.startswith("{")]
            failure = next(item for item in events if item.get("event") == "domain_failure")
            assert failure["job"]["status"] == "failed"
            assert len(report["checks"]) == 1
            return
        job_id = await probe.protocol(client, report, second_provider=provider,
                                      through_generation=True)
    assert job_id
    assert report["last_stage"] == "generation_and_exact_adoption_completed"
    assert len(report["checks"]) == 3
    assert "test_point.generated" in provider.stages
    assert any(stage == "test_case.generated" for stage in provider.stages), provider.stages

    from uuid import UUID

    from casepilot_api.database import get_session_factory
    from casepilot_api.models import GenerationJob
    with get_session_factory()() as db:
        job = db.get(GenerationJob, UUID(job_id))
        assert "MODEL UNTRUSTED" not in json.dumps(job.input_payload["confirmed_plan"])
        assert "MODEL UNTRUSTED" not in json.dumps(job.output_payload)
        refs = [ref for point in job.input_payload["confirmed_plan"]["test_points"]
                for ref in point.get("source_refs", [])]
        assert refs and all(ref.get("label") for ref in refs)
