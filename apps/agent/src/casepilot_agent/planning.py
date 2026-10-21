"""Persistable planning, independent of executable test case generation."""

import asyncio
import json
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from time import sleep
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from openai import APIConnectionError, InternalServerError, RateLimitError
from pydantic import Field, create_model, model_validator

from casepilot_agent.contracts import (
    CASE_DESIGN_INSTRUCTION,
    TEST_POINT_DESIGN_INSTRUCTION,
    FeaturePlan,
    FeaturePoint,
    RequirementAnalysis,
    SourceRef,
    TestPoint,
    TestPointPlan,
)
from casepilot_agent.reuse import ReuseAnalysis


def evidence_batches(context: dict[str, Any], budget: int = 18000) -> list[dict[str, Any]]:
    """Visit every excerpt, including unusually large blocks, without truncation."""
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for item in context.get("evidence", []):
        item = {k: v for k, v in item.items() if k not in {"reference_cases", "sheet", "case_import_rows"}}
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



class PlanningAnalysis(ReuseAnalysis):
    """Extract requirements and their features in one pass over large documents."""

    feature_points: list[FeaturePoint] = Field(default_factory=list)
    planning_update_mode: Literal["merge", "replace"] = "merge"
    superseded_feature_ids: list[str] = Field(default_factory=list)
    superseded_test_point_ids: list[str] = Field(default_factory=list)


def requested_point_count(prompt: str) -> int | None:
    match = re.search(
        r"(?:生成|编写|设计|创建|新增|增加|补充|替换为|修改为|恰好)[^。；;\n]{0,24}?"
        r"(?<!\d)([1-9]\d{0,3})\s*(?:个|条)\s*[^，。；;\n\d]{0,12}?测试点",
        prompt,
    )
    if not match:
        return None
    count = int(match.group(1))
    if count > 500:
        raise ValueError("单次规划最多支持500个测试点，请缩小范围后重试")
    return count


def reconcile_planning(previous, incoming, analyses):
    """Apply an explicit revision; omission in an incremental response is not deletion."""
    if not previous or any(item.planning_update_mode == "replace" for item in analyses):
        return deepcopy(incoming)
    removed_features = {ref for item in analyses for ref in item.superseded_feature_ids}
    removed_points = {ref for item in analyses for ref in item.superseded_test_point_ids}
    known_features = {item["id"] for item in previous.get("feature_points", [])}
    known_points = {item["id"] for item in previous.get("test_points", [])}
    if not removed_features <= known_features or not removed_points <= known_points:
        raise ValueError("Planning revision references unknown prior IDs")
    result = deepcopy(incoming)
    features = {item["id"]: deepcopy(item) for item in previous.get("feature_points", [])
                if item["id"] not in removed_features}
    features.update({item["id"]: deepcopy(item) for item in incoming.get("feature_points", [])})
    points = {}
    for item in previous.get("test_points", []):
        if item["id"] in removed_points:
            continue
        refs = [ref for ref in item.get("feature_point_ids", []) if ref not in removed_features]
        if not refs:
            continue
        points[item["id"]] = {**deepcopy(item), "feature_point_ids": refs}
    points.update({item["id"]: deepcopy(item) for item in incoming.get("test_points", [])})
    if any(
        ref not in features
        for point in points.values()
        for ref in point.get("feature_point_ids", [])
    ):
        raise ValueError("Planning revision has dangling feature references")
    result["feature_points"] = list(features.values())
    result["test_points"] = list(points.values())
    for field in ("evidence", "warnings"):
        result[field] = deepcopy(previous.get(field, []))
        for item in incoming.get(field, []):
            if item not in result[field]:
                result[field].append(deepcopy(item))
    # Coverage is derived from the current plan; never retain stale matrix rows.
    result["coverage_matrix"] = []
    return result


