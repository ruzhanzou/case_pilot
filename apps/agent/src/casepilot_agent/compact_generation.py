"""Versioned, bounded model contracts for confirmed-plan generation.

The model writes case content, never database identities or duplicated citations.
An independent audit acknowledges every slot and returns only necessary replacements.
"""
import asyncio
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import Counter
from typing import Literal
from time import sleep

from agents.exceptions import ModelBehaviorError
from openai import APIConnectionError, APITimeoutError, RateLimitError, InternalServerError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from casepilot_agent.contracts import (
    CASE_DESIGN_INSTRUCTION, GENERATION_GROUNDING_INSTRUCTION, FeaturePlan, GenerationResult,
    QualityIssue, QualityReport, RequirementAnalysis, SourceRef, TestCaseDraft, TestPointPlan, TestStep,
)
from casepilot_agent.planning import planned_module

CONTRACT = "case_batch_v2"
BATCH_SIZE = 5
BATCH_CONCURRENCY = 2


class CaseContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    preconditions: list[str] = Field(min_length=1, max_length=12)
    steps: list[TestStep] = Field(min_length=1, max_length=4)


class ContentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_cases: list[CaseContent] = Field(min_length=1, max_length=BATCH_SIZE)


class AuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=1)
    verdict: Literal["supported", "revise"]
    replacement: CaseContent | None
    reason: str = Field(max_length=300)


class BatchAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviews: list[AuditItem] = Field(min_length=1, max_length=BATCH_SIZE)


class DuplicateResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equivalent: bool
    reason: str = Field(min_length=1, max_length=500)
    replacement: CaseContent


def reconcile_duplicates(result, request, execute_stage):
    """Review only colliding cases; retain coverage when equivalent cases merge."""
    from casepilot_agent.pipeline import validate_generation
    merged = 0
    for _ in range(len(result.test_cases)):
        report = validate_generation(result)
        issue = next((i for i in report.issues if i.code in {"duplicate_case", "duplicate_case_content"}), None)
        if issue is None:
            break
        duplicate = next(c for c in result.test_cases if c.id == issue.object_id)
        def fingerprint(case):
            return (sorted(x.strip().lower() for x in case.preconditions if x.strip()),
                    [x.action.strip().lower() for x in case.steps if x.action.strip()],
                    sorted(x.expected.strip().lower() for x in case.steps if x.expected.strip()))
        previous = result.test_cases[:result.test_cases.index(duplicate)]
        original = next(c for c in previous if
                        (c.title.strip().lower() == duplicate.title.strip().lower() if issue.code == "duplicate_case"
                         else fingerprint(c) == fingerprint(duplicate)))
        decision = execute_stage(
            "test_case.grounded", GENERATION_GROUNDING_INSTRUCTION + CASE_DESIGN_INSTRUCTION +
            "核对这两条冲突用例及原始证据。相同业务场景则equivalent=true，replacement为合并后的完整用例内容；"
            "不同场景则equivalent=false，replacement仅修正第二条，用准确场景标题消除重名，不得只加序号或改同义词。"
            "保留有依据的独立校验，删除无证据支持的推断，不得借合并扩大断言。replacement.slot固定为1。",
            {"repair_kind": "cross_batch_duplicate_v1", "cases": [c.model_dump(mode="json") for c in [original, duplicate]],
             "confirmed_brief": request.markdown_content, "evidence": request.confirmed_plan.get("evidence", [])},
            DuplicateResolution, request.model_id)
        if decision.replacement.slot != 1:
            raise StageContractError("duplicate_repair_slot_invalid")
        target = original if decision.equivalent else duplicate
        for field in ("title", "preconditions", "steps"):
            setattr(target, field, getattr(decision.replacement, field))
        if decision.equivalent:
            target.test_point_ids = list(dict.fromkeys(target.test_point_ids + duplicate.test_point_ids))
            target.source_refs.extend(ref for ref in duplicate.source_refs if ref not in target.source_refs)
            target.priority = min(target.priority, duplicate.priority)
            result.test_cases.remove(duplicate)
            merged += 1
        # Each decision must resolve its collision; do not spend unbounded calls.
        if any(i.object_id == duplicate.id and i.code in {"duplicate_case", "duplicate_case_content"}
               for i in validate_generation(result).issues):
            break
    return merged


class AuditStageError(RuntimeError):
    """Audit exhausted its retry budget; do not regenerate valid case content."""


class StageContractError(ValueError):
    """Valid JSON with invalid identities, cardinality, or audit decisions."""


def require_slots(items, slots):
    if Counter(item.slot for item in items) != Counter(slots):
        raise StageContractError("stage_slot_mismatch")


