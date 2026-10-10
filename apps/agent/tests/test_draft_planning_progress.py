from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from uuid import uuid4

import pytest
from test_parallel_planning import features, points

from casepilot_agent import tasks
from casepilot_agent.contracts import RequirementAnalysis, UsageMetadata


class Store:
    def __init__(self):
        self.lock = RLock()
        self.job = {
            "id": uuid4(),
            "status": "queued",
            "input_payload": {
                "prompt": "为登录生成12条测试用例",
                "model_id": "auto",
                "conversation_id": str(uuid4()),
            },
        }
        self.events = []
        self.briefs = []
        self.stages = []

    @contextmanager
    def connection(self):
        with self.lock:
            yield self

    def claim_job(self, connection, job_id, **kwargs):
        self.job["status"] = "running"
        return self.job

    def get_job_for_update(self, connection, job_id):
        return self.job

    def is_cancelled(self, connection, job_id):
        return self.job["status"] == "cancelled"

    def update_job(self, connection, job_id, **values):
        self.job.update(deepcopy(values))

    def load_completed_stage(self, connection, job_id, stage, input_payload):
        return next((s for s in self.stages if s["stage"] == stage
                     and s["input_payload"] == input_payload), None)

    def record_stage(self, connection, **values):
        self.stages.append(deepcopy({"latency_ms": 0, "token_usage": {}, **values}))

    def publish(self, job_id, event):
        self.events.append(deepcopy(event))
        if "planning_preview" in event:
            assert self.job["output_payload"]["planning_preview"] == event["planning_preview"]

    def persist_test_brief(self, connection, job, content):
        assert self.job["output_payload"]["planning_progress"]["completed_batches"] == 2
        self.briefs.append(deepcopy(content))
        return 1

    def complete_job_message(self, *args, **kwargs):
        pass

    def fail_job_message(self, *args, **kwargs):
        pass


@pytest.mark.parametrize("fail", [False, True])
def test_draft_persists_before_streaming_and_only_finalizes_complete_plan(monkeypatch, fail):
    store = Store()

    class Provider:
        def complete(self, *, stage, payload, **kwargs):
            if stage == "requirement.analyzed":
                result = RequirementAnalysis(
                    summary="为登录生成12条测试用例", test_object="登录", test_object_specified=True
                )
            elif stage == "feature.generated":
                result = features(6)
            else:
                if fail and payload["batch_index"] == 2:
                    raise ValueError("provider_failure")
                result = points(payload, fill_budget=True)
            return result, UsageMetadata(model="mock")

    monkeypatch.setattr(tasks, "JobStore", lambda *args: store)
    monkeypatch.setattr(tasks, "create_provider", lambda *args: Provider())
    monkeypatch.setattr(tasks, "create_embedding_provider", lambda: None)
    monkeypatch.setattr(tasks, "_context_payload", lambda *args, **kwargs: {"evidence": []})
    if fail:
        with pytest.raises(ValueError, match="provider_failure"):
            tasks.draft_test_brief(str(store.job["id"]))
        assert store.job["status"] == "failed"
        assert store.briefs == []
        assert "planning_preview" in store.job["output_payload"]
        checkpoint = [s for s in store.stages if s["stage"] == "requirement.batch.1"]
        assert len(checkpoint) == 1
        fail = False
        tasks.draft_test_brief(str(store.job["id"]))
        assert store.job["status"] == "completed"
        assert len([s for s in store.stages if s["stage"] == "requirement.batch.1"]) == 1
    else:
        tasks.draft_test_brief(str(store.job["id"]))
        assert store.job["status"] == "completed"
        assert len(store.briefs) == 1
        assert len(store.briefs[0]["planning"]["test_points"]) == 12
        assert store.events[-1]["event"] == "brief.completed"
        previews = [
            e for e in store.events if e.get("planning_progress", {}).get("completed_batches")
        ]
        assert previews
        assert previews[-1]["planning_progress"]["progress"] == 95
