"""Fixed continuation failure metadata; no exception text, arguments or SQL."""
import traceback
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from casepilot_api.workbench_tool_diagnostics import EXCEPTIONS, HTTP_CODES

CODES = frozenset({
    "invalid_approval_continuation", "unbound_workbench_observation",
    "unbound_workbench_job", "nonterminal_workbench_job",
})
PHASES = frozenset({"claim", "observe", "restore", "reserve", "segment", "commit"})
FIELDS = frozenset({
    "kind", "message", "effect", "receipt_ids", "steps", "action", "status",
    "cursor", "plan", "binding", "epoch", "source_version", "event_kind",
    "source_id", "run_id", "checkpoint", "tool_calls", "arguments", "name",
})
TYPES = frozenset({"missing", "literal_error", "extra_forbidden", "value_error",
                   "string_type", "int_type", "list_type", "dict_type", "model_type"})


def continuation_failure(error, phase):
    result = {
        "error_code": "workbench_continuation_failed",
        "phase": phase if phase in PHASES else "unknown",
        "exception_class": type(error).__name__ if type(error).__name__ in EXCEPTIONS
        else "unrecognized",
    }
    if isinstance(error, HTTPException):
        result["domain_code"] = (error.detail
                                 if type(error.detail) is str and error.detail in HTTP_CODES
                                 else "unknown")
        if type(error.status_code) is int and 400 <= error.status_code <= 599:
            result["http_status"] = error.status_code
    elif type(error) is ValueError and len(error.args) == 1:
        result["domain_code"] = (error.args[0]
                                 if type(error.args[0]) is str and error.args[0] in CODES
                                 else "unknown")
    if isinstance(error, ValidationError):
        result["validation_errors"] = [{
            "type": item["type"] if item["type"] in TYPES else "unknown",
            "path": [part if (type(part) is str and part in FIELDS)
                     or (type(part) is int and 0 <= part <= 10000) else "unknown"
                     for part in item["loc"][:16]],
        } for item in error.errors(
            include_input=False, include_context=False, include_url=False)[:16]]
    result["frames"] = [{"file": Path(frame.filename).name, "function": frame.name,
                         "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)
                        if "/casepilot_api/" in frame.filename][-6:]
    return result
