"""Review results are read-only, validated against the cases actually provided."""

import json
from collections.abc import Iterator
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CaseFinding(BaseModel):
    title: str
    severity: str = Field(pattern=r"^(high|medium|low)$")
    case_refs: list[str] = Field(min_length=1)
    evidence: str
    recommendation: str
    basis: Literal["requirement", "potential"] = "potential"
    relationship: Literal["duplicate", "overlap", "contains", "quality", "coverage"] | None = None
    unique_coverage: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence_for_confirmed_gap(self):
        if self.basis == "requirement" and not self.requirement_refs:
            self.basis = "potential"
        return self


class CaseAnalysisReport(BaseModel):
    summary: str
    findings: list[CaseFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)



def complete_analysis_batch(provider, *, instruction, payload, model_id, before_call=None):
    """Use short exact references and one bounded repair for invalid references."""
    from casepilot_agent.contracts import UsageMetadata

    cases = payload["cases"]
    aliases = {f"c{index}": str(item["ref"]) for index, item in enumerate(cases)}
    allowed = set(aliases.values())
    request = {**payload, "cases": [
        {**item, "ref": f"c{index}"} for index, item in enumerate(cases)
    ]}
    usage = UsageMetadata(model="")
    for attempt in range(2):
        if before_call:
            before_call()
        report, call_usage = provider.complete(
            stage="cases.analyzed",
            instruction=instruction + " findings.case_refs必须逐字复制本批输入ref（如c0），"
                "不能填写标题、用例显示编号或编造引用。validation_feedback只纠正引用，不扩大评审范围。",
            payload=request, result_type=CaseAnalysisReport, model_id=model_id,
        )
        usage.model = call_usage.model
        usage.latency_ms += call_usage.latency_ms
        for key, value in call_usage.token_usage.items():
            usage.token_usage[key] = usage.token_usage.get(key, 0) + value
        unknown = sorted({ref for finding in report.findings for ref in finding.case_refs
                          if ref not in aliases and ref not in allowed})
        if not unknown:
            for finding in report.findings:
                finding.case_refs = list(dict.fromkeys(aliases.get(ref, ref) for ref in finding.case_refs))
            return report, usage
        if attempt:
            raise ValueError("analysis_unknown_case_reference")
        request = {**request, "validation_feedback": {
            "unknown_references": unknown, "allowed_references": list(aliases),
            "previous_report": report.model_dump(mode="json"),
        }}
    raise AssertionError("unreachable_analysis_retry")

def exact_duplicate_findings(case_context: list[dict]) -> list[CaseFinding]:
    """Compare full business content across every batch without model truncation.

    Different business titles, modules, tags, or case types are not assumed
    interchangeable. Storage IDs and provenance do not change executable content.
    """
    groups: dict[str, list[str]] = {}
    for item in case_context:
        snapshot = item.get("snapshot") or {}
        steps = [
            {key: str(step.get(key) or "").strip() for key in ("action", "expected")}
            for step in snapshot.get("steps", [])
            if isinstance(step, dict)
        ]
        if (
            not str(snapshot.get("title") or "").strip()
            or not any(step["action"] for step in steps)
            or not any(step["expected"] for step in steps)
        ):
            continue
        content = {
            key: str(snapshot.get(key) or "").strip()
            for key in ("title", "module", "case_type", "description")
        }
        content.update(
            preconditions=[str(value).strip() for value in snapshot.get("preconditions", [])],
            steps=steps,
            tags=sorted(str(value) for value in snapshot.get("tags", [])),
        )
        fingerprint = sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        refs = groups.setdefault(fingerprint, [])
        if item["ref"] not in refs:
            refs.append(item["ref"])
    return [
        CaseFinding(
            title="用例业务内容完全相同",
            severity="medium",
            case_refs=refs,
            evidence="已比较完整原文：标题、模块、类型、描述、标签、前置条件及全部操作与预期相同；未截断步骤或字段。",
            recommendation="请核对来源、优先级及使用场景后选择保留项；本次检查不会自动删除用例。",
            relationship="duplicate",
        )
        for refs in groups.values()
        if len(refs) > 1
    ]


def _analysis_snapshot(snapshot: dict) -> dict:
    return {
        key: snapshot[key]
        for key in (
            "case_key",
            "title",
            "module",
            "priority",
            "case_type",
            "tags",
            "description",
            "preconditions",
            "steps",
            "source_refs",
        )
        if key in snapshot
    }


