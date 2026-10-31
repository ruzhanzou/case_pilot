"""Fail closed at terminal run states before QA sends another human confirmation."""
import re

TERMINAL_FAILURE = frozenset({"failed", "cancelled", "invalidated", "budget_exhausted"})
CODES = frozenset({"workbench_continuation_failed", "agent_final_receipt_invalid",
                   "agent_tool_failed", "workbench_scope_requires_selection",
                   "budget_exhausted", "workbench_run_binding_changed"})
PHASES = frozenset({"claim", "observe", "restore", "reserve", "segment", "commit"})
EXCEPTIONS = frozenset({"ValueError", "TypeError", "ValidationError", "HTTPException",
                        "RuntimeError", "IntegrityError", "OperationalError",
                        "InvalidRequestError", "StatementError", "KeyError", "AttributeError"})


def safe_failure(value):
    value = value if isinstance(value, dict) else {}
    code = value.get("error_code")
    result = {"error_code": code if type(code) is str and code in CODES else "unknown"}
    if "domain_code" in value:
        domain_codes = {"invalid_approval_continuation", "unbound_workbench_observation",
                        "unbound_workbench_job", "nonterminal_workbench_job",
                        "workbench_run_binding_changed", "workbench_selection_changed",
                        "reference_context_changed", "skill_version_changed"}
        code = value["domain_code"]
        result["domain_code"] = code if type(code) is str and code in domain_codes else "unknown"
    for field, allowed in [("phase", PHASES), ("exception_class", EXCEPTIONS)]:
        item = value.get(field)
        result[field] = item if type(item) is str and item in allowed else "unknown"
    frames = []
    rows = value.get("frames", [])
    for row in rows[:6] if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if (type(row.get("file")) is str
                and re.fullmatch(r"[a-z_]+\.py", row["file"])
                and type(row.get("function")) is str
                and re.fullmatch(r"[a-z_]{1,80}", row["function"])
                and type(row.get("line")) is int and 0 < row["line"] < 100000):
            frames.append({k: row[k] for k in ("file", "function", "line")})
    result["frames"] = frames
    fields = {"kind", "message", "effect", "receipt_ids", "steps", "action", "status",
              "cursor", "plan", "binding", "epoch", "source_version", "event_kind",
              "source_id", "run_id", "checkpoint", "tool_calls", "arguments", "name"}
    types = {"missing", "literal_error", "extra_forbidden", "value_error", "string_type",
             "int_type", "list_type", "dict_type", "model_type"}
    errors = value.get("validation_errors")
    if isinstance(errors, list):
        result["validation_errors"] = [{
            "type": row.get("type") if type(row.get("type")) is str
            and row["type"] in types else "unknown",
            "path": [part if (type(part) is str and part in fields)
                     or (type(part) is int and 0 <= part <= 10000) else "unknown"
                     for part in row["path"][:16]],
        } for row in errors[:16] if isinstance(row, dict) and isinstance(row.get("path"), list)]
    return result


def require_live_run(state, report, stage):
    """The caller already verifies exact run/root/epoch ownership before this gate."""
    if state.get("status") not in TERMINAL_FAILURE:
        return
    report["terminal_failure"] = {
        "status": state["status"],
        "stage": stage,
        "diagnostic": safe_failure(state.get("failure_diagnostic", {})),
    }
    raise AssertionError("durable_run_terminal_failure")