def compact_planning_context(common, features):
    """Use verified quotations plus extracted rules, falling back on missing citations.

    Original evidence stays in the persisted plan. Never trust a model's source
    identifiers or substitute an unverified quotation for the source text.
    """
    evidence = common["context"].get("evidence", [])
    selected = []
    for feature in features:
        matched = []
        for ref in feature.source_refs:
            # Providers occasionally normalize terminal punctuation. Match the
            # remaining text literally; the returned excerpt is always original.
            quote = ref.excerpt.strip().rstrip("。.；;")
            if len(quote) < 4:
                return common
            ref_matched = False
            for source in evidence:
                if (not (ref.document_id or ref.chunk_id or ref.source_id)
                        and ref.label != source.get("label")):
                    continue
                if any(getattr(ref, key) and getattr(ref, key) != source.get(key)
                       for key in ("source_id", "document_id", "chunk_id")):
                    continue
                text = str(source.get("excerpt", ""))
                # ASCII/full-width colons occupy one character, so offsets still
                # refer to the original text and no rule content is rewritten.
                start = text.replace("：", ":").find(quote.replace("：", ":"))
                if start < 0:
                    continue
                # Keep nearby exceptions/qualifications, not just the cited sentence.
                excerpt = text[max(0, start - 240):start + len(quote) + 240]
                matched.append({**source, "excerpt": excerpt})
                ref_matched = True
            if not ref_matched:
                return common
        if not matched:
            return common
        selected.extend(matched)
    unique = {json.dumps(item, sort_keys=True): item for item in selected}
    if not unique or sum(len(item["excerpt"]) for item in unique.values()) >= sum(
        len(str(item.get("excerpt", ""))) for item in evidence
    ):
        return common
    return {**common, "context": {**common["context"], "evidence": list(unique.values())}}


