"""Persistable planning, independent of executable test case generation."""

import asyncio
import json
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from time import sleep
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from openai import APIConnectionError, InternalServerError, RateLimitError
from pydantic import Field, create_model, model_validator

from casepilot_agent.contracts import (
    CASE_DESIGN_INSTRUCTION,
    FeaturePlan,
    RequirementAnalysis,
    SourceRef,
    TestPoint,
    TestPointPlan,
)


def evidence_batches(context: dict[str, Any], budget: int = 18000) -> list[dict[str, Any]]:
    """Visit every excerpt, including unusually large blocks, without truncation."""
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for item in context.get("evidence", []):
        text = str(item.get("excerpt", ""))
        for start in range(0, max(1, len(text)), budget):
            piece = {**item, "excerpt": text[start : start + budget]}
            if current and size + len(piece["excerpt"]) > budget:
                batches.append({**context, "evidence": current})
                current, size = [], 0
            current.append(piece)
            size += len(piece["excerpt"])
    if current or not batches:
        batches.append({**context, "evidence": current})
    return batches


def analyze_batches(batches, complete, *, load, save, on_progress, check_cancelled,
                    concurrency=3):
    """Bound model calls; checkpoint each result before publishing progress."""
    completed, active = {}, {}
    pending = []
    for index, batch in enumerate(batches):
        check_cancelled()
        cached = load(index, batch)
        if cached is None:
            pending.append(index)
        else:
            completed[index] = cached

    last_progress = None

    def publish():
        nonlocal last_progress
        progress = (len(completed), len(batches), tuple(sorted(active.values())))
        if progress != last_progress:
            on_progress(*progress)
            last_progress = progress

    def worker(index):
        with asyncio.Runner() as runner:
            asyncio.set_event_loop(runner.get_loop())
            for attempt in range(2):
                check_cancelled()
                try:
                    return complete(index, batches[index])
                except (APIConnectionError, InternalServerError, RateLimitError):
                    # A transient request failure must not discard the whole
                    # large-document run. Retry this batch once, in the same slot.
                    if attempt:
                        raise
                    for _ in range(4):
                        check_cancelled()
                        sleep(0.5)

    publish()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="evidence") as pool:
        remaining = iter(pending)
        failure = None
        try:
            while True:
                while len(active) < concurrency and failure is None:
                    check_cancelled()
                    index = next(remaining, None)
                    if index is None:
                        break
                    active[pool.submit(worker, index)] = index
                publish()
                if not active:
                    if failure is not None:
                        raise failure
                    break
                done, _ = wait(active, timeout=0.5, return_when=FIRST_COMPLETED)
                check_cancelled()
                for future in sorted(done, key=lambda item: active[item]):
                    index = active.pop(future)
                    try:
                        result = future.result()
                    except Exception as error:
                        failure = failure or error
                        continue
                    check_cancelled()
                    save(index, batches[index], result)
                    completed[index] = result
                    publish()
        except BaseException:
            for future in active:
                future.cancel()
            raise
    return [completed[index] for index in range(len(batches))]


PLANNING_CONCURRENCY = 3
FEATURES_PER_BATCH = 3
POINTS_PER_BATCH = 12
MAX_CONSOLIDATED_EVIDENCE_CHARS = 180000


