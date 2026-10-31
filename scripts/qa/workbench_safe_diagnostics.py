"""Allowlisted structured-failure summary; attached exception data is untrusted."""

import math
import re

_STAGES = frozenset({"requirement.analyzed", "requirement.extracted", "feature.extracted",
    "test_point.generated", "reuse.compared", "output_quantity.interpreted", "rewrite.batch",
    "test_case.generated", "test_case.grounded", "test_case.rewritten", "feature.generated",
    "reuse.objects_matched", "rewrite.evidence", "rewrite.constraints_validated",
    "enhancement.completed", "knowledge.answered"})
_SCHEMAS = frozenset({"SourceScopedPlanningAnalysis", "SourceScopedFeaturePlan",
    "PlanningAnalysis", "ReuseAnalysis", "RequirementAnalysis", "FeaturePlan",
    "BatchTestPointPlan", "TestPointPlan", "ScopedDecisions", "ReuseDecisions", "OutputQuantity",
    "RewritePatchBatch", "BoundedRewriteBatch", "GenerationResult", "TestCaseBatch",
    "EnhancementResult", "RewriteCandidate", "KnowledgeAnswer", "AssetObjectMatches"})
_CLASSES = frozenset({"ModelBehaviorError", "ValidationError", "JSONDecodeError",
    "ValueError", "TypeError", "OtherError"})
_TYPES = frozenset({"reuse_point_coverage_invalid", "reuse_source_action_invalid",
    "reuse_source_not_in_scope",
    "finite_number", "float_type", "greater_than",
    "none_required", "missing", "literal_error", "string_type", "list_type", "dict_type",
    "int_type", "bool_type", "extra_forbidden", "value_error", "json_invalid", "too_short",
    "too_long", "greater_than_equal", "less_than_equal", "union_tag_invalid",
    "other_validation_error"})
_COVERAGE_TYPES = frozenset({
    "planning_boundary_source_invalid",
    "planning_boundary_literal_invalid",
    "planning_boundary_threshold_invalid",
    "planning_boundary_relation_invalid",
    "planning_boundary_unit_invalid",
    "planning_boundary_axis_invalid",
    "planning_boundary_time_origin_invalid",
    "planning_boundary_sampling_invalid",
    "planning_boundary_sample_link_invalid",
    "planning_boundary_coordinate_invalid",
    "planning_boundary_assertion_owner_invalid",
    "planning_boundary_contract_required",
    "planning_boundary_binding_conflict",

    "planning_primary_binding_conflict",
    "planning_primary_binding_unavailable",
    "planning_coverage_completion_goal_invalid",
    "planning_coverage_completion_unlinked_point",
    "planning_coverage_completion_owner_invalid",
    "planning_primary_feature_invalid",
    "planning_primary_source_missing",
    "planning_point_sources_required",
    "planning_point_scenario_required",

    "planning_coverage_obligation_limit",
    "planning_coverage_point_id_duplicate",
    "planning_coverage_obligation_id_invalid",
    "planning_coverage_basis_invalid",
    "planning_coverage_feature_reference_invalid",
    "planning_coverage_point_reference_invalid",
    "planning_coverage_point_ownership_invalid",
    "planning_coverage_ambiguous_claim",
    "planning_duplicate_suggestion_invalid",
    "planning_coverage_existing_point_changed",
    "planning_coverage_obligation_changed",
})
_TYPES = _TYPES | _COVERAGE_TYPES
_COUNTS = frozenset({"expected_count", "actual_count", "missing_count", "extra_count",
                     "duplicate_count"})
_REUSE_ERRORS = frozenset({"reuse_point_coverage_invalid", "reuse_source_action_invalid",
                          "reuse_source_not_in_scope"})