def equivalent_analysis_cases(case_context: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """Collapse only identical review inputs, retaining every original reference.

    Case keys and internal step IDs are identity, not review content. Priority,
    provenance and all business fields sent to the reviewer remain significant.
    """
    representatives: list[dict] = []
    aliases: dict[str, list[str]] = {}
    fingerprints: dict[str, str] = {}
    for item in case_context:
        canonical = dict(item.get("snapshot") or {})
        for identity in ("id", "case_key", "created_at", "current_revision_id"):
            canonical.pop(identity, None)
        if "steps" in canonical:
            canonical["steps"] = [
                {k: v for k, v in step.items() if k != "id"} if isinstance(step, dict) else step
                for step in canonical["steps"]
            ]
        key = sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        representative = fingerprints.get(key)
        if representative is None:
            representative = item["ref"]
            fingerprints[key] = representative
            representatives.append(item)
            aliases[representative] = []
        aliases[representative].append(item["ref"])
    return representatives, aliases


def analysis_batches(case_context: list[dict]) -> Iterator[list[dict]]:
    """Bound requests, never silently drop the tail of a case or a field."""
    batch: list[dict] = []
    size = 2
    for item in case_context:
        snapshot = item.get("snapshot") or {}
        complete = {"ref": item["ref"], "snapshot": _analysis_snapshot(snapshot)}
        encoded = json.dumps(complete["snapshot"], ensure_ascii=False)
        item_size = len(json.dumps(complete, ensure_ascii=False))
        if item_size > 15000:
            if batch:
                yield batch
                batch, size = [], 2
            # JSON text preserves every type, field and character; joining the
            # indexed pieces reconstructs the original reviewed snapshot exactly.
            # At 6000 serialized characters even double-escaping fits the budget.
            width = 6000
            count = (len(encoded) + width - 1) // width
            for index, offset in enumerate(range(0, len(encoded), width), 1):
                yield [
                    {
                        "ref": item["ref"],
                        "fragment_index": index,
                        "fragment_count": count,
                        "content_json_fragment": encoded[offset : offset + width],
                    }
                ]
            continue
        if batch and (len(batch) >= 20 or size + item_size + 2 > 16000):
            yield batch
            batch, size = [], 2
        batch.append(complete)
        size += item_size + 2
    if batch:
        yield batch


def constrain_fragment_findings(report: CaseAnalysisReport, batch: list[dict]) -> None:
    """A fragment cannot establish whole-case equivalence or a confirmed gap."""
    partial = {item["ref"] for item in batch if item.get("fragment_count", 1) > 1}
    for finding in report.findings:
        if not partial.intersection(finding.case_refs):
            continue
        if finding.relationship in {"duplicate", "contains"}:
            finding.relationship = "overlap"
            finding.basis = "potential"
            finding.title = "待核对的局部相似内容"
            finding.evidence = "局部比对线索（不能代表整条用例）：" + finding.evidence
            finding.recommendation = (
                "仅发现局部内容相似，请核对完整用例后再决定是否合并；不能据此直接删除。"
            )
        elif finding.relationship == "coverage":
            finding.basis = "potential"
            finding.recommendation = (
                "此发现仅基于一个内容片段，请核对完整用例及需求后确认是否存在覆盖缺口。"
            )


def cross_batch_comparisons(
    batches: list[list[dict]], *, max_batches: int = 64, weights: dict[str, int] | None = None
) -> tuple[list[list[dict]], int]:
    """Bridge original batches using full cases, with an explicit work bound.

    Every pair across two small groups appears together. No title similarity
    filter is used: synonyms and different titles must remain comparable.
    Return the number of cross-batch pairs actually supplied, not a claim that
    the model found every relationship. Oversized pairs remain unverified.
    """
    groups: list[tuple[int, list[dict]]] = []
    for index, batch in enumerate(batches):
        group: list[dict] = []
        for item in batch:
            if item.get("fragment_count", 1) > 1:
                continue
            if group and (
                len(group) >= 20 or len(json.dumps([*group, item], ensure_ascii=False)) > 7500
            ):
                groups.append((index, group))
                group = []
            group.append(item)
        if group:
            groups.append((index, group))
    bridges: list[list[dict]] = []
    compared = 0
    examined = 0
    for left_index, (origin, left) in enumerate(groups):
        for other_origin, right in groups[left_index + 1 :]:
            if origin == other_origin:
                continue
            pending = [(left, right)]
            while pending:
                if len(bridges) >= max_batches or examined >= max_batches * 16:
                    return bridges, compared
                part_left, part_right = pending.pop()
                examined += 1
                combined = [{**item, "comparison_group": "left"} for item in part_left] + [
                    {**item, "comparison_group": "right"} for item in part_right
                ]
                if len(json.dumps(combined, ensure_ascii=False)) > 16000:
                    if len(part_left) >= len(part_right) and len(part_left) > 1:
                        middle = len(part_left) // 2
                        pending.extend(
                            [(part_left[middle:], part_right), (part_left[:middle], part_right)]
                        )
                    elif len(part_right) > 1:
                        middle = len(part_right) // 2
                        pending.extend(
                            [(part_left, part_right[middle:]), (part_left, part_right[:middle])]
                        )
                    continue
                bridges.append(combined)
                compared += sum((weights or {}).get(item["ref"], 1) for item in part_left) * sum(
                    (weights or {}).get(item["ref"], 1) for item in part_right
                )
    return bridges, compared


def render_report(report: CaseAnalysisReport, case_context: list[dict]) -> str:
    labels = {
        item["ref"]: item.get("snapshot", {}).get("case_key", item["ref"]) for item in case_context
    }
    allowed = set(labels)
    if any(ref not in allowed for finding in report.findings for ref in finding.case_refs):
        raise ValueError("analysis_unknown_case_reference")
    lines = [f"已检查 {len(allowed)} 条用例。", report.summary]
    for index, finding in enumerate(report.findings, 1):
        lines.extend(
            [
                f"\n{index}. [{finding.severity}] {finding.title}",
                f"用例：{', '.join(labels[ref] for ref in finding.case_refs)}",
                f"依据：{finding.evidence}",
                f"建议：{finding.recommendation}",
            ]
        )
    if report.limitations:
        lines.extend(["\n检查限制：", *report.limitations])
    lines.append("\n以上为检查建议，尚未修改用例。")
    return "\n".join(lines)
