"""Persistable planning, independent of executable test case generation."""

import asyncio
import json
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from copy import deepcopy
from time import sleep
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from pydantic import Field, FiniteFloat, create_model, model_validator
from pydantic.json_schema import SkipJsonSchema

from casepilot_agent.contracts import (
    CASE_DESIGN_INSTRUCTION,
    TEST_POINT_DESIGN_INSTRUCTION,
    FeaturePlan,
    FeaturePoint,
    RequirementAnalysis,
    TestPoint,
    TestPointPlan,
)
from casepilot_agent.planning_boundary import (
    BoundaryContract,
    BoundarySample,
    UnresolvedBoundaryContract,
    boundary_evidence_bindings,
    project_boundary_metadata,
    validate_boundary_contracts,
)
from casepilot_agent.planning_coverage import (
    COVERAGE_INSTRUCTION,
    MAX_COVERAGE_OBLIGATIONS,
    CoverageDuplicateSuggestion,
    CoverageObligation,
    CoverageReport,
    schema_coverage_guard,
    validate_completion_ownership,
    validate_coverage,
)
from casepilot_agent.planning_sources import (
    bind_primary_selection,
    feature_source_slots,
    payload_catalog,
    point_source_selection_type,
    primary_bindings,
    project_feature_sources,
    project_point_sources,
    source_selection_schema,
    validate_primary_sources,
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
                    active[pool.submit(copy_context().run, worker, index)] = index
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
POINTS_PER_BATCH = 24
MAX_DEFAULT_POINTS = 240
MAX_POINT_BATCHES = 32
MAX_CONSOLIDATED_EVIDENCE_CHARS = 180000



class PlanningAnalysis(ReuseAnalysis):
    """Extract requirements and their features in one pass over large documents."""

    feature_points: list[FeaturePoint] = Field(default_factory=list)
    planning_update_mode: Literal["merge", "replace"] = "merge"
    planning_revision_action: Literal["upsert", "delete_only"] = Field(
        default="upsert", description=(
            "本轮只删除已有测试点/功能且保留其余内容时必须delete_only，不生成替代内容；"
            "有新增或替换场景时才用upsert。"
        ),
    )
    superseded_feature_ids: list[str] = Field(default_factory=list)
    superseded_test_point_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_revision_action(self):
        if self.planning_revision_action == "delete_only":
            if self.planning_update_mode != "merge" or not (
                self.superseded_feature_ids or self.superseded_test_point_ids
            ):
                raise ValueError("delete_only_revision_requires_explicit_removals")
            # The model-declared operation is a deletion, so its output budget
            # is zero even if the model redundantly restates retained features.
            self.feature_points = []
        return self


def requested_planning_quantity(
    prompt: str,
    execute,
    conversation_memory=None,
    planning_context=None,
    approved_source_catalog=None,
):
    from casepilot_agent.quantity import interpret_quantity

    return interpret_quantity(
        execute,
        {
            "prompt": prompt,
            "conversation_memory": conversation_memory or [],
            "planning_context": planning_context,
            "approved_source_catalog": approved_source_catalog or [],
        },
    )


def requested_point_count(
    prompt: str, execute, conversation_memory=None, planning_context=None
) -> int | None:
    return requested_planning_quantity(
        prompt, execute, conversation_memory, planning_context
    ).test_point_count


def reconcile_planning(previous, incoming, analyses):
    """Apply an explicit revision; omission in an incremental response is not deletion."""
    if analyses and all(isinstance(item, PlanningAnalysis) and item.planning_revision_action == "delete_only"
                        for item in analyses):
        if not previous or incoming.get("test_points") or incoming.get("feature_points"):
            raise ValueError("delete_only_revision_generated_content")
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
    # Retained points keep their immutable numeric evidence. This is historical
    # point provenance, never sampling authority for this new request. Incoming
    # point IDs replace prior identities, so they cannot inherit an old contract.
    retained_ids = set(points) - {item["id"] for item in incoming.get("test_points", [])}
    retained_batches = []
    for old_batch in (previous.get("coverage_review") or {}).get("batches", []):
        batch = deepcopy(old_batch)
        obligations = []
        for obligation in batch.get("obligations", []):
            links = [ref for ref in obligation.get("point_ids", []) if ref in retained_ids]
            if not links:
                continue
            obligation["point_ids"] = links
            obligations.append(obligation)
        if not obligations:
            continue
        batch["obligations"] = obligations
        identifiers = {item["id"] for item in obligations}
        batch["uncovered_ids"] = [ref for ref in batch.get("uncovered_ids", [])
                                  if ref in identifiers]
        batch["duplicate_suggestions"] = []
        batch["warnings"] = list(dict.fromkeys([
            *batch.get("warnings", []), "retained_previous_point_coverage",
        ]))
        retained_batches.append(batch)
    if retained_batches:
        review = result.setdefault("coverage_review", {
            "status": "pending_independent_review", "source": "model_proposed", "batches": [],
        })
        current_batches = review.setdefault("batches", [])
        next_index = max((batch.get("batch_index", 0) for batch in current_batches), default=0) + 1
        for offset, batch in enumerate(retained_batches):
            batch["batch_index"] = next_index + offset
        current_batches.extend(retained_batches)
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
    matched_originals = set()
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
                # Server-hydrated refs retain full original text. A unique, explicitly
                # named rule may still use the existing bounded context window; derive
                # its quotation from this source, never from model-authored excerpts.
                source_quote = quote
                if ref.excerpt == text and len(feature.requirement_refs) == 1:
                    rule = feature.requirement_refs[0].strip()
                    if rule and len(rule) <= 80:
                        pattern = (r"(?<![A-Za-z0-9_.-])" + re.escape(rule)
                                   + r"\s*[:：]\s*[^\n。；;]+[。；;]")
                        matches = set(re.findall(pattern, text))
                        if len(matches) == 1:
                            source_quote = matches.pop()
                # ASCII/full-width colons occupy one character, so offsets still
                # refer to the original text and no rule content is rewritten.
                start = text.replace("：", ":").find(source_quote.replace("：", ":"))
                if start < 0:
                    continue
                # Keep nearby exceptions/qualifications, not just the cited sentence.
                lower, upper = max(0, start - 240), start + len(source_quote) + 240
                if source_quote != quote:
                    omitted = text[:lower] + text[upper:]
                    # New full-text projection must not discard remote rule sentences,
                    # numeric limits, or explicit qualifications. Ambiguity falls back
                    # to the entire authorized source, never a guessed short summary.
                    if re.search(
                        r"[。；;.!?！？\d]|除外|例外|除非|不适用|不包括|"
                        r"exception|except|unless|exempt|however",
                        omitted, re.IGNORECASE,
                    ):
                        return common
                excerpt = text[lower:upper]
                matched.append({**source, "excerpt": excerpt})
                matched_originals.add(json.dumps(source, sort_keys=True))
                ref_matched = True
            if not ref_matched:
                return common
        if not matched:
            return common
        selected.extend(matched)
    # Feature ownership must not hide other rules supplied in this same batch:
    # point models can need their independent evidence for state interactions.
    selected.extend(source for source in evidence
                    if json.dumps(source, sort_keys=True) not in matched_originals)
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
                  "context": batch, "source_catalog": payload_catalog(batch)}
        feature_plan = (feature_plans[index].model_copy(deep=True)
                        if feature_plans and (feature_plans[index].feature_points or allow_empty) else complete(
            "feature.generated",
            CASE_DESIGN_INSTRUCTION + "按本批资料规划全部相关功能，保留具体规则和来源。不生成用例。"
            "若context包含historical_cases，回归模式包含仍适用的核心场景，变更模式区分旧规则与本次新需求。"
            "历史用例仅作覆盖参考，不得把与新需求冲突的旧预期当成当前规则。"
            "module 为业务模块路径，name 为功能名；不得为凑数量合并不同功能。"
            "当前只是完整资料的一个分片，其他模块由其他批次处理。"
            "仅为本批有明确证据的规则生成功能；不得为全局数量补位、生成占位功能或推测其他模块规则。"
            "同一规则的样例记录不是新功能，功能名使用资料中的规则名称，保留原始规则编号。"
            "source_refs仅选择source_catalog的slot填入locator；三个身份ID必须为null。"
            "引用正文、名称与真实来源标识由服务器填充，不要发明来源。",
            common,
            source_selection_schema(FeaturePlan, batch),
        ))
        feature_plan = project_feature_sources(feature_plan, batch)
        for ordinal, feature in enumerate(feature_plan.feature_points):
            feature.id = f"FP-{index + 1}-{ordinal + 1}"
            feature.name = source_rule_name(feature, batch) or feature.name
        check_cancelled()
        # Point models select only features; do not duplicate full source catalogs
        # alongside the compacted evidence used by the next stage.
        common.pop("source_catalog", None)
        common["_canonical_context"] = batch
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
    coverage_batches = {}
    coverage_limits = {
        "max_points": MAX_DEFAULT_POINTS,
        "max_batches": MAX_POINT_BATCHES,
        "max_completion_rounds": 1,
        "max_model_calls": MAX_POINT_BATCHES * 3,
    }
    if target_count is None and (
        len(groups) > MAX_POINT_BATCHES or len(features) > MAX_DEFAULT_POINTS
    ):
        result = merge_planning(features, [], context, len(batches))
        result["coverage_review"] = {
            "status": "pending_independent_review",
            "source": "model_proposed",
            "batches": [],
            "limits": coverage_limits,
            "warnings": ["coverage_scope_limit"],
        }
        return result
    budget = (
        target_count
        if target_count is not None
        else min(MAX_DEFAULT_POINTS, len(groups) * POINTS_PER_BATCH)
    )
    if target_count is not None and target_count < len(features):
        if (
            sum(len(str(e.get("excerpt", ""))) for e in context.get("evidence", []))
            > MAX_CONSOLIDATED_EVIDENCE_CHARS
        ):
            raise ValueError("planning_budget_requires_smaller_scope")
        local = requirement.model_dump(mode="json", exclude={"feature_points"})
        for field, value in list(local.items()):
            if isinstance(value, list):
                merged = {
                    json.dumps(v, sort_keys=True): v
                    for common, _ in groups
                    for v in common["requirement"].get(field, [])
                }
                local[field] = list(merged.values())
        groups = [
            (
                compact_planning_context({"requirement": local, "context": context}, features),
                features,
            )
        ]
    quotas = [budget // len(features) + (i < budget % len(features)) for i in range(len(features))]
    feature_budget = dict(zip((f.id for f in features), quotas, strict=True))
    completed = {}
    active = {}

    def coverage_metadata():
        ordered = [p for index in sorted(completed) for p in completed[index]]
        stable_ids = _stable_point_ids(features, ordered)
        reviewed_batches = deepcopy(
            [coverage_batches[i] for i in sorted(completed) if i in coverage_batches]
        )
        for batch in reviewed_batches:
            for item in [*batch["obligations"], *batch["duplicate_suggestions"]]:
                item["point_ids"] = [stable_ids[ref] for ref in item["point_ids"]]
        return {
            "status": "pending_independent_review",
            "source": "model_proposed",
            "batches": reviewed_batches,
            "limits": coverage_limits,
            "warnings": [],
        }

    def publish():
        ordered = [p for index in sorted(completed) for p in completed[index]]
        snapshot = merge_planning(features, ordered, context, len(batches))
        snapshot["coverage_review"] = coverage_metadata()
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
            quota = sum(feature_budget[f.id] for f in feature_slice)
            count = quota if target_count is not None else min(POINTS_PER_BATCH, quota)
            allowed_ref = Literal[tuple(f.id for f in feature_slice)]
            source_point_type = point_source_selection_type(TestPoint, common["context"])
            bindings = primary_bindings(feature_slice, common["context"])
            if not bindings:
                raise ValueError("planning_primary_binding_unavailable")
            binding_ref = Literal[tuple(item["id"] for item in bindings)]
            boundary_bindings = boundary_evidence_bindings(common["context"])

            def expand_binding(value):
                return schema_coverage_guard(bind_primary_selection, value, bindings)

            def expand_assertion(value):
                if not isinstance(value, dict):
                    return value
                selected = next((b for b in bindings
                                 if b["id"] == value.get("assertion_binding")), None)
                if selected is None:
                    return value
                data = deepcopy(value)
                for field, expected in (("assertion_feature_id", selected["feature_id"]),
                                        ("assertion_source_slot", selected["source_slot"])):
                    if data.get(field) not in (None, "", expected):
                        schema_coverage_guard(_boundary_binding_conflict)
                    data[field] = expected
                return data

            sample_type = create_model(
                "BatchBoundarySample", __base__=BoundarySample,
                value=(SkipJsonSchema[FiniteFloat | None], None),
                assertion_binding=(binding_ref, ...),
                assertion_feature_id=(SkipJsonSchema[str], ""),
                assertion_source_slot=(SkipJsonSchema[str], ""),
                assertion_source_ref=(SkipJsonSchema[type(None)], None),
                quantity_axis_id=(SkipJsonSchema[str | None], None),
                unit=(SkipJsonSchema[Literal[""]], ""),
                axis=(SkipJsonSchema[Literal[""]], ""),
                time_origin=(SkipJsonSchema[Literal[""]], ""),
                __validators__={"expand_assertion": model_validator(mode="before")(
                    expand_assertion)},
            )
            point_type = create_model(
                "BatchTestPoint", __base__=source_point_type,
                scenario=(str, Field(min_length=1)),
                boundary_samples=(list[sample_type] | None, None),
                primary_binding=(binding_ref, ...),
                primary_feature_id=(SkipJsonSchema[allowed_ref | None], None),
                feature_point_ids=(list[allowed_ref], Field(default_factory=list)),
                source_refs=(source_point_type.model_fields["source_refs"].annotation,
                             Field(default_factory=list)),
                __validators__={"expand_binding": model_validator(mode="before")(expand_binding)},
            )

            def validate_batch(plan):
                validate_point_batch(
                    plan, {f.id for f in feature_slice}, count, exact=target_count is not None
                )
                for point in plan.test_points:
                    if not point.scenario.strip():
                        schema_coverage_guard(_scenario_required)
                obligations = getattr(plan, "coverage_obligations", [])
                suggestions = getattr(plan, "duplicate_suggestions", [])
                for obligation_index, obligation in enumerate(obligations):
                    structural_metadata = {
                        "obligation_index": obligation_index,
                        "dimension": obligation.dimension,
                        "contract_present": obligation.boundary_contract is not None,
                        "clarification_present": bool(obligation.clarification.strip()),
                        "point_count": len(obligation.point_ids),
                    }
                    if isinstance(obligation.boundary_contract, UnresolvedBoundaryContract):
                        # Validate all submitted IDs/ownership before removing uncertified
                        # links. Ordinary draft points survive; hard samples never do.
                        candidate = obligation.model_dump(mode="json")
                        reason = obligation.boundary_contract.reason
                        candidate.update(boundary_contract=None, clarification="")
                        schema_coverage_guard(validate_coverage, [candidate], plan.test_points,
                                              {f.id for f in feature_slice})
                        if any(sample.obligation_id == obligation.id
                               for point in plan.test_points
                               for sample in point.boundary_samples or []):
                            schema_coverage_guard(_boundary_contract_required, structural_metadata)
                        obligation.boundary_contract = None
                        obligation.point_ids = []
                        obligation.clarification = reason
                    if (obligation.dimension == "boundary"
                            and obligation.boundary_contract is None
                            and not obligation.clarification.strip()):
                        schema_coverage_guard(_boundary_contract_required, structural_metadata)
                incomplete = schema_coverage_guard(
                    validate_boundary_contracts, obligations, plan.test_points,
                    common["context"], feature_source_slots(feature_slice, common["context"]),
                    derive_missing_values=True,
                )
                # Canonical source projection also validates canonical sample values.
                # Derive new request-local coordinates first; no output is published
                # until this independent source/primary guard succeeds as well.
                schema_coverage_guard(
                    validate_primary_sources, plan, feature_slice, common["context"]
                )
                if obligations or suggestions:
                    schema_coverage_guard(validate_coverage, obligations, plan.test_points,
                                          {f.id for f in feature_slice}, suggestions,
                                          incomplete=incomplete)
                return plan

            source_slot_ref = Literal[tuple(item["slot"]
                                            for item in payload_catalog(common["context"]))]
            def expand_boundary_evidence(value):
                if not isinstance(value, dict):
                    return value
                data = deepcopy(value)
                selected = next((entry for entry in boundary_bindings
                                 if entry["id"] == data.get("evidence_binding")), None)
                # Old scripted/cache inputs remain valid only with exact matching
                # current evidence. Model-facing schema requires the selector.
                if selected is None and "evidence_binding" not in data:
                    selected = next((entry for entry in boundary_bindings
                                     if entry["source_slot"] == data.get("source_slot")
                                     and entry["threshold"] == data.get("threshold")
                                     and entry["source_literal"]
                                     in data.get("source_literal", "")), None)
                    if selected:
                        data["evidence_binding"] = selected["id"]
                        data["source_literal"] = selected["source_literal"]
                if selected:
                    for field in ("source_slot", "source_literal", "threshold",
                                  "unit", "quantity_axis_id", "sampling_step", "sampling_literal"):
                        if field in data and data[field] != selected[field]:
                            code = ("planning_boundary_sampling_invalid"
                                    if field in {"sampling_step", "sampling_literal"}
                                    else "planning_boundary_binding_conflict")
                            schema_coverage_guard(_boundary_binding_conflict, code)
                        data[field] = selected[field]
                return data

            contract_type = create_model(
                "BatchBoundaryContract", __base__=BoundaryContract,
                evidence_binding=(Literal[tuple(entry["id"] for entry in boundary_bindings)]
                                  if boundary_bindings else Literal["unavailable"], ...),
                source_slot=(SkipJsonSchema[source_slot_ref], ""),
                source_literal=(SkipJsonSchema[str], ""),
                unit=(SkipJsonSchema[str], ""),
                quantity_axis_id=(SkipJsonSchema[str | None], None),
                sampling_step=(SkipJsonSchema[float | None], None),
                sampling_literal=(SkipJsonSchema[str], ""),
                axis=(str, Field(min_length=1, description=(
                    "Proposed human-readable axis description, not a machine identity or proof."))),
                time_origin=(str, Field(min_length=1, description=(
                    "Proposed time-origin for human review; not_applicable for counts."))),
                threshold=(
                    SkipJsonSchema[BoundaryContract.model_fields["threshold"].annotation], 0.0
                ),
                source_ref=(SkipJsonSchema[type(None)], None),
                __validators__={"expand_evidence": model_validator(mode="before")(
                    expand_boundary_evidence)},
            )
            contract_choice = (contract_type | UnresolvedBoundaryContract
                               if boundary_bindings else UnresolvedBoundaryContract)

            def restore_clarification(value):
                # Canonical/cache form stores unresolved state as clarification,
                # not a new persisted contract shape. Restore only that explicit state.
                if (isinstance(value, dict) and value.get("dimension") == "boundary"
                        and value.get("boundary_contract") is None
                        and not value.get("point_ids")
                        and isinstance(value.get("clarification"), str)
                        and value["clarification"].strip()):
                    data = deepcopy(value)
                    data["boundary_contract"] = dict(
                        status="unresolved", reason=data["clarification"]
                    )
                    return data
                return value

            boundary_obligation_type = create_model(
                "BatchBoundaryObligation", __base__=CoverageObligation,
                dimension=(Literal["boundary"], ...),
                boundary_contract=(contract_choice, ...),
                feature_point_ids=(list[allowed_ref], Field(min_length=1, max_length=24)),
                __validators__={"restore_clarification": model_validator(mode="before")(
                    restore_clarification)},
            )
            ordinary_obligation_type = create_model(
                "BatchOrdinaryObligation", __base__=CoverageObligation,
                dimension=(Literal["normal", "exception", "state"], ...),
                boundary_contract=(type(None), None),
                feature_point_ids=(list[allowed_ref], Field(min_length=1, max_length=24)),
            )
            obligation_type = boundary_obligation_type | ordinary_obligation_type
            plan_type = create_model(
                "BatchTestPointPlan",
                __base__=TestPointPlan,
                test_points=(
                    list[point_type],
                    Field(min_length=count if target_count is not None else 1, max_length=count),
                ),
                coverage_obligations=(
                    list[obligation_type],
                    Field(default_factory=list, max_length=MAX_COVERAGE_OBLIGATIONS),
                ),
                duplicate_suggestions=(
                    list[CoverageDuplicateSuggestion],
                    Field(default_factory=list, max_length=24),
                ),
                __validators__={"validate_batch": model_validator(mode="after")(validate_batch)},
            )
            plan = None
            for attempt in range(2):
                check_cancelled()
                try:
                    plan = complete(
                        "test_point.generated",
                        TEST_POINT_DESIGN_INSTRUCTION
                        + "\n"
                        + COVERAGE_INSTRUCTION
                        + "\n【本批输出约束】\n"
                        "title保留边界数值和例外。feature_point_ids是所属功能ID，不是测试点序号，"
                        "必须逐字复用本批feature_points的id，多个测试点可以复用同一个功能ID，严禁递增或发明功能ID。"
                        "本批每个功能ID都必须被至少一个测试点关联；一个测试点可以同时关联多个相关功能ID，"
                        "数量预算小于功能数时也不能遗漏功能关联，不得通过超出数量预算来修复。"
                        "本批数量为batch_count；target_count非空表示用户明确指定数量，必须恰好输出batch_count个不同测试点，"
                        "不得合并用户明确拆开的测试点；target_count为空时batch_count只是上限。不得在本批重复追求全局总数。"
                        "coverage_matrix留空；source_refs独立选择本请求source_catalog槽填locator，三个身份ID为null。"
                        "feature_point_ids仅表示功能归属，不是全部证据依赖；跨规则场景引用所有实际依据槽。"
                        "不得引用本请求未展示的其他分片来源。使用简洁字段，不重复原文。",
                        {
                            **{
                                key: value
                                for key, value in common.items()
                                if not key.startswith("_")
                            },
                            "source_catalog": payload_catalog(common["context"]),
                            "primary_bindings": bindings,
                            "boundary_evidence_bindings": boundary_bindings,
                            "feature_source_slots": feature_source_slots(
                                feature_slice, common["context"]
                            ),
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
                    break
                except (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError):
                    if attempt:
                        raise
                    for _ in range(4):
                        check_cancelled()
                        sleep(0.5)
            assert plan is not None
            validate_point_batch(
                plan, {f.id for f in feature_slice}, count, exact=target_count is not None
            )
            validate_primary_sources(plan, feature_slice, common["context"])
            obligations = getattr(plan, "coverage_obligations", [])
            suggestions = getattr(plan, "duplicate_suggestions", [])
            report = (
                validate_coverage(
                    obligations, plan.test_points, {f.id for f in feature_slice}, suggestions
                )
                if obligations or suggestions
                else CoverageReport()
            )
            incomplete = validate_boundary_contracts(
                obligations, plan.test_points, common["context"],
                feature_source_slots(feature_slice, common["context"]),
            )
            report = (
                validate_coverage(obligations, plan.test_points,
                                  {f.id for f in feature_slice}, suggestions,
                                  incomplete=incomplete)
                if obligations or suggestions else CoverageReport()
            )
            # Missing test setup is not an invitation to invent adjacent samples.
            fillable = {item.id for item in report.uncovered
                        if item.boundary_contract is None
                        or (item.boundary_contract.sampling_step is not None
                            and item.boundary_contract.sampling_literal)}
            completion_attempted = False
            if target_count is None and fillable and len(plan.test_points) < count:
                check_cancelled()
                completion_attempted = True
                # One bounded full response preserves the initial point snapshots. It
                # may append missing evidence-backed boundaries, never rewrite them.
                original_plan = plan

                def validate_completion(candidate):
                    schema_coverage_guard(validate_coverage_completion, original_plan, candidate,
                                          incomplete=incomplete)
                    return candidate

                completion_type = create_model(
                    "BatchTestPointPlan", __base__=plan_type,
                    __validators__={"validate_completion": model_validator(mode="after")(
                        validate_completion)},
                )
                filled = complete(
                    "test_point.generated",
                    TEST_POINT_DESIGN_INSTRUCTION
                    + "\n"
                    + COVERAGE_INSTRUCTION
                    + "\n只补coverage_gaps；保留existing_plan的所有原点、原ID和内容，完整返回。"
                    "最多batch_count点；不能补足则保留未覆盖义务。不得改写/删除原义务。"
                    "source_refs仅选source_catalog槽，身份ID为null。",
                    {
                        **{key: value for key, value in common.items() if not key.startswith("_")},
                        "source_catalog": payload_catalog(common["context"]),
                        "primary_bindings": bindings,
                        "boundary_evidence_bindings": boundary_bindings,
                        "feature_source_slots": feature_source_slots(
                            feature_slice, common["context"]
                        ),
                        "feature_points": {
                            "feature_points": [
                                f.model_dump(mode="json", exclude={"source_refs"})
                                for f in feature_slice
                            ]
                        },
                        "existing_plan": plan.model_dump(mode="json"),
                        "coverage_gaps": [
                            item.model_dump(mode="json") for item in report.uncovered if item.id in fillable
                        ],
                        "target_count": None,
                        "batch_count": count,
                        "batch_index": index + 1,
                        "coverage_completion": True,
                    },
                    completion_type,
                )
                validate_point_batch(filled, {f.id for f in feature_slice}, count)
                validate_coverage_completion(original_plan, filled, incomplete=incomplete)
                revised = getattr(filled, "coverage_obligations", [])
                plan, obligations = filled, revised
                suggestions = getattr(plan, "duplicate_suggestions", [])
                report = (
                    validate_coverage(
                        obligations, plan.test_points, {f.id for f in feature_slice}, suggestions
                    )
                    if obligations or suggestions
                    else CoverageReport()
                )
            incomplete = validate_boundary_contracts(
                obligations, plan.test_points, common["context"],
                feature_source_slots(feature_slice, common["context"]),
            )
            report = (
                validate_coverage(obligations, plan.test_points,
                                  {f.id for f in feature_slice}, suggestions,
                                  incomplete=incomplete)
                if obligations or suggestions else CoverageReport()
            )
            projected_boundary = project_boundary_metadata(plan.model_dump(mode="json"),
                                                           common["context"])
            # Canonical boundary projection happens after all model validation.
            boundary_points = {p["id"]: p for p in projected_boundary["test_points"]}
            obligations = [CoverageObligation.model_validate(item)
                           for item in projected_boundary.get("coverage_obligations", [])]
            # Keep the exact displayed catalog text. Canonical context validates
            # identity and textual provenance, never adds unseen citation content.
            plan = project_point_sources(
                plan,
                common["context"],
                canonical_context=common.get("_canonical_context", common["context"]),
            )
            for point in plan.test_points:
                samples = boundary_points[point.id].get("boundary_samples")
                if samples is not None:
                    point.boundary_samples = [BoundarySample.model_validate(v) for v in samples]
            id_map = {}
            feature_id_map = {
                f.id: f"FP-{uuid5(NAMESPACE_URL, f'{f.module}/{f.name}').hex[:16]}"
                for f in feature_slice
            }
            for ordinal, point in enumerate(plan.test_points):
                stable = f"TP-{index + 1}-{ordinal + 1}"
                id_map[point.id] = stable
                point.id = stable
            coverage_batches[index] = {
                "batch_index": index + 1,
                "obligations": [
                    {
                        **item.model_dump(mode="json"),
                        "point_ids": [id_map[p] for p in item.point_ids],
                        "feature_point_ids": [feature_id_map[f] for f in item.feature_point_ids],
                    }
                    for item in obligations
                ],
                "uncovered_ids": [item.id for item in report.uncovered],
                "clarifications": [item.clarification for item in report.clarifications],
                "duplicate_suggestions": [
                    {"point_ids": [id_map[p] for p in item.point_ids], "reason": item.reason}
                    for item in suggestions
                ],
                "completion_attempted": completion_attempted,
                "warnings": (["coverage_not_assessed"] if not obligations else [])
                + (["coverage_unverified"] if incomplete or report.clarifications else [])
                + (["boundary_semantics_requires_review"] if any(
                    item.boundary_contract is not None
                    and item.boundary_contract.quantity_axis_id is not None
                    for item in obligations
                ) else [])
                + (
                    [
                        "coverage_budget_limited"
                        if target_count is not None
                        else "coverage_gap_remaining"
                    ]
                    if report.uncovered
                    else []
                ),
            }
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
                    active[pool.submit(copy_context().run, worker, index)] = index
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
    result = merge_planning(features, points, context, len(batches))
    result["coverage_review"] = coverage_metadata()
    if target_count is not None and len(result["test_points"]) != target_count:
        raise ValueError("planning_final_point_count_mismatch")
    return result


def _scenario_required():
    raise ValueError("planning_point_scenario_required")


def _boundary_contract_required(metadata=None):
    error = ValueError("planning_boundary_contract_required")
    if metadata is not None:
        error.casepilot_safe_metadata = metadata
    raise error


def _boundary_binding_conflict(code="planning_boundary_binding_conflict"):
    raise ValueError(code)


def validate_coverage_completion(original, candidate, *, incomplete=()):
    """Keep the same strict snapshot guards in schema repair and outside providers."""
    old = {p.id: p.model_dump(mode="json") for p in original.test_points}
    new = {p.id: p.model_dump(mode="json") for p in candidate.test_points}
    if any(new.get(key) != value for key, value in old.items()):
        raise ValueError("planning_coverage_existing_point_changed")
    revised = {item.id: item for item in getattr(candidate, "coverage_obligations", [])}
    if any(item.id not in revised or item.model_dump(exclude={"point_ids"}) !=
           revised[item.id].model_dump(exclude={"point_ids"})
           for item in getattr(original, "coverage_obligations", [])):
        raise ValueError("planning_coverage_obligation_changed")
    validate_completion_ownership(original, candidate, incomplete=incomplete)


def validate_point_batch(plan, feature_ids, count, *, exact=False):
    if not plan.test_points or len(plan.test_points) > count or (exact and len(plan.test_points) != count):
        raise ValueError("planning_point_batch_size_invalid")
    if exact and len({(tuple(sorted(p.feature_point_ids)), p.scenario, p.title) for p in plan.test_points}) != len(plan.test_points):
        raise ValueError("planning_duplicate_test_point")
    covered = set()
    for point in plan.test_points:
        if not point.feature_point_ids or set(point.feature_point_ids) - feature_ids:
            raise ValueError("planning_feature_reference_invalid")
        covered.update(point.feature_point_ids)
    if covered != feature_ids:
        raise ValueError("planning_feature_uncovered:" + ",".join(sorted(feature_ids - covered)))


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
        canonical_evidence = {
            json.dumps(source, sort_keys=True): source
            for item in contributing
            for source in item.get("_canonical_context", item["context"]).get("evidence", [])
        }
        consolidated.append(
            (
                {
                    "requirement": local,
                    "context": {**context, "evidence": evidence},
                    "_canonical_context": {
                        **context,
                        "evidence": list(canonical_evidence.values()),
                    },
                },
                selected,
            )
        )
    return canonical, consolidated


def _stable_point_ids(features, points):
    feature_map = {
        f.id: f"FP-{uuid5(NAMESPACE_URL, f'{f.module}/{f.name}').hex[:16]}" for f in features
    }
    keys, objectives = {}, {}
    for point in points:
        key = "/".join(
            sorted({feature_map[ref] for ref in point.feature_point_ids})
            + [point.scenario, point.title]
        )
        if point.primary_feature_id is not None and len(set(point.feature_point_ids)) > 1:
            key = json.dumps([key, {"primary_feature_id": feature_map[point.primary_feature_id]}],
                             ensure_ascii=False)
        if point.boundary_samples:
            sample_keys = []
            for sample in point.boundary_samples:
                value = sample.model_dump(mode="json")
                value["assertion_feature_id"] = feature_map[sample.assertion_feature_id]
                sample_keys.append(value)
            key = json.dumps([key, sample_keys], sort_keys=True, ensure_ascii=False)
        keys[point.id] = key
        objectives.setdefault(key, set()).add(point.objective)
    result = {}
    for point in points:
        identity = keys[point.id]
        if len(objectives[identity]) > 1:
            identity = json.dumps([identity, point.objective], ensure_ascii=False)
        result[point.id] = f"TP-{uuid5(NAMESPACE_URL, identity).hex[:16]}"
    return result


def merge_planning(features, points, context, processed_batches):
    # Snapshot normalization must not mutate worker inputs or previous snapshots.
    features = [f.model_copy(deep=True) for f in features]
    points = [p.model_copy(deep=True) for p in points]
    # Adjacent evidence batches may describe the same business branch.
    # Merge exact semantic keys, retaining every source and rule description.
    stable_point_ids = _stable_point_ids(features, points)
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
        if point.primary_feature_id is not None:
            point.primary_feature_id = feature_map[point.primary_feature_id]
        point.feature_point_ids = list(
            dict.fromkeys(feature_map[ref] for ref in point.feature_point_ids)
        )
        for sample in point.boundary_samples or []:
            sample.assertion_feature_id = feature_map[sample.assertion_feature_id]
        point.id = stable_point_ids[point.id]
        if point.id in merged_points:
            current = merged_points[point.id]
            current.source_refs.extend(
                ref for ref in point.source_refs if ref not in current.source_refs
            )
            if point.boundary_samples:
                current.boundary_samples = current.boundary_samples or []
                current.boundary_samples.extend(
                    sample for sample in point.boundary_samples
                    if sample not in current.boundary_samples
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
    feature = (next(item for item in features if item.id == point.primary_feature_id)
               if point.primary_feature_id is not None
               else next(item for item in features if item.id in point.feature_point_ids))
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
