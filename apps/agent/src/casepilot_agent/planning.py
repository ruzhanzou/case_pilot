"""Persistable planning, independent of executable test case generation."""

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from casepilot_agent.contracts import FeaturePlan, RequirementAnalysis, SourceRef, TestPointPlan


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


def build_planning(
    requirement: RequirementAnalysis, context: dict[str, Any], complete, analyses=None
):
    features, points = [], []
    batches = evidence_batches(context)
    for index, batch in enumerate(batches):
        local = analyses[index] if analyses else requirement
        common = {"requirement": local.model_dump(mode="json"), "context": batch}
        feature_plan = complete(
            "feature.generated",
            "按本批资料规划全部相关功能，保留具体规则和来源。不生成用例。"
            "module 为业务模块路径，name 为功能名；不得为凑数量合并不同功能。",
            common,
            FeaturePlan,
        )
        mapping = {}
        for ordinal, feature in enumerate(feature_plan.feature_points):
            stable_id = f"FP-{index + 1}-{ordinal + 1}"
            mapping[feature.id] = stable_id
            feature.id = stable_id
            if not feature.source_refs:
                feature.source_refs = [SourceRef.model_validate(item) for item in batch["evidence"]]
        plan = complete(
            "test_point.generated",
            "为给定功能逐项规划测试点，不生成用例正文。scenario 为具体业务场景，"
            "title 为需要验证的规则或条件；保留边界数值、例外和来源。"
            "feature_point_ids 只能引用给定功能 ID。数量按需求决定，不固定为正常异常边界三项。",
            {**common, "feature_points": feature_plan.model_dump(mode="json")},
            TestPointPlan,
        )
        allowed = {feature.id for feature in feature_plan.feature_points}
        for ordinal, point in enumerate(plan.test_points):
            point.id = f"TP-{index + 1}-{ordinal + 1}"
            if not point.source_refs:
                point.source_refs = [SourceRef.model_validate(item) for item in batch["evidence"]]
            point.feature_point_ids = [mapping.get(ref, ref) for ref in point.feature_point_ids]
            if not point.feature_point_ids or set(point.feature_point_ids) - allowed:
                raise ValueError("planning_feature_reference_invalid")
        features.extend(feature_plan.feature_points)
        points.extend(plan.test_points)
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
        "processed_batches": len(batches),
        "warnings": context.get("warnings", []),
    }


def planned_module(point, features) -> str:
    feature = next(item for item in features if item.id in point.feature_point_ids)
    parts = [part.strip() for part in feature.module.split("/") if part.strip()]
    for part in (feature.name, point.scenario, point.title):
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