def coverage_rows(features, points, cases):
    """Derive traceability from actual ownership, not an extra model response."""
    rows = []
    for feature in features:
        owned = [p.id for p in points if feature.id in p.feature_point_ids]
        covered = [p for p in owned if any(p in c.test_point_ids for c in cases)]
        for requirement in feature.requirement_refs:
            if covered:
                rows.append({"requirement_ref": requirement, "feature_point_ids": [feature.id],
                             "test_point_ids": covered,
                             "test_case_ids": [c.id for c in cases if set(c.test_point_ids) & set(covered)]})
    return rows


def run_compact(request, provider, execute_stage, on_batch, count):
    from casepilot_agent.pipeline import validate_generation

    plan = request.confirmed_plan
    features = FeaturePlan.model_validate(plan).feature_points
    points = TestPointPlan.model_validate(plan).test_points
    if not points:
        raise StageContractError("planning_has_no_test_points")
    total = min(count, len(points)) if count else len(points)
    generated_by_slot = {}
    pending = [(offset, min(BATCH_SIZE, total - offset), 0) for offset in range(0, total, BATCH_SIZE)]
    def process_batch(offset, size, retry_attempt):
        slots = list(range(offset + 1, offset + size + 1))
        group = [points[(slot - 1) % len(points)] for slot in slots]
        feature_ids = {ref for point in group for ref in point.feature_point_ids}
        selected = [f for f in features if f.id in feature_ids]
        refs = [ref for item in [*group, *selected] for ref in item.source_refs]
        source_ids = {ref.chunk_id for ref in refs if ref.chunk_id}
        evidence = [item for item in plan.get("evidence", []) if item.get("chunk_id") in source_ids]
        # If legacy plans have no chunk links, retain evidence rather than silently
        # auditing against an empty source set. Each document appears only once.
        if not evidence:
            evidence = list(plan.get("evidence", []))
        common = {
            "output_contract": CONTRACT, "batch_start_index": offset + 1,
            "retry_attempt": retry_attempt,
            "batch_count": size, "total_count": total, "completed_count": offset,
            "prompt": request.prompt, "confirmed_brief": request.markdown_content,
            "user_requirements": [m for m in request.conversation_memory if m.get("role") == "user"],
            "evidence": evidence,
            "global_scenario_index": [{"id": p.id, "title": p.title, "scenario": p.scenario} for p in points],
            "features": [f.model_dump(exclude={"source_refs"}) for f in selected],
        }
        batch = execute_stage(
            "test_case.generated",
            GENERATION_GROUNDING_INSTRUCTION + CASE_DESIGN_INSTRUCTION +
            "仅为本批每个slot生成一条用例，slot必须原样保留且恰好覆盖全部slot。"
            "只输出title、preconditions、steps及slot；不输出来源、编号、模块、优先级等系统字段。"
            "每条用例一个明确目标，分别列出1至4项操作和整条用例的可观察校验点，不要求逐步配对；兼容steps行中action或expected可留空，但用例必须同时包含操作和校验点，不得用正常、符合预期代替断言。",
            {**common, "points": [
                {"slot": slot, "point": point.model_dump(exclude={"source_refs"})}
                for slot, point in zip(slots, group)
            ]}, ContentBatch, request.model_id,
        )
        require_slots(batch.test_cases, slots)
        content = {case.slot: case for case in batch.test_cases}
        if provider.name != "mock":
            for audit_attempt in range(2):
                try:
                    audit = execute_stage(
                        "test_case.grounded",
                        GENERATION_GROUNDING_INSTRUCTION + CASE_DESIGN_INSTRUCTION +
                        "独立核对本批全部slot。每个slot必须返回一个reviews条目。"
                        "有来源支持则verdict=supported、replacement=null；不要重复原用例。"
                        "存在无依据的断言则verdict=revise，在reason中说明原因并提供该slot的完整修正内容。"
                        "replacement.slot必须一致，保留已支持的操作和预期。不得遗漏slot或改变测试目标。",
                        {**common, "audit_attempt": audit_attempt, "test_cases": [content[slot].model_dump(mode="json") for slot in slots]},
                        BatchAudit, request.model_id,
                    )
                    require_slots(audit.reviews, slots)
                    for review in audit.reviews:
                        if review.verdict == "supported":
                            if review.replacement is not None:
                                raise StageContractError("supported_audit_has_replacement")
                        else:
                            if (review.replacement is None or review.replacement.slot != review.slot
                                    or not review.reason.strip()):
                                raise StageContractError("invalid_audit_replacement")
                            content[review.slot] = review.replacement
                    break
                except (ModelBehaviorError, ValidationError, StageContractError, APIConnectionError,
                        APITimeoutError, RateLimitError, InternalServerError) as error:
                    if audit_attempt:
                        raise AuditStageError("batch_audit_failed") from error
                    if isinstance(error, (APIConnectionError, RateLimitError, InternalServerError)):
                        sleep(1)
        validated = []
        for slot, point in zip(slots, group):
            case = content[slot]
            source_refs = point.source_refs or [r for f in selected if f.id in point.feature_point_ids for r in f.source_refs]
            # Hydrate canonical references on the server; never ask the model
            # to echo source documents or generate UUIDs.
            canonical = {str(e.get("chunk_id")): e for e in evidence}
            hydrated = []
            for ref in source_refs:
                source = canonical.get(str(ref.chunk_id))
                hydrated.append(SourceRef.model_validate(source) if source else ref)
            validated.append(TestCaseDraft(
                **case.model_dump(exclude={"slot"}),
                id=f"TC-{point.id}-{(slot - 1) // len(points) + 1}",
                module=planned_module(point, features), case_type=point.category,
                priority=point.priority, test_point_ids=[point.id],
                source_refs=hydrated or [SourceRef(label="用户输入", excerpt=request.prompt)],
            ))
        # Validate before publishing; no partial batch escapes a failed gate.
        candidate = GenerationResult(
            mode=provider.name, requirement=RequirementAnalysis(summary=request.prompt),
            feature_points=selected, test_points=group, test_cases=validated,
            coverage_matrix=coverage_rows(selected, group, validated),
            quality=QualityReport(passed=True, score=100),
        )
        errors = [i for i in validate_generation(candidate).issues if i.severity == "error"
                  and i.code not in {"duplicate_case", "duplicate_case_content"}]
        if errors:
            raise StageContractError("case_quality_invalid:" + ",".join(i.code for i in errors))
        return validated

    def worker(batch):
        # SDK synchronous runs require a per-thread loop. Close clients/tasks and
        # the loop before returning a pooled thread to another batch.
        with asyncio.Runner() as runner:
            asyncio.set_event_loop(runner.get_loop())
            return process_batch(*batch)

    def split(batch):
        offset, size, attempt = batch
        half = max(1, size // 2)
        return [(start, min(half, offset + size - start), attempt + 1)
                for start in range(offset, offset + size, half)]

    with ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY, thread_name_prefix="case-batch") as pool:
        active = {}
        try:
            while pending or active:
                while pending and len(active) < BATCH_CONCURRENCY:
                    batch = pending.pop(0)
                    active[pool.submit(worker, batch)] = batch
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda f: active[f][0]):
                    batch = active.pop(future)
                    offset, size, attempt = batch
                    try:
                        validated = future.result()
                    except (ModelBehaviorError, ValidationError, StageContractError):
                        if size == 1:
                            raise
                        pending[0:0] = split(batch)
                        continue
                    except (APIConnectionError, RateLimitError, InternalServerError):
                        if attempt == 0:
                            sleep(1)
                            pending.insert(0, (offset, size, 1))
                        else:
                            raise
                        continue
                    generated_by_slot.update(zip(range(offset, offset + size), validated))
                    if on_batch:
                        on_batch([generated_by_slot[i] for i in sorted(generated_by_slot)], total)
        except BaseException:
            # Stop dispatching on fatal errors/cancellation. Join in-flight work
            # before the job is marked failed, so no late writes follow failure.
            for future in active:
                future.cancel()
            raise
    generated = [generated_by_slot[i] for i in sorted(generated_by_slot)]
    result = GenerationResult(
        mode=provider.name,
        requirement=RequirementAnalysis(test_object=request.prompt, test_object_specified=True,
                                        summary=request.markdown_content or request.prompt),
        feature_points=features, test_points=points, test_cases=generated,
        coverage_matrix=coverage_rows(features, points, generated),
        quality=QualityReport(passed=True, score=100),
    )
    merged = reconcile_duplicates(result, request, execute_stage)
    result.coverage_matrix = coverage_rows(features, points, result.test_cases)
    result.quality = validate_generation(result)
    if merged:
        result.quality.issues.append(QualityIssue(code="duplicate_cases_merged", severity="warning",
            message=f"跨批审核合并{merged}条重复场景，保留测试点关联与来源。"))
    if total < len(points):
        for issue in result.quality.issues:
            if issue.code == "uncovered_test_point":
                issue.code, issue.severity = "planned_point_uncovered", "warning"
    if count and count > total:
        result.quality.issues.append(QualityIssue(
            code="independent_scenarios_below_target", severity="warning",
            message=f"请求{count}条，已确认独立场景仅{total}条；未循环测试点凑数。"))
    errors = sum(i.severity == "error" for i in result.quality.issues)
    result.quality.passed = errors == 0
    result.quality.score = max(0, 100 - errors * 25 - (len(result.quality.issues) - errors) * 8)
    return result
