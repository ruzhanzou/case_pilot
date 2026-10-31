"""Bounded server-only tool diagnostics; never serialize arguments or exception text."""

from fastapi import HTTPException

REJECTION_CODES = frozenset(
    {
        "selection_version_conflict",
        "plan_required",
        "plan_authority_changed",
        "uploaded_preview_requires_selection",
        "one_proposal_per_turn",
        "workbench_plan_step_mismatch",
        "collection_proposal_requires_review",
        "agent_selection_requires_observed_sources",
        "duplicate_uploaded_source",
        "invalid_tool_arguments",
    }
)
HTTP_CODES = frozenset(
    {
        "workbench_selection_version_conflict",
        "workbench_selection_target_conflict",
        "workbench_source_changed",
        "workbench_run_authority_changed",
        "workbench_run_binding_changed",
        "workbench_run_source_changed",
        "workbench_legacy_scope_requires_reselection",
        "workbench_run_stopped",
        "workbench_run_authority_invalid",
        "collection_not_found",
        "collection_space_mismatch",
        "collection_impact_busy",
        "collection_impact_unresolved",
        "workbench_selection_changed",
        "workbench_destination_changed",
        "workbench_question_in_progress",
        "collection_proposal_stale",
    }
)
ACTIONS = frozenset(
    {
        "COLLECTION_CREATE",
        "COLLECTION_RENAME",
        "COLLECTION_DELETE",
        "COLLECTION_QUERY",
        "CASE_QUERY",
        "CASE_MODIFY",
        "CASE_DELETE",
        "CASE_GENERATE",
        "CASE_REUSE",
        "CASE_REVIEW",
        "CASE_DEDUP",
        "COVERAGE_ANALYZE",
        "KNOWLEDGE_QA",
    }
)
EXCEPTIONS = frozenset(
    {
        "HTTPException",
        "ValueError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "RuntimeError",
        "ValidationError",
        "OperationalError",
        "IntegrityError",
        "InvalidRequestError",
        "StatementError",
    }
)
COMPLETION_CODES = frozenset(
    {
        "goal_unverified",
        "goal_pending",
        "goal_satisfied",
        "review_required",
        "compute_pending",
        "dialogue_only",
        "tool_result_only",
        "failed",
        "cancelled",
    }
)
PHASES = frozenset({"handler", "result_type", "result_json"})


def safe_tool_diagnostic(value):
    """Idempotent field allowlist for runtime, event storage and QA consumers."""
    if not isinstance(value, dict):
        return {"diagnostic_unavailable": True}
    clean = {}
    for field, allowed in (
        ("rejection_code", REJECTION_CODES),
        ("http_detail_code", HTTP_CODES),
        ("exception_class", EXCEPTIONS),
    ):
        if field in value:
            item = value[field]
            clean[field] = (
                item
                if type(item) is str and item in allowed
                else ("unrecognized" if field == "exception_class" else "unknown")
            )
    for field, allowed in (
        ("phase", PHASES),
        ("plan_action", ACTIONS),
        ("completion_code", COMPLETION_CODES),
    ):
        if type(value.get(field)) is str and value[field] in allowed:
            clean[field] = value[field]
    for field, upper in (
        ("plan_cursor", 1000),
        ("canonical_count", 10000),
        ("canonical_version", 2147483647),
        ("argument_base_version", 2147483647),
        ("request_selection_version", 2147483647),
    ):
        item = value.get(field)
        if type(item) is int and 0 <= item <= upper:
            clean[field] = item
    for field in (
        "canonical_present",
        "plan_present",
        "diagnostic_unavailable",
        "goal_plan_valid",
        "goal_pending",
    ):
        if type(value.get(field)) is bool:
            clean[field] = value[field]
    status = value.get("http_status")
    if type(status) is int and 400 <= status <= 599:
        clean["http_status"] = status
    return clean


def failure_diagnostic(error, phase):
    value = {"phase": phase, "exception_class": type(error).__name__}
    if isinstance(error, HTTPException):
        value.update(http_status=error.status_code, http_detail_code=error.detail)
    return safe_tool_diagnostic(value)


def context_diagnostic(callback):
    if callback is None:
        return {}
    try:
        return safe_tool_diagnostic(callback())
    except Exception:
        return {"diagnostic_unavailable": True}
