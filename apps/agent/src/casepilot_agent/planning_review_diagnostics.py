"""Fixed diagnostics only: no exception text, input, context or arbitrary field names."""

from contextlib import contextmanager, suppress
from contextvars import ContextVar
from copy import deepcopy

from pydantic import ValidationError

PHASES = frozenset(
    {
        "claim",
        "provider_setup",
        "provider_call",
        "schema_validation",
        "reference_validation",
        "revision_validation",
        "completion_revalidation",
        "result_serialization",
        "result_persistence",
        "failure_persistence",
    }
)
CODES = frozenset(
    {
        "planning_review_input_limit",
        "planning_review_duplicate_issue",
        "planning_review_reference_invalid",
        "planning_review_source_invalid",
        "planning_review_span_invalid",
        "planning_review_span_collision",
        "planning_review_selection_invalid",
        "planning_review_budget_or_state",
        "planning_review_authority_changed",
        "planning_review_source_changed",
        "planning_review_version_changed",
        "planning_revision_duplicate_edit",
        "planning_revision_scope_invalid",
        "planning_revision_new_id_invalid",
        "planning_revision_content_invalid",
        "planning_revision_primary_source_invalid",
        "planning_revision_sample_owner_invalid",
        "planning_revision_dangling_reference",
        "planning_revision_sample_link_invalid",
        "planning_coverage_obligation_limit",
        "planning_coverage_point_id_duplicate",
        "planning_coverage_obligation_id_invalid",
        "planning_coverage_basis_invalid",
        "planning_coverage_feature_reference_invalid",
        "planning_coverage_point_reference_invalid",
        "planning_coverage_point_ownership_invalid",
        "planning_coverage_ambiguous_claim",
        "planning_duplicate_suggestion_invalid",
    }
)
CLASSES = frozenset(
    {
        "ContractError",
        "ValidationError",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "RuntimeError",
        "HTTPException",
        "ModelBehaviorError",
        "JSONDecodeError",
        "APITimeoutError",
        "APIConnectionError",
        "APIStatusError",
        "RateLimitError",
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "InternalServerError",
        "IntegrityError",
        "OperationalError",
        "StatementError",
        "DataError",
        "PendingRollbackError",
        "ProgrammingError",
    }
)
TYPES = frozenset(
    {
        "missing",
        "literal_error",
        "string_type",
        "list_type",
        "dict_type",
        "int_type",
        "int_parsing",
        "bool_type",
        "none_required",
        "extra_forbidden",
        "value_error",
        "json_invalid",
        "too_short",
        "too_long",
        "string_too_short",
        "string_too_long",
        "greater_than_equal",
        "less_than_equal",
        "string_pattern_mismatch",
        "model_type",
        "model_attributes_type",
        "union_tag_invalid",
        "union_tag_not_found",
    }
)


class ContractError(ValueError):
    def __init__(self, code, path=(), *, path_complete=True):
        super().__init__(code)
        self.code, self.path, self.path_complete = code, tuple(path), path_complete


def _fields():
    from casepilot_agent.contracts import TestPoint
    from casepilot_agent.planning_coverage import CoverageObligation
    from casepilot_agent.planning_review import Review, ReviewSelection, Revision

    fields = {
        "planning",
        "selected",
        "coverage_review",
        "batches",
        "obligations",
        "test_points",
        "boundary_samples",
    }

    def visit(value):
        if isinstance(value, dict):
            fields.update(value.get("properties", {}))
            fields.update(value.get("$defs", {}))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for schema in (Review, ReviewSelection, Revision, TestPoint, CoverageObligation):
        fields.add(schema.__name__)
        visit(schema.model_json_schema())
    return fields


def diagnostic(error, phase):
    allowed = _fields()

    def path(parts):
        valid = all(
            type(p) is int and 0 <= p <= 10000 or type(p) is str and p in allowed for p in parts
        )
        # Preserve path depth, never print an unknown extra key (it may itself be a secret).
        return [
            p
            if type(p) is int and 0 <= p <= 10000 or type(p) is str and p in allowed
            else "unknown_field"
            for p in parts
        ], valid

    phase = phase if phase in PHASES else "unrecognized"
    result = {
        "phase": phase,
        "code": "planning_review_unclassified_failure",
        "exception_chain": [],
        "errors": [],
        "errors_complete": True,
    }
    current, seen = error, set()
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        name = type(current).__name__
        result["exception_chain"].append(name if name in CLASSES else "unrecognized")
        args = current.args
        code = args[0] if len(args) == 1 and type(args[0]) is str and args[0] in CODES else None
        detail = getattr(current, "detail", None)
        if name == "HTTPException" and type(detail) is str and detail in CODES:
            code = detail
        if isinstance(current, ContractError):
            code = current.code if current.code in CODES else None
            loc, complete = path(current.path)
            result["errors"].append(
                {
                    "code": code or "unrecognized",
                    "path": loc,
                    "path_complete": complete and current.path_complete,
                }
            )
        if code and result["code"] == "planning_review_unclassified_failure":
            result["code"] = code
        if isinstance(current, ValidationError):
            if result["code"] == "planning_review_unclassified_failure":
                result["code"] = "planning_review_schema_invalid"
            prefix = getattr(current, "planning_review_path", ())
            for item in current.errors(
                include_input=False, include_context=False, include_url=False
            ):
                loc, complete = path((*prefix, *item["loc"]))
                result["errors"].append(
                    {
                        "code": item["type"] if item["type"] in TYPES else "unrecognized",
                        "path": loc,
                        "path_complete": complete
                        and getattr(current, "planning_review_path_complete", True),
                    }
                )
        current = current.__cause__ or current.__context__
    if current is not None:
        result["chain_complete"] = False
    if len(result["errors"]) > 64:
        result["errors_complete"] = False
        result["errors"] = result["errors"][:64]
    if result["code"] == "planning_review_unclassified_failure":
        result["code"] = {
            "provider_call": "planning_review_provider_failed",
            "result_persistence": "planning_review_persistence_failed",
            "failure_persistence": "planning_review_failure_record_unavailable",
            "result_serialization": "planning_review_serialization_failed",
        }.get(phase, "planning_review_implementation_or_unclassified_failure")
    return result


_observer = ContextVar("planning_review_diagnostic_observer", default=None)


@contextmanager
def observe_failures(callback):
    """Optional local observer, no default logging or telemetry; context-local."""
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


def notify(value):
    callback = _observer.get()
    if callback is not None:
        with suppress(Exception):
            callback(deepcopy(value))
