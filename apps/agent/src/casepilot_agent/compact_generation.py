"""Versioned, bounded model contracts for confirmed-plan generation.

The model writes case content, never database identities or duplicated citations.
Local checks preserve complete candidates for human review without model audits.
"""
import asyncio
import re
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Literal

from agents.exceptions import ModelBehaviorError
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from casepilot_agent.contracts import (
    CASE_DESIGN_INSTRUCTION,
    GENERATION_GROUNDING_INSTRUCTION,
    FeaturePlan,
    GenerationResult,
    QualityIssue,
    QualityReport,
    RequirementAnalysis,
    SourceRef,
    TestCaseDraft,
    TestPointPlan,
    TestStep,
)
from casepilot_agent.planning import planned_module
from casepilot_agent.reuse import reuse_ref

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


class ReviewContentBatch(ContentBatch):
    # Preserve parseable siblings when one entry fails its content schema.
    test_cases: list[CaseContent | dict] = Field(default_factory=list, max_length=BATCH_SIZE)


class AssertionSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int = Field(ge=1)
    source_index: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=500)


class AuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=1)
    verdict: Literal["supported", "revise"]
    replacement: CaseContent | None
    reason: str = Field(max_length=300)
    assertions: list[AssertionSupport] = Field(default_factory=list)


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


def validate_assertion_support(review, case, sources):
    expected = {i + 1 for i, step in enumerate(case.steps) if step.expected.strip()}
    if {a.step for a in review.assertions} != expected:
        raise StageContractError("audit_expectations_not_covered")
    for assertion in review.assertions:
        quote = assertion.quote.strip()
        if not quote:
            raise StageContractError("audit_quote_not_in_original_source")
        # The model often numbers cited rules instead of the full evidence array.
        # Resolve literal text within this request's original sources, preferring
        # its selected source, and persist the server-resolved provenance.
        order = list(range(len(sources)))
        if assertion.source_index in order:
            order.remove(assertion.source_index)
            order.insert(0, assertion.source_index)
        match = next(((i, quote) for i in order if quote in sources[i]), None)
        if match is None and quote[-1] in "。.":
            alternate = quote[:-1] + {"。": ".", ".": "。"}[quote[-1]]
            # Never turn a decimal prefix into a complete sentence.
            pattern = re.escape(alternate) + (r"(?!\d)" if alternate.endswith(".") else "")
            match = next(((i, alternate) for i in order if re.search(pattern, sources[i])), None)
        if match is None:
            raise StageContractError("audit_quote_not_in_original_source")
        assertion.source_index, assertion.quote = match



def validate_case_content(case):
    if not case.title.strip() or not any(item.strip() for item in case.preconditions):
        raise StageContractError("empty_case_title_or_setup")
    if not any(s.action.strip() for s in case.steps) or not any(
        s.expected.strip() for s in case.steps
    ):
        raise StageContractError("empty_case_operations_or_expectations")


