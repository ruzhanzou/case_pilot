"""Worker failure locations, correlated by job UUID, without exception values."""
import re
import traceback
from pathlib import Path
from uuid import UUID

CLASSES = frozenset({
    "RuntimeError", "ValueError", "TypeError", "KeyError", "AttributeError",
    "UnboundLocalError", "AssertionError", "ValidationError", "IntegrityError",
    "OperationalError", "ProgrammingError", "DataError", "InvalidRequestError",
    "PendingRollbackError", "TimeoutError", "WorkerInterrupted",
})
PHASES = {"brief.failed": "brief", "generation.failed": "generation",
          "rewrite.failed": "rewrite", "qa.failed": "qa"}


def worker_failure(error, event_name, job_id):
    frames = []
    root = Path(__file__).parent.resolve()
    for frame in traceback.extract_tb(error.__traceback__):
        try:
            file = Path(frame.filename).resolve().relative_to(root)
        except ValueError:
            continue
        if (all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in file.parts)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", frame.name)):
            frames.append({"file": str(file), "line": frame.lineno, "function": frame.name})
    return {"phase": PHASES.get(event_name, "unknown"), "error_code": "domain_job_failed",
            "exception_class": type(error).__name__ if type(error).__name__ in CLASSES
            else "unrecognized", "frames": frames[-12:],
            **({"job_id": str(job_id)} if isinstance(job_id, UUID) else {})}
