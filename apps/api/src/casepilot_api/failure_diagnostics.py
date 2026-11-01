"""Content-free failure locations and opaque request correlation, never exception text."""
import re
import traceback
from contextvars import ContextVar
from pathlib import Path
from uuid import UUID

failure_context: ContextVar[dict | None] = ContextVar("failure_context", default=None)
CLASSES = frozenset({
    "RuntimeError", "ValueError", "TypeError", "KeyError", "AttributeError",
    "UnboundLocalError", "AssertionError", "ValidationError", "ResponseValidationError",
    "IntegrityError", "OperationalError", "ProgrammingError", "DataError",
    "InvalidRequestError", "PendingRollbackError", "TimeoutError",
})


def correlate_failure(**values):
    context = failure_context.get()
    if context is None:
        return
    for key in ("client_request_id", "conversation_id", "turn_id", "run_id"):
        value = values.get(key)
        if isinstance(value, UUID):
            context[key] = str(value)


def failure_diagnostic(error, correlation):
    root = Path(__file__).parent.resolve()
    frames = []
    for frame in traceback.extract_tb(error.__traceback__):
        try:
            file = Path(frame.filename).resolve().relative_to(root)
        except ValueError:
            continue
        if (all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in file.parts)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", frame.name)):
            frames.append({"file": str(file), "line": frame.lineno, "function": frame.name})
    identifiers = {}
    for key in ("request_id", "client_request_id", "conversation_id", "turn_id", "run_id"):
        try:
            identifiers[key] = str(UUID(str(correlation[key])))
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return {"phase": "api_request", "error_code": "internal_error",
            "exception_class": type(error).__name__ if type(error).__name__ in CLASSES
            else "unrecognized", "frames": frames[-12:], **identifiers}
