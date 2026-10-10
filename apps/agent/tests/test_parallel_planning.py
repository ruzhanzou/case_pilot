from copy import deepcopy
from threading import Barrier, Event

import pytest

from casepilot_agent.contracts import FeaturePlan, RequirementAnalysis
from casepilot_agent.contracts import TestPointPlan as PointPlan
from casepilot_agent.planning import build_planning


def features(count):
    return FeaturePlan.model_validate(
        {
            "feature_points": [
                {
                    "id": f"f{i}",
                    "name": f"功能{i}",
                    "module": "登录",
                    "description": f"规则{i}",
                    "requirement_refs": [f"R{i}"],
                    "source_refs": [{"label": f"来源{i}"}],
                }
                for i in range(count)
            ]
        }
    )


def points(payload, fill_budget=False):
    group = payload["feature_points"]["feature_points"]
    count = payload["batch_count"] if fill_budget else len(group)
    return PointPlan.model_validate(
        {
            "test_points": [
                {
                    "id": "reused",
                    "title": f"{group[i % len(group)]['name']}-场景{i}",
                    "scenario": f"场景{i}",
                    "objective": "验证规则",
                    "category": "功能",
                    "priority": "P1",
                    "priority_reason": "用户规则",
                    "feature_point_ids": [group[i % len(group)]["id"]],
                }
                for i in range(count)
            ]
        }
    )


def test_parallel_out_of_order_batches_publish_stable_ids_and_exact_total_budget():
    first_wave = Barrier(3, timeout=5)
    second_published = Event()
    snapshots, quotas = [], []

    def complete(stage, instruction, payload, result_type):
        if stage == "feature.generated":
            return features(15)
        assert "feature_outline" not in payload  # Other batch IDs caused real model scope leakage.
        index = payload["batch_index"]
        quotas.append(payload["batch_count"])
        if index <= 3:
            first_wave.wait()  # Fails if requests are secretly serialized.
        if index == 1:
            assert second_published.wait(5)
        return points(payload, fill_budget=True)

    def publish(plan, metadata):
        snapshots.append((deepcopy(plan), deepcopy(metadata)))
        if any(p["title"].startswith("功能3-") for p in plan["test_points"]):
            second_published.set()

    result = build_planning(
        RequirementAnalysis(summary="50条用例"), {}, complete, target_count=50, on_progress=publish
    )
    assert sum(quotas) == 50
    assert len(result["test_points"]) == 50
    assert max(len(meta["active_batches"]) for _, meta in snapshots) == 3
    counts = [meta["completed_batches"] for _, meta in snapshots]
    assert counts == sorted(counts)
    assert snapshots[-1][1]["completed_batches"] == 5
    previous = {}
    for snapshot, _ in snapshots:
        current = {p["id"]: p for p in snapshot["test_points"]}
        assert previous.items() <= current.items()
        previous = current
    assert previous == {p["id"]: p for p in result["test_points"]}
    assert all(p["source_refs"] for p in result["test_points"])


def test_failure_does_not_publish_invalid_batch_or_drop_completed_snapshot():
    published = Event()
    snapshots = []

    def complete(stage, instruction, payload, result_type):
        if stage == "feature.generated":
            return features(6)
        if payload["batch_index"] == 2:
            assert published.wait(5)
            result = points(payload)
            result.test_points[0].feature_point_ids = ["foreign-feature"]
            return result
        return points(payload)

    def publish(plan, metadata):
        snapshots.append(deepcopy(plan))
        if plan["test_points"]:
            published.set()

    with pytest.raises(ValueError, match="planning_feature_reference_invalid"):
        build_planning(RequirementAnalysis(summary="登录"), {}, complete, on_progress=publish)
    assert len(snapshots[-1]["test_points"]) == 3
    assert all(
        "foreign-feature" not in p["feature_point_ids"] for p in snapshots[-1]["test_points"]
    )


def test_cancellation_stops_dispatch_after_first_wave():
    barrier = Barrier(3, timeout=5)
    cancelled = Event()
    started = []

    def check():
        if cancelled.is_set():
            raise RuntimeError("cancelled")

    def complete(stage, instruction, payload, result_type):
        if stage == "feature.generated":
            return features(15)
        started.append(payload["batch_index"])
        barrier.wait()
        return points(payload)

    def publish(plan, metadata):
        if metadata["completed_batches"]:
            cancelled.set()

    with pytest.raises(RuntimeError, match="cancelled"):
        build_planning(
            RequirementAnalysis(summary="登录"),
            {},
            complete,
            check_cancelled=check,
            on_progress=publish,
        )
    assert set(started) == {1, 2, 3}


def test_missing_feature_is_rejected_instead_of_reported_complete():
    def complete(stage, instruction, payload, result_type):
        if stage == "feature.generated":
            return features(3)
        result = points(payload)
        result.test_points.pop()
        return result

    with pytest.raises(ValueError, match="planning_feature_uncovered"):
        build_planning(RequirementAnalysis(summary="登录"), {}, complete)