def build_planning(
    requirement: RequirementAnalysis,
    context: dict[str, Any],
    complete,
    analyses=None,
    *,
    target_count=None,
    on_progress=None,
    on_feature_progress=None,
    feature_plans=None,
    allow_empty=False,
    check_cancelled=lambda: None,
):
    """Plan disjoint feature groups concurrently; publish validated, stable snapshots."""
    features, points, groups = [], [], []
    batches = evidence_batches(context)
    def plan_features(index, batch):
        check_cancelled()
        local = analyses[index] if analyses else requirement
        common = {"requirement": local.model_dump(mode="json", exclude={"feature_points"}),
                  "context": batch}
        feature_plan = (feature_plans[index].model_copy(deep=True)
                        if feature_plans and (feature_plans[index].feature_points or allow_empty) else complete(
            "feature.generated",
            CASE_DESIGN_INSTRUCTION + "按本批资料规划全部相关功能，保留具体规则和来源。不生成用例。"
            "若context包含historical_cases，回归模式包含仍适用的核心场景，变更模式区分旧规则与本次新需求。"
            "历史用例仅作覆盖参考，不得把与新需求冲突的旧预期当成当前规则。"
            "module 为业务模块路径，name 为功能名；不得为凑数量合并不同功能。"
            "当前只是完整资料的一个分片，其他模块由其他批次处理。"
            "仅为本批有明确证据的规则生成功能；不得为全局数量补位、生成占位功能或推测其他模块规则。"
            "同一规则的样例记录不是新功能，功能名使用资料中的规则名称，保留原始规则编号。",
            common,
            FeaturePlan,
        ))
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
    # A verified rule in the same document is still the same rule when different
    # slices propose different module paths. Conflicting definitions never qualify.
    rule_modules = {}
    known_documents = {item.get("document_id") for item in context.get("evidence", [])}
    for _, feature_plan in feature_results:
        for feature in feature_plan.feature_points:
            name = source_rule_name(feature, context)
            documents = {ref.document_id for ref in feature.source_refs}
            if (name and len(documents) == 1 and None not in documents
                    and documents <= known_documents):
                identity = (next(iter(documents)), name)
                feature.name = name
                feature.module = rule_modules.setdefault(identity, feature.module)
    # Completion order must not change IDs, budgets, or downstream batch membership.
    for common, feature_plan in feature_results:
        features.extend(feature_plan.feature_points)
        for start in range(0, len(feature_plan.feature_points), FEATURES_PER_BATCH):
            group = feature_plan.feature_points[start : start + FEATURES_PER_BATCH]
            groups.append((compact_planning_context(common, group), group))

    if not features:
        if allow_empty:
            result = merge_planning([], [], context, len(batches))
            if on_progress:
                on_progress(result, {"completed_batches": 0, "total_batches": 0,
                                     "active_batches": [], "test_point_count": 0})
            return result
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
                TEST_POINT_DESIGN_INSTRUCTION + "\n【本批输出约束】\n"
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
        # A sample or chunk may end in a truncated rule, even before a newline.
        # Only complete, explicitly terminated definitions establish identity.
        pattern = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(candidate)
                             + r"\s*[:：]\s*([^\n。；;]+)(?=[。；;])")
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
        return context
    batches = evidence_batches(context)
    if len(batches) == 1:
        return batches[0]
    rules = []
    sources = []
    # Existing expected outcomes are under review, not source material. Supplying
    # them to extraction lets a model copy the very assertions we must check.
    def scope_only(value):
        if isinstance(value, dict):
            return {key: scope_only(item) for key, item in value.items()
                    if key not in {"expected", "source_refs"}}
        if isinstance(value, list):
            return [scope_only(item) for item in value]
        return value
    scope = scope_only(snapshot)

    def extract(index, batch):
        analysis = complete(
            "rewrite.evidence",
            "完整检查本批资料对选中用例集合的影响，仅提取相关规则到business_rules。"
            "保留数值、单位、例外和冲突；不相关则返回空列表。不修改用例、不扩大目标范围。"
            "business_rules逐条摘录context.evidence中的原文完整规则，不改写、不概括，保留规则编号和上下文条件。"
            "test_case只是检索范围，绝不是事实依据；禁止从用例标题、操作或前置条件推导业务规则。"
            "不输出测试步骤或预期，不补全资料未规定的状态、会话、文案或副作用。",
            {"test_case": scope, "context": batch},
            RequirementAnalysis,
        )
        return analysis

    analyses = analyze_batches(
        batches,
        extract,
        load=lambda *_: None,
        save=lambda *_: None,
        on_progress=lambda *_: None,
        check_cancelled=lambda: None,
    )
    for batch, analysis in zip(batches, analyses, strict=True):
        if not analysis.business_rules:
            continue
        matched = []
        for rule in analysis.business_rules:
            quote = rule.strip().rstrip("。.;；")
            found = None
            for source in batch["evidence"]:
                text = str(source.get("excerpt", ""))
                start = text.replace("：", ":").find(quote.replace("：", ":")) if quote else -1
                if start >= 0:
                    found = source, start, start + len(quote)
                    break
            if found is None:
                # A paraphrased rule with an explicit ID is a retrieval hint,
                # never evidence. Resolve the ID to its actual original sentence.
                ids = re.findall(r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9_.-]{0,79})\s*[:：]", rule)
                if len(set(ids)) == 1:
                    pattern = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(ids[0])
                                         + r"\s*[:：][^\n。；;]+[。；;]")
                    anchors = {}
                    for source in batch["evidence"]:
                        for match in pattern.finditer(str(source.get("excerpt", ""))):
                            anchors.setdefault(match.group(0), (source, match.start(), match.end()))
                    if anchors:
                        found, *others = anchors.values()
                        # Conflicting definitions of the same ID must all survive.
                        for source, start, end in others:
                            text = source["excerpt"]
                            rules.append(text[start:end])
                            matched.append({**source, "excerpt": text[max(0, start - 240):end + 240]})
            if found is None:
                # Preserve the entire batch on an unresolved rule; do not promote
                # a model paraphrase into the business_rules evidence list.
                matched = list(batch["evidence"])
                break
            source, start, end = found
            text = source["excerpt"]
            rules.append(text[start:end])
            matched.append({**source, "excerpt": text[max(0, start - 240):end + 240]})
        sources.extend(item for item in matched if item not in sources)
    # Merge overlapping windows from the same original chunk. Repeated rules
    # otherwise repeat their surrounding text and metadata in every model call.
    windows = {}
    for source in sources:
        metadata = {k: v for k, v in source.items() if k != "excerpt"}
        original = next((item for item in context["evidence"]
                         if {k: v for k, v in item.items() if k != "excerpt"} == metadata
                         and source["excerpt"] in item["excerpt"]), source)
        key = json.dumps(original, sort_keys=True)
        start = original["excerpt"].index(source["excerpt"])
        windows.setdefault(key, (original, []))[1].append((start, start + len(source["excerpt"])))
    sources = []
    for original, spans in windows.values():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        sources.extend({**original, "excerpt": original["excerpt"][start:end]} for start, end in merged)
    source_metadata = {json.dumps({k: v for k, v in item.items() if k != "excerpt"}, sort_keys=True):
                       {k: v for k, v in item.items() if k != "excerpt"} for item in sources}
    return {
        "business_rules": list(dict.fromkeys(rules)),
        "sources": list(source_metadata.values()),
        "evidence": sources,
        "processed_batches": len(batches),
        "warnings": context.get("warnings", []),
    }
