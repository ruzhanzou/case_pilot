"""Bounded server-only tool diagnostics; never serialize arguments or exception text."""

from fastapi import HTTPException
from pydantic import ValidationError

REJECTION_CODES = frozenset(
    {
        "skill_version_changed",
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
        "reference_context_changed",
        "skill_version_changed",
        "reference_source_unavailable",
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
        "read_result_only",
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
    if isinstance(value.get("argument_errors"), list):
        clean["argument_errors"] = safe_argument_errors(value["argument_errors"])
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


_ARGUMENT_FIELDS = frozenset({
    "plan", "steps", "plan_actions", "strategy", "sources", "ref", "version",
    "base_version", "collection_id", "active_collection_id", "selection_policy",
    "search", "scope", "limit", "offset", "name", "skill", "skill_id", "skill_version",
    "query", "document_ids", "source_ids", "source_id", "mode", "operation",
})
_ARGUMENT_TYPES = frozenset({
    "missing", "extra_forbidden", "literal_error", "value_error", "json_invalid",
    "string_type", "list_type", "dict_type", "int_type", "int_parsing", "bool_type",
    "too_short", "too_long", "greater_than_equal", "less_than_equal", "uuid_parsing",
    "string_too_short", "string_too_long", "model_type",
})


def safe_argument_errors(items):
    clean = []
    for item in items[:12] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        loc = item.get("loc")
        value = {"type": item.get("type") if type(item.get("type")) is str
                 and item["type"] in _ARGUMENT_TYPES
                 else "unknown", "loc": [
                     part if type(part) is int and 0 <= part <= 10000 else
                     part if type(part) is str and part in _ARGUMENT_FIELDS else "unknown_field"
                     for part in loc[:12]] if isinstance(loc, (list, tuple)) else []}
        if item.get("code") == "workbench_plan_step_count_mismatch":
            value["code"] = "workbench_plan_step_count_mismatch"
        clean.append(value)
    return clean


def argument_diagnostic(error):
    if not isinstance(error, ValidationError):
        return []
    values = []
    for item in error.errors(include_input=False, include_context=True, include_url=False)[:12]:
        cause = (item.get("ctx") or {}).get("error")
        args = cause.args if type(cause) is ValueError else ()
        code = ("workbench_plan_step_count_mismatch" if args ==
                ("workbench_plan_step_count_mismatch",) else None)
        values.append({"type": item["type"], "loc": item["loc"], "code": code})
    return safe_argument_errors(values)