_FIELDS = frozenset({
    "boundary_contract", "boundary_samples", "source_slot", "source_ref", "source_literal",
    "threshold", "unit", "comparator", "axis", "time_origin", "sampling_step",
    "sampling_literal", "obligation_id", "position", "value", "initial_state", "assertion",
    "assertion_role", "assertion_feature_id", "assertion_source_ref", "assertion_source_slot",
    "assertion_binding","primary_binding", "primary_feature_id", "coverage_obligations", "duplicate_suggestions", "basis", "dimension",
    "point_ids", "clarification", "locator", "source_id", "document_id", "chunk_id",
    "items", "test_points", "feature_points", "features", "id", "title",
    "description", "module", "priority", "steps", "action", "expected", "decisions",
    "point_id", "decision", "case_id", "source_ids", "source_refs", "feature_point_ids",
    "test_point_ids", "coverage_matrix", "risks", "assumptions", "open_questions",
    "quantity", "count", "total", "new_count", "reuse_count", "strategy", "reason",
    "confidence", "output_count", "requested_count", "target_count", "plan", "reuse"})


_METADATA_BOOLEANS = frozenset({
    "contract_present", "clarification_present", "source_in_catalog", "source_allowed",
    "literal_matches", "threshold_matches", "unit_matches", "axis_matches",
    "time_origin_matches", "sampling_matches",
})


def safe_coverage_metadata(value):
    """Copy only bounded structural evidence, never arbitrary model strings.

    This is deliberately not a general-purpose serializer. In particular source
    literals, axis/unit text, IDs and exception messages must never be retained.
    """
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key in _METADATA_BOOLEANS and type(item) is bool:
            result[key] = item
        elif key in {"obligation_index", "point_count", "batch_index", "attempt"}:
            limit = 47 if key == "obligation_index" else 10000
            if type(item) is int and 0 <= item <= limit:
                result[key] = item
        elif (
            key == "dimension" and type(item) is str
            and item in {"normal", "boundary", "exception", "state"}
        ) or (
            key == "source_slot" and type(item) is str
            and re.fullmatch(r"source:(?:0|[1-9][0-9]{0,3})", item)
        ) or (
            key in {"threshold", "sampling_step"} and type(item) in {int, float}
            and -1e12 <= item <= 1e12 and math.isfinite(item)
        ):
            result[key] = item
    return result


def safe_structured_failure(error):
    if type(error).__name__ != "ModelBehaviorError":
        return None
    value = getattr(error, "casepilot_safe_diagnostic", None)
    if not isinstance(value, dict):
        return None

    def label(item, allowed, fallback):
        return item if isinstance(item, str) and item in allowed else fallback

    chain = value.get("exception_chain")
    errors = value.get("validation_errors")
    result = {
        "stage": label(value.get("stage"), _STAGES, "unrecognized"),
        "schema": label(value.get("schema"), _SCHEMAS, "unrecognized"),
        "exception_chain": [label(item, _CLASSES, "OtherError")
                            for item in chain[:5]] if isinstance(chain, list) else [],
        "validation_errors": [],
    }
    for item in errors[:12] if isinstance(errors, list) else []:
        if not isinstance(item, dict):
            continue
        loc = item.get("loc")
        raw_counts = item.get("counts")
        counts = ({key: value for key, value in raw_counts.items()
                   if key in _COUNTS and type(value) is int and 0 <= value <= 10000}
                  if isinstance(raw_counts, dict) and isinstance(item.get("type"), str)
                  and item["type"] in _REUSE_ERRORS else {})
        metadata = (safe_coverage_metadata(item.get("metadata"))
                    if isinstance(item.get("type"), str)
                    and item["type"] in _COVERAGE_TYPES else {})
        result["validation_errors"].append({
            **({"metadata": metadata} if metadata else {}),
            **({"counts": counts} if counts else {}),
            "type": label(item.get("type"), _TYPES, "other_validation_error"),
            "loc": [part if type(part) is int and 0 <= part <= 10000 else
                    label(part, _FIELDS, "unknown_field")
                    for part in loc[:8]] if isinstance(loc, (list, tuple)) else [],
        })
    return result