def build_planning(
    requirement: RequirementAnalysis,
    context: dict[str, Any],
    complete,
    analyses=None,
    *,
    target_count=None,
    on_progress=None,
    on_feature_progress=None,
    check_cancelled=lambda: None,
):
    """Plan disjoint feature groups concurrently; publish validated, stable snapshots."""
    features, points, groups = [], [], []
    batches = evidence_batches(context)
    def plan_features(index, batch):
        check_cancelled()
        local = analyses[index] if analyses else requirement
        common = {"requirement": local.model_dump(mode="json"), "context": batch}
        feature_plan = complete(
            "feature.generated",
            CASE_DESIGN_INSTRUCTION + "按本批资料规划全部相关功能，保留具体规则和来源。不生成用例。"
            "module 为业务模块路径，name 为功能名；不得为凑数量合并不同功能。"
            "当前只是完整资料的一个分片，其他模块由其他批次处理。"
            "仅为本批有明确证据的规则生成功能；不得为全局数量补位、生成占位功能或推测其他模块规则。"
            "同一规则的样例记录不是新功能，功能名使用资料中的规则名称，保留原始规则编号。",
            common,
            FeaturePlan,
        )
        for ordinal, feature in enumerate(feature_plan.feature_points):
            feature.id = f"FP-{index + 1}-{ordinal + 1}"
            feature.name = source_rule_name(feature, batch) or feature.name
            if not feature.source_refs:
                feature.source_refs = [
                    SourceRef.model_validate(item) for item in batch.get("evidence", [])
                ]
        check_cancelled()
        return common, feature_plan

    feature_results = analyze_batches(
        batches, plan_features, load=lambda *_: None, save=lambda *_: None,
        on_progress=on_feature_progress or (lambda *_: None),
        check_cancelled=check_cancelled, concurrency=PLANNING_CONCURRENCY,
    )
    # Completion order must not change IDs, budgets, or downstream batch membership.
    for common, feature_plan in feature_results:
        features.extend(feature_plan.feature_points)
        for start in range(0, len(feature_plan.feature_points), FEATURES_PER_BATCH):
            groups.append((common, feature_plan.feature_points[start : start + FEATURES_PER_BATCH]))

    if not features:
        raise ValueError("planning_has_no_features")

    features, groups = consolidate_feature_groups(features, groups, context)

    # The quantity is a planning budget, while every feature retains coverage.
    # Do not silently drop business features when the requested count is smaller.
    budget = max(target_count or len(features) * 3, len(features))
    quotas = [budget // len(features) + (i < budget % len(features)) for i in range(len(features))]
    feature_budget = dict(zip((f.id for f in features), quotas, strict=True))
    completed = {}
    active = {}

    def publish():
        ordered = [p for index in sorted(completed) for p in completed[index]]
        snapshot = merge_planning(features, ordered, context, len(batches))
        metadata = {
            "completed_batches": len(completed),
            "total_batches": len(groups),
            "completed_features": sum(len(groups[i][1]) for i in completed),
            "total_features": len(features),
            "test_point_count": len(snapshot["test_points"]),
            "target_count": target_count,
            "active_batches": [
                {"batch": i + 1, "features": [f.name for f in groups[i][1]]}
                for i in sorted(active.values())
            ],
        }
        if on_progress:
            on_progress(snapshot, metadata)

    def worker(index):
        # Runner.run_sync needs an event loop owned by this worker thread.
        with asyncio.Runner() as runner:
            asyncio.set_event_loop(runner.get_loop())
            check_cancelled()
            common, feature_slice = groups[index]
            count = min(POINTS_PER_BATCH, sum(feature_budget[f.id] for f in feature_slice))
            allowed_ref = Literal[tuple(f.id for f in feature_slice)]
            point_type = create_model(
                "BatchTestPoint", __base__=TestPoint, feature_point_ids=(list[allowed_ref], ...)
            )
            def validate_batch(plan):
                validate_point_batch(plan, {f.id for f in feature_slice}, count)
                return plan

            plan_type = create_model(
                "BatchTestPointPlan", __base__=TestPointPlan,
                test_points=(list[point_type], Field(min_length=1, max_length=count)),
                __validators__={"validate_batch": model_validator(mode="after")(validate_batch)},
            )
            plan = complete(
                "test_point.generated",
                CASE_DESIGN_INSTRUCTION + "只为本批给定功能规划测试点，不生成用例正文。"
                "每个功能至少覆盖一次，优先关键规则；跨功能场景归属本批功能时才生成，避免重复。"
                "title保留边界数值和例外。feature_point_ids是所属功能ID，不是测试点序号，"
                "必须逐字复用本批feature_points的id，多个测试点可以复用同一个功能ID，严禁递增或发明功能ID。"
                "本批数量预算为batch_count，最多生成该数量；不得在本批重复追求全局总数。"
                "coverage_matrix留空；source_refs留空，系统按功能关联原始来源。使用简洁字段，不重复原文。",
                {
                    **common,
                    "feature_points": {
                        "feature_points": [
                            f.model_dump(mode="json", exclude={"source_refs"})
                            for f in feature_slice
                        ]
                    },
                    "planning_feature_count": len(features),
                    "target_count": target_count,
                    "batch_count": count,
                    "batch_index": index + 1,
                },
                plan_type,
            )
            validate_point_batch(plan, {f.id for f in feature_slice}, count)
            for ordinal, point in enumerate(plan.test_points):
                point.id = f"TP-{index + 1}-{ordinal + 1}"
                # Hydrate citations from the actual referenced features.
                point.source_refs = list(
                    dict.fromkeys(
                        ref.model_dump_json()
                        for f in feature_slice
                        if f.id in point.feature_point_ids
                        for ref in f.source_refs
                    )
                )
                point.source_refs = [
                    SourceRef.model_validate_json(ref) for ref in point.source_refs
                ]
            check_cancelled()
            return plan.test_points

    publish()
    with ThreadPoolExecutor(
        max_workers=PLANNING_CONCURRENCY, thread_name_prefix="planning"
    ) as pool:
        pending = iter(range(len(groups)))
        try:
            while True:
                while len(active) < PLANNING_CONCURRENCY:
                    check_cancelled()
                    index = next(pending, None)
                    if index is None:
                        break
                    active[pool.submit(worker, index)] = index
                publish()
                if not active:
                    break
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda item: active[item]):
                    index = active.pop(future)
                    completed[index] = future.result()
                    check_cancelled()
                    publish()
        except BaseException:
            for future in active:
                future.cancel()
            raise
    points = [p for index in sorted(completed) for p in completed[index]]
    return merge_planning(features, points, context, len(batches))