def validate_stage_result(result, payload):
    """Validate business identities before storing or reusing a checkpoint."""
    if isinstance(result, ContentBatch) and payload.get("validation_mode") == "human_review_basic":
        # Keep parseable responses so the batch runner can retain valid siblings
        # and repair only missing/invalid slots. This mode is part of the cache key.
        slots = {p["slot"] for p in payload.get("points", [])}
        response_slots = [c.get("slot") if isinstance(c, dict) else c.slot for c in result.test_cases]
        if slots and not any(isinstance(slot, int) and slot in slots for slot in response_slots):
            raise StageContractError("stage_slot_mismatch")
        return result
    if isinstance(result, ContentBatch):
        require_slots(result.test_cases, [p["slot"] for p in payload["points"]])
        for case in result.test_cases:
            validate_case_content(case)
    elif isinstance(result, BatchAudit):
        require_slots(result.reviews, [c["slot"] for c in payload["test_cases"]])
        for review in result.reviews:
            if review.verdict == "supported" and review.replacement is not None:
                raise StageContractError("supported_audit_has_replacement")
            if review.verdict == "revise" and (
                review.replacement is None
                or review.replacement.slot != review.slot
                or not review.reason.strip()
            ):
                raise StageContractError("invalid_audit_replacement")
            if review.replacement is not None:
                validate_case_content(review.replacement)
            if "grounding_sources" in payload:
                original = next(c for c in payload["test_cases"] if c["slot"] == review.slot)
                case = review.replacement or CaseContent.model_validate(original)
                validate_assertion_support(review, case, payload["grounding_sources"])
    elif isinstance(result, DuplicateResolution):
        if result.replacement.slot != 1:
            raise StageContractError("duplicate_repair_slot_invalid")
        validate_case_content(result.replacement)
    return result


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
    feature_ids = {f.id for f in features}
    if len(feature_ids) != len(features) or len({p.id for p in points}) != len(points):
        raise StageContractError("duplicate_planning_identity")
    if any(not p.feature_point_ids or not set(p.feature_point_ids) <= feature_ids for p in points):
        raise StageContractError("invalid_feature_reference")
    total = len(points)
    generated_by_slot = {}
    unresolved = {}
    repair_rounds = 0
    decisions = {d["point_id"]: d for d in plan.get("reuse", {}).get("decisions", [])}
    if plan.get("reuse", {}).get("strategy") == "fresh":
        decisions = {}
    remaining = []
    reused = {}
    for slot, point in enumerate(points, 1):
        decision = decisions.get(point.id)
        if decision and decision.get("point_snapshot") != point.model_dump(mode="json"):
            raise StageContractError("reuse_plan_changed_reanalyze_required")
        if not decision or decision["action"] != "reuse":
            remaining.append(slot)
            continue
        source = decision["source"]
        if source["key"] in reused:
            generated_by_slot[reused[source["key"]]].test_point_ids.append(point.id)
            continue
        snapshot = source["snapshot"]
        candidate = TestCaseDraft.model_validate({**snapshot, "id": f"TC-{point.id}-1",
            "module": snapshot.get("module") or planned_module(point, features),
            "test_point_ids": [point.id],
            "source_refs": [reuse_ref(decision).model_dump()]})
        validate_case_content(candidate)
        generated_by_slot[slot] = candidate
        reused[source["key"]] = slot
    if generated_by_slot and on_batch:
        on_batch([generated_by_slot[i] for i in sorted(generated_by_slot)], total)
    pending = [(remaining[offset:offset + BATCH_SIZE], 0, {}) for offset in range(0, len(remaining), BATCH_SIZE)]
    retryable = (ModelBehaviorError, ValidationError, StageContractError,
                 APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)

    def process_batch(slots, retry_attempt, feedback):
        group = [points[slot - 1] for slot in slots]
        selected_ids = {ref for point in group for ref in point.feature_point_ids}
        selected = [f for f in features if f.id in selected_ids]
        refs = [ref for item in [*group, *selected] for ref in item.source_refs]
        source_ids = {ref.chunk_id for ref in refs if ref.chunk_id}
        evidence = [item for item in plan.get("evidence", []) if item.get("chunk_id") in source_ids]
        if not evidence:
            evidence = list(plan.get("evidence", []))
        evidence = [{k: v for k, v in item.items() if k != "reference_cases"} for item in evidence]
        payload = {
            "output_contract": CONTRACT, "validation_mode": "human_review_basic",
            "batch_start_index": slots[0], "batch_slots": slots,
            "retry_attempt": retry_attempt, "validation_feedback": feedback,
            "batch_count": len(slots), "total_count": total, "completed_count": slots[0] - 1,
            "prompt": request.prompt, "confirmed_brief": request.markdown_content,
            "user_requirements": [m for m in request.conversation_memory if m.get("role") == "user"],
            "evidence": evidence,
            "reuse_modifications": [{"slot": slot, "original": decisions[point.id]["source"]["snapshot"],
                                      "change_reason": decisions[point.id]["reason"]}
                                     for slot, point in zip(slots, group, strict=True)
                                     if point.id in decisions and decisions[point.id]["action"] == "modify"],
            "global_scenario_index": [{"id": p.id, "title": p.title, "scenario": p.scenario} for p in points],
            "features": [f.model_dump(exclude={"source_refs"}) for f in selected],
            "points": [{"slot": slot, "point": point.model_dump(exclude={"source_refs"})}
                       for slot, point in zip(slots, group, strict=True)],
        }
        try:
            batch = execute_stage(
                "test_case.generated",
                GENERATION_GROUNDING_INSTRUCTION + CASE_DESIGN_INSTRUCTION +
                "若有reuse_modifications，基于original仅修改受当前需求影响的内容，保留未变部分；旧规则与新需求冲突时新需求优先。"
                "仅为本批每个slot生成一条用例，slot必须原样保留且恰好覆盖全部slot。"
                "只输出title、preconditions、steps及slot；不输出来源、编号、模块、优先级等系统字段。"
                "每条用例一个明确目标，分别列出1至4项操作和整条用例的可观察校验点，不要求逐步配对；"
                "steps行中action或expected可留空，但用例必须同时包含操作和校验点，"
                "不得用正常、符合预期代替断言。若有validation_feedback，只修复本次指定slot的问题。",
                payload, ReviewContentBatch, request.model_id,
            )
        except retryable as error:
            reason = str(error) if isinstance(error, StageContractError) else "generation_response_invalid"
            return {}, dict.fromkeys(slots, reason)
        parsed = []
        invalid_slots = set()
        for raw in batch.test_cases:
            try:
                parsed.append(CaseContent.model_validate(raw))
            except ValidationError:
                slot = raw.get("slot") if isinstance(raw, dict) else None
                if isinstance(slot, int) and slot in slots:
                    invalid_slots.add(slot)
        frequencies = Counter(case.slot for case in parsed)
        content = {case.slot: case for case in parsed
                   if frequencies[case.slot] == 1 and case.slot not in invalid_slots}
        valid, invalid = {}, {}
        canonical = {str(e.get("chunk_id")): e for e in evidence if e.get("chunk_id")}
        for slot, point in zip(slots, group, strict=True):
            case = content.get(slot)
            if case is None:
                invalid[slot] = "missing_or_duplicate_slot"
                continue
            try:
                validate_case_content(case)
                if any(step.expected.strip() in {"正常", "结果正常", "符合预期", "结果符合预期"}
                       for step in case.steps):
                    raise StageContractError("vague_test_validation")
            except StageContractError as error:
                invalid[slot] = str(error)
                continue
            source_refs = point.source_refs or [r for f in selected
                                               if f.id in point.feature_point_ids for r in f.source_refs]
            hydrated = []
            for ref in source_refs:
                if ref.chunk_id and str(ref.chunk_id) in canonical:
                    hydrated.append(SourceRef.model_validate(canonical[str(ref.chunk_id)]))
                elif not any((ref.chunk_id, ref.document_id, ref.source_id)):
                    hydrated.append(ref)
                else:
                    # A dangling source identity is a plan error, never an excuse
                    # to fabricate provenance or silently use an unrelated source.
                    raise StageContractError("invalid_source_reference")
            if point.id in decisions and decisions[point.id]["action"] == "modify":
                hydrated.append(reuse_ref(decisions[point.id]))
            valid[slot] = TestCaseDraft(
                **case.model_dump(exclude={"slot"}), id=f"TC-{point.id}-1",
                module=planned_module(point, features), case_type=point.category,
                priority=point.priority, test_point_ids=[point.id],
                source_refs=hydrated or [SourceRef(label="用户输入", excerpt=request.prompt)],
            )
        return valid, invalid

    def worker(batch):
        with asyncio.Runner() as runner:
            asyncio.set_event_loop(runner.get_loop())
            return process_batch(*batch)

    with ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY, thread_name_prefix="case-batch") as pool:
        active = {}
        try:
            while pending or active:
                while pending and len(active) < BATCH_CONCURRENCY:
                    batch = pending.pop(0)
                    active[pool.submit(worker, batch)] = batch
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda f: active[f][0]):
                    slots, attempt, _ = active.pop(future)
                    repair_rounds = max(repair_rounds, attempt)
                    valid, invalid = future.result()
                    generated_by_slot.update(valid)
                    if valid and on_batch:
                        on_batch([generated_by_slot[i] for i in sorted(generated_by_slot)], total)
                    if invalid and attempt == 0:
                        # Fresh batches go first. Each failed slot gets just one
                        # repair, without regenerating successful siblings.
                        repair_groups = []
                        for slot in sorted(invalid):
                            if not repair_groups or repair_groups[-1][-1] + 1 != slot:
                                repair_groups.append([])
                            repair_groups[-1].append(slot)
                        pending.extend((group, 1, {s: invalid[s] for s in group})
                                       for group in repair_groups)
                    else:
                        unresolved.update(invalid)
        except BaseException:
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
    result.quality = validate_generation(result)
    for issue in result.quality.issues:
        if issue.code in {"duplicate_case", "duplicate_case_content"}:
            issue.severity = "warning"
            issue.message += "；请人工审阅确认是否保留"
        elif issue.code == "uncovered_test_point" and any(points[s - 1].id == issue.object_id for s in unresolved):
            issue.severity = "warning"
            point = next(p for p in points if p.id == issue.object_id)
            issue.message = f"待完善：{point.title}（{point.id}）。一次修复后仍未通过基础校验，尚无可采纳用例。"
    result.quality.issues.append(QualityIssue(
        code="manual_review_required", severity="warning",
        message="已完成本地基础校验，未进行模型复审；请人工确认业务预期、覆盖范围和重复场景后再采纳。"))
    if count and count > total:
        result.quality.issues.append(QualityIssue(
            code="independent_scenarios_below_target", severity="warning",
            message=f"请求{count}条，已确认独立场景仅{total}条；未循环测试点凑数。"))
    errors = sum(i.severity == "error" for i in result.quality.issues)
    result.quality.passed = errors == 0
    result.quality.structural_passed = errors == 0
    result.quality.grounding_status = "unverified"
    result.quality.repair_rounds = repair_rounds
    result.quality.score = max(0, min(90, 100 - errors * 25 - (len(result.quality.issues) - errors) * 8))
    return result
