"""Review results are read-only, validated against the cases actually provided."""

import json
from collections.abc import Iterator

from pydantic import BaseModel, Field


class CaseFinding(BaseModel):
    title: str
    severity: str = Field(pattern=r"^(high|medium|low)$")
    case_refs: list[str] = Field(min_length=1)
    evidence: str
    recommendation: str


class CaseAnalysisReport(BaseModel):
    summary: str
    findings: list[CaseFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def analysis_batches(case_context: list[dict]) -> Iterator[list[dict]]:
    """Keep each model request bounded while preserving the fields needed for review."""
    batch: list[dict] = []
    size = 0
    for item in case_context:
        snapshot = item.get("snapshot") or {}
        compact = {
            "ref": item["ref"],
            "snapshot": {
                key: snapshot[key]
                for key in (
                    "case_key", "title", "module", "priority", "case_type",
                    "description", "preconditions", "steps", "source_refs",
                )
                if key in snapshot
            },
        }
        # One unusually long field must not make a single-case request unbounded.
        truncated = False
        for key, value in compact["snapshot"].items():
            if isinstance(value, str):
                compact["snapshot"][key] = value[:500]
                truncated |= len(value) > 500
            elif isinstance(value, list):
                truncated |= len(value) > 6
                compact["snapshot"][key] = [
                    str(part)[:300] if not isinstance(part, dict)
                    else {name: str(content)[:300] for name, content in part.items()}
                    for part in value[:6]
                ]
                truncated |= any(len(str(part)) > 300 for part in value[:6])
        if truncated:
            compact["truncated"] = True
        item_size = len(json.dumps(compact, ensure_ascii=False))
        if batch and (len(batch) >= 20 or size + item_size > 16000):
            yield batch
            batch, size = [], 0
        batch.append(compact)
        size += item_size
    if batch:
        yield batch


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