def validate_point_batch(plan, feature_ids, count):
    if not plan.test_points or len(plan.test_points) > count:
        raise ValueError("planning_point_batch_size_invalid")
    covered = set()
    for point in plan.test_points:
        if not point.feature_point_ids or set(point.feature_point_ids) - feature_ids:
            raise ValueError("planning_feature_reference_invalid")
        covered.update(point.feature_point_ids)
    if covered != feature_ids:
        raise ValueError("planning_feature_uncovered")


def source_rule_name(feature, batch):
    """Canonicalize a single cited rule only against its original definition."""
    if len(feature.requirement_refs) != 1:
        return None
    reference = feature.requirement_refs[0].strip()
    if not reference or len(reference) > 80:
        return None
    # Providers sometimes invent a prefix in requirement_refs. A label in their
    # citation is usable only when the original batch confirms its definition.
    quoted = {
        match
        for ref in feature.source_refs
        for match in re.findall(r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9_.-]{0,79})\s*[:：]",
                                ref.excerpt or "")
    }
    candidates = [reference, *sorted(quoted - {reference})]
    names = set()
    for candidate in candidates:
        pattern = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(candidate)
                             + r"\s*[:：]\s*([^\n。；;]+)")
        definitions = {
            match.strip().rstrip("。.")
            for item in batch.get("evidence", [])
            for match in pattern.findall(str(item.get("excerpt", "")))
        }
        if len(definitions) != 1:
            continue
        definition = definitions.pop()
        if definition and len(definition) <= 160:
            names.add(f"{candidate} {definition}")
    return names.pop() if len(names) == 1 else None


def consolidate_feature_groups(features, groups, context):
    """Merge repeated named features before spending calls and quotas on points.

    Use the same exact module/name identity as final snapshots. Retain all rules
    and all contributing original evidence; no similarity-based deletion.
    """
    def key(feature):
        return feature.module, feature.name
    canonical = FeaturePlan.model_validate(merge_planning(features, [], {}, 0)).feature_points
    by_key = {key(feature): feature for feature in canonical}
    origins = {}
    for common, group in groups:
        for feature in group:
            origins.setdefault(key(feature), []).append(common)
    planned, consolidated = set(), []
    for common, group in groups:
        selected = []
        for feature in group:
            identity = key(feature)
            if identity not in planned:
                planned.add(identity)
                selected.append(by_key[identity])
        if not selected:
            continue
        contributing = [item for feature in selected for item in origins[key(feature)]]
        # For disjoint batches the original local context remains unchanged.
        if all(item is common for item in contributing):
            consolidated.append((common, selected))
            continue
        evidence, seen = [], set()
        local = dict(common["requirement"])
        for field in local:
            if isinstance(local[field], list):
                values = {}
                for item in contributing:
                    for value in item["requirement"].get(field, []):
                        values.setdefault(json.dumps(value, sort_keys=True), value)
                local[field] = list(values.values())
        for item in contributing:
            for source in item["context"].get("evidence", []):
                identity = json.dumps(source, sort_keys=True)
                if identity not in seen:
                    seen.add(identity)
                    evidence.append(source)
        # Never turn arbitrarily large documents into one unbounded model call.
        # Preserve the original bounded groups when consolidation exceeds budget.
        evidence_chars = sum(len(str(item.get("excerpt", ""))) for item in evidence)
        if evidence_chars > MAX_CONSOLIDATED_EVIDENCE_CHARS:
            return features, groups
        consolidated.append(({"requirement": local,
                              "context": {**context, "evidence": evidence}}, selected))
    return canonical, consolidated


