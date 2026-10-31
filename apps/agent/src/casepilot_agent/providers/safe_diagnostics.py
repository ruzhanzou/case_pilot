"""Allowlisted schema diagnostics. Never retain raw error text, inputs or context."""
import math
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar

from pydantic import ValidationError

from casepilot_agent.planning_coverage import COVERAGE_VALIDATION_CODES

_TYPES = frozenset({"reuse_point_coverage_invalid", "reuse_source_action_invalid",
    "reuse_source_not_in_scope",
    "finite_number", "float_type", "greater_than",
    "missing", "literal_error", "string_type", "list_type", "dict_type",
    "int_type", "bool_type", "none_required", "extra_forbidden", "value_error", "json_invalid",
    "too_short", "string_too_short", "string_too_long",
    "too_long", "greater_than_equal", "less_than_equal", "union_tag_invalid"})
_TYPES = _TYPES | COVERAGE_VALIDATION_CODES
_FIELDS = frozenset({"items", "test_points", "feature_points", "features", "id", "title",
    "description", "module", "priority", "steps", "action", "expected", "decisions",
    "point_id", "decision", "case_id", "source_ids", "source_refs", "feature_point_ids",
    "test_point_ids", "coverage_matrix", "risks", "assumptions", "open_questions",
    "quantity", "count", "total", "new_count", "reuse_count", "strategy", "reason",
    "locator", "source_id", "document_id", "chunk_id",
    "coverage_obligations", "duplicate_suggestions", "point_ids",
    "boundary_contract", "boundary_samples", "source_slot", "source_literal", "source_ref",
    "threshold", "unit", "comparator", "axis", "time_origin", "sampling_step", "sampling_literal",
    "obligation_id", "position", "value", "initial_state", "assertion", "assertion_role",
    "assertion_binding", "assertion_feature_id", "assertion_source_slot", "assertion_source_ref",
    "dimension", "basis", "clarification", "primary_feature_id", "primary_binding", "scenario",
    "confidence", "output_count", "requested_count", "target_count", "plan", "reuse"})
_COUNTS = frozenset({"expected_count", "actual_count", "missing_count", "extra_count",
                     "duplicate_count"})
_REUSE_ERRORS = frozenset({"reuse_point_coverage_invalid", "reuse_source_action_invalid",
                          "reuse_source_not_in_scope"})
_CLASSES = frozenset({"ModelBehaviorError", "ValidationError", "JSONDecodeError",
                     "ValueError", "TypeError"})


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


def structured_failure(error, *, stage, result_type):
    def label(value):
        valid = isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,79}", value)
        return value if valid else "unrecognized"
    diagnostic = {"stage": label(stage), "schema": label(result_type.__name__),
                  "exception_chain": [], "validation_errors": []}
    seen = set()
    current = error
    while current is not None and id(current) not in seen and len(seen) < 5:
        seen.add(id(current))
        name = type(current).__name__
        diagnostic["exception_chain"].append(name if name in _CLASSES else "OtherError")
        if isinstance(current, ValidationError):
            errors = current.errors(include_url=False, include_context=True, include_input=False)
            for item in errors[:12]:
                context = item.get("ctx")
                counts = ({key: value for key, value in context.items()
                           if key in _COUNTS and type(value) is int and 0 <= value <= 10000}
                          if isinstance(context, dict) and item["type"] in _REUSE_ERRORS else {})
                metadata = (safe_coverage_metadata(context.get("metadata"))
                            if isinstance(context, dict)
                            and item["type"] in COVERAGE_VALIDATION_CODES else {})
                diagnostic["validation_errors"].append({
                    **({"metadata": metadata} if metadata else {}),
                    "type": item["type"] if item["type"] in _TYPES else "other_validation_error",
                    **({"counts": counts} if counts else {}),
                    "loc": [part if type(part) is int and 0 <= part <= 10000
                            else part if isinstance(part, str) and part in _FIELDS
                            else "unknown_field"
                            for part in item.get("loc", ())[:8]],
                })
        current = current.__cause__ or current.__context__
    return diagnostic


_observer: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "casepilot_structured_failure_observer", default=None)


@contextmanager
def observe_structured_failures(observer: Callable[[dict], None] | None) -> Iterator[None]:
    """Opt-in, context-local diagnostics; callers own flushing/persistence.

    Context propagates through asyncio.to_thread/copy_context, not unrelated
    threads or processes. Nested scopes restore the previous observer exactly.
    """
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def notify_structured_failure(error, *, stage, result_type) -> None:
    """Emit only safe shape metadata; diagnostics must never alter provider flow."""
    observer = _observer.get()
    if observer is None:
        return
    # Do not log callback exceptions: they may include caller-private data.
    with suppress(Exception):
        observer(structured_failure(error, stage=stage, result_type=result_type))
