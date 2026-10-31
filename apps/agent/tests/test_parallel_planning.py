from copy import deepcopy
from threading import Barrier, Event, Lock

import pytest

from casepilot_agent.contracts import FeaturePlan, RequirementAnalysis
from casepilot_agent.contracts import TestPoint as BasePoint
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
                    "source_refs": [{"label": f"来源{i}", "locator": "source:0"}],
                }
                for i in range(count)
            ]
        }
    )


class FixturePoint(BasePoint):
    primary_feature_id: str
    primary_binding: str | None = None


class FixturePointPlan(PointPlan):
    test_points: list[FixturePoint]


def points(payload, fill_budget=False):
    group = payload["feature_points"]["feature_points"]
    count = payload["batch_count"] if fill_budget else len(group)
    return FixturePointPlan.model_validate(
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
                    "primary_feature_id": group[i % len(group)]["id"],
                    "primary_binding": next(
                        (
                            binding["id"]
                            for binding in payload.get("primary_bindings", [])
                            if binding["feature_id"] == group[i % len(group)]["id"]
                        ),
                        None,
                    ),
                    "source_refs": [
                        {"label": "selection", "locator": slot}
                        for slot in payload.get("feature_source_slots", {}).get(
                            group[i % len(group)]["id"], ["source:0"]
                        )
                    ],
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
        RequirementAnalysis(summary="50条用例"),
        {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
        complete, target_count=50, on_progress=publish
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
        build_planning(
            RequirementAnalysis(summary="登录"),
            {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
            complete, on_progress=publish,
        )
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
            {"user_input": "合成登录需求：验证取消时不再派发规划。"},
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
        build_planning(
            RequirementAnalysis(summary="登录"),
            {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
            complete,
        )


def test_test_point_planning_retries_transient_connection_loss(monkeypatch):
    import httpx
    from openai import APIConnectionError

    from casepilot_agent import planning

    monkeypatch.setattr(planning, "sleep", lambda _: None)
    calls = 0

    def complete(stage, instruction, payload, result_type):
        nonlocal calls
        if stage == "feature.generated":
            return features(3)
        calls += 1
        if calls == 1:
            raise APIConnectionError(request=httpx.Request("POST", "https://example.test"))
        return points(payload)

    result = build_planning(
        RequirementAnalysis(summary="登录"),
        {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
        complete,
    )
    assert calls == 2
    assert len(result["test_points"]) == 3


def test_large_document_features_are_bounded_parallel_and_keep_source_order():
    barrier, release, lock = Barrier(3, timeout=5), Event(), Lock()
    active = peak = 0
    progress, point_batches = [], []
    evidence = [{"label": str(i), "excerpt": str(i % 10) * 18000} for i in range(32)]
    analyses = [RequirementAnalysis(summary=f"需求{i}") for i in range(32)]

    def complete(stage, instruction, payload, result_type):
        nonlocal active, peak
        if stage != "feature.generated":
            point_batches.append((payload["batch_index"], payload["requirement"]["summary"]))
            return points(payload)
        index = int(payload["context"]["evidence"][0]["label"])
        assert payload["requirement"]["summary"] == f"需求{index}"
        with lock:
            active += 1
            peak = max(peak, active)
        if index < 3:
            barrier.wait()
        if index == 0:
            assert release.wait(5)
        result = features(1)
        result.feature_points[0].name = f"功能{index}"
        result.feature_points[0].source_refs = []
        with lock:
            active -= 1
        return result

    def publish(done, total, active_batches):
        assert total == 32
        assert len(active_batches) <= 3
        progress.append(done)
        if done:
            release.set()

    result = build_planning(
        RequirementAnalysis(summary="全部需求"), {"evidence": evidence}, complete,
        analyses, on_feature_progress=publish,
    )
    assert peak == 3
    assert progress == sorted(progress)
    assert progress[-1] == 32
    assert sorted(point_batches) == [(i + 1, f"需求{i}") for i in range(32)]
    assert [f["name"] for f in result["feature_points"]] == [f"功能{i}" for i in range(32)]
    assert [f["source_refs"][0]["label"] for f in result["feature_points"]] == [
        str(i) for i in range(32)
    ]
    assert len(result["test_points"]) == 32


def test_repeated_features_share_point_budget_without_dropping_rules_or_evidence():
    point_inputs = []
    evidence = [{"label": str(i), "excerpt": str(i) * 18000} for i in range(3)]
    analyses = [RequirementAnalysis(summary="登录", business_rules=[f"边界{i}"])
                for i in range(3)]

    def complete(stage, instruction, payload, result_type):
        if stage == "feature.generated":
            result = features(1)
            index = payload["context"]["evidence"][0]["label"]
            result.feature_points[0].description = f"边界{index}"
            result.feature_points[0].source_refs = []
            return result
        point_inputs.append(payload)
        return points(payload, fill_budget=True)

    result = build_planning(analyses[0], {"evidence": evidence}, complete, analyses,
                            target_count=3)
    assert len(point_inputs) == 1
    assert point_inputs[0]["batch_count"] == 3
    assert point_inputs[0]["context"]["evidence"] == evidence
    assert point_inputs[0]["requirement"]["business_rules"] == [f"边界{i}" for i in range(3)]
    assert len(result["feature_points"]) == 1
    assert result["feature_points"][0]["description"] == "边界0\n边界1\n边界2"
    assert len(result["feature_points"][0]["source_refs"]) == 3
    assert len(result["test_points"]) == 3
    assert result["evidence"] == evidence


def test_consolidation_preserves_bounded_groups_when_combined_evidence_is_too_large(monkeypatch):
    from casepilot_agent import planning

    monkeypatch.setattr(planning, 'MAX_CONSOLIDATED_EVIDENCE_CHARS', 18000)
    original, groups = [], []
    for index in range(2):
        feature = features(1).feature_points[0]
        feature.id = f'FP-{index}'
        original.append(feature)
        common = {'requirement': RequirementAnalysis(summary='登录').model_dump(),
                  'context': {'evidence': [{'label': str(index), 'excerpt': 'x' * 18000}]}}
        groups.append((common, [feature]))
    merged, bounded = planning.consolidate_feature_groups(original, groups, {})
    assert merged is original
    assert bounded is groups


def test_only_verified_unambiguous_rule_labels_normalize_feature_names():
    from casepilot_agent.planning import source_rule_name

    feature = features(1).feature_points[0]
    feature.requirement_refs = ['RULE-1']
    batch = {'evidence': [{'excerpt': 'RULE-1: 连续5次错误锁定15分钟。\nRULE-10: 其他规则。'}]}
    assert source_rule_name(feature, batch) == 'RULE-1 连续5次错误锁定15分钟'
    assert source_rule_name(feature, {'evidence': [{'excerpt': 'RULE-10: 其他规则。'}]}) is None
    assert source_rule_name(feature, {'evidence': [
        {'excerpt': '样例记录，适用规则RULE-1：连续5次错误锁定15分钟。此为样例。'}
    ]}) == 'RULE-1 连续5次错误锁定15分钟'
    batch['evidence'].append({'excerpt': 'RULE-1: 连续3次错误锁定10分钟。'})
    assert source_rule_name(feature, batch) is None  # Conflicting definitions must survive.
    feature.requirement_refs = ['RULE-1', 'RULE-2']
    assert source_rule_name(feature, batch) is None


def test_explicit_point_quantity_rejects_short_batches():
    def complete(stage, instruction, payload, result_type):
        if stage == 'feature.generated': return features(2)
        return points(payload)  # Only two, although user explicitly requested four.
    with pytest.raises(ValueError, match='planning_point_batch_size_invalid'):
        build_planning(
            RequirementAnalysis(summary='四个测试点'),
            {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
            complete, target_count=4,
        )


def test_one_point_can_cover_multiple_features_without_inflating_quantity():
    def complete(stage, instruction, payload, result_type):
        if stage == 'feature.generated': return features(6)
        assert payload['batch_count'] == 1
        result = points(payload, fill_budget=True)
        result.test_points[0].feature_point_ids = [f['id'] for f in payload['feature_points']['feature_points']]
        return result
    result = build_planning(
        RequirementAnalysis(summary='只要一个测试点'),
        {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
        complete, target_count=1,
    )
    assert len(result['test_points']) == 1
    assert set(result['test_points'][0]['feature_point_ids']) == {f['id'] for f in result['feature_points']}


def test_final_deduplication_cannot_silently_shrink_explicit_quantity():
    def complete(stage, instruction, payload, result_type):
        if stage == 'feature.generated': return features(1)
        result = points(payload, fill_budget=True)
        result.test_points[1] = result.test_points[0].model_copy(deep=True)
        return result
    with pytest.raises(ValueError, match='planning_duplicate_test_point'):
        build_planning(
            RequirementAnalysis(summary='两个不同测试点'),
            {"user_input": "合成登录需求：验证规则和所请求的测试点数量。"},
            complete, target_count=2,
        )