def merge_planning(features, points, context, processed_batches):
    # Snapshot normalization must not mutate worker inputs or previous snapshots.
    features = [f.model_copy(deep=True) for f in features]
    points = [p.model_copy(deep=True) for p in points]
    # Adjacent evidence batches may describe the same business branch.
    # Merge exact semantic keys, retaining every source and rule description.
    merged_features, feature_map = {}, {}
    for feature in features:
        key = f"{feature.module}/{feature.name}"
        stable_id = f"FP-{uuid5(NAMESPACE_URL, key).hex[:16]}"
        feature_map[feature.id] = stable_id
        feature.id = stable_id
        if stable_id in merged_features:
            current = merged_features[stable_id]
            if feature.description not in current.description:
                current.description += "\n" + feature.description
            current.source_refs.extend(
                ref for ref in feature.source_refs if ref not in current.source_refs
            )
            current.requirement_refs = list(
                dict.fromkeys(current.requirement_refs + feature.requirement_refs)
            )
        else:
            merged_features[stable_id] = feature
    merged_points = {}
    for point in points:
        point.feature_point_ids = list(
            dict.fromkeys(feature_map[ref] for ref in point.feature_point_ids)
        )
        key = "/".join(sorted(point.feature_point_ids) + [point.scenario, point.title])
        point.id = f"TP-{uuid5(NAMESPACE_URL, key).hex[:16]}"
        if point.id in merged_points:
            current = merged_points[point.id]
            current.source_refs.extend(
                ref for ref in point.source_refs if ref not in current.source_refs
            )
            if point.objective not in current.objective:
                current.objective += "\n" + point.objective
        else:
            merged_points[point.id] = point
    return {
        "feature_points": [item.model_dump(mode="json") for item in merged_features.values()],
        "test_points": [item.model_dump(mode="json") for item in merged_points.values()],
        "coverage_matrix": [],
        "evidence": context.get("evidence", []),
        "processed_batches": processed_batches,
        "warnings": context.get("warnings", []),
    }


def planned_module(point, features) -> str:
    feature = next(item for item in features if item.id in point.feature_point_ids)
    parts = [part.strip() for part in feature.module.split("/") if part.strip()]
    for part in (feature.name,):
        part = part.strip().replace("/", "／")
        if part and (not parts or parts[-1] != part):
            parts.append(part)
    return "/".join(parts)


def rewrite_evidence(context, snapshot, complete):
    """Read every document batch, extracting only rules affecting the selected case."""
    if not context.get("evidence"):
        return {}
    batches = evidence_batches(context)
    if len(batches) == 1:
        return batches[0]
    rules = []
    sources = []
    for batch in batches:
        analysis = complete(
            "requirement.analyzed",
            "完整检查本批资料对指定用例的影响，仅提取相关规则到business_rules。"
            "保留数值、单位、例外和冲突；不相关则返回空列表。不修改用例、不扩大目标范围。",
            {"test_case": snapshot, "context": batch},
            RequirementAnalysis,
        )
        if analysis.business_rules:
            rules.extend(analysis.business_rules)
            sources.extend(
                {
                    key: item.get(key)
                    for key in ("source_id", "document_id", "chunk_id", "label", "locator")
                }
                for item in batch["evidence"]
            )
    return {
        "business_rules": list(dict.fromkeys(rules)),
        "sources": sources,
        "processed_batches": len(batches),
        "warnings": context.get("warnings", []),
    }
