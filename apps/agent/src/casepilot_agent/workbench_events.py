"""SQL-only durable domain completion hook; no dependency on the API image."""
import json
from uuid import uuid4

from sqlalchemy import text

CONTINUATION_TASK = "casepilot.workbench.continue"


def emit_job_completion(connection, job):
    payload = dict(job.get("input_payload") or {})
    run_id = payload.get("workbench_run_id")
    status = str(getattr(job["status"], "value", job["status"]))
    if not run_id or status not in {"completed", "failed", "cancelled", "awaiting_input"}:
        return None
    # All inputs originate in the server dispatcher. Match the current wait,
    # cursor and epoch; late worker output may not revive an obsolete plan.
    run = connection.execute(text("""
        SELECT id, epoch, cursor, status, cancelled_at, checkpoint
        FROM workbench_runs WHERE id = CAST(:run_id AS uuid) FOR UPDATE
    """), {"run_id": str(run_id)}).mappings().one_or_none()
    if (run is None or run["cancelled_at"] is not None
            or run["status"] in {"completed", "failed", "cancelled",
                                 "invalidated", "budget_exhausted"}
            or run["epoch"] != payload.get("workbench_epoch")
            or run["cursor"] != payload.get("workbench_cursor")
            or str((run["checkpoint"] or {}).get("waiting_job_id")) != str(job["id"])):
        return None
    event_id = str(uuid4())
    source_version = f"{status}:{payload.get('task_revision', 1)}"
    inserted = connection.execute(text("""
        INSERT INTO workbench_continuations
        (id, run_id, event_kind, source_id, source_version, status, expected_epoch,
         cursor, payload, receipt, attempts, created_at)
        VALUES (CAST(:id AS uuid), CAST(:run_id AS uuid), 'job_completed', :source_id,
                :version, 'pending', :epoch, :cursor, CAST(:payload AS jsonb), '{}', 0, now())
        ON CONFLICT ON CONSTRAINT uq_workbench_continuation_source DO NOTHING RETURNING id
    """), {"id": event_id, "run_id": str(run_id), "source_id": str(job["id"]),
           "version": source_version, "epoch": run["epoch"], "cursor": run["cursor"],
           "payload": json.dumps({"job_id": str(job["id"]), "status": status,
                                  "operation": job["operation"]})}).scalar_one_or_none()
    if inserted is None:
        return None
    connection.execute(text("""
        INSERT INTO task_outbox
        (id, task_name, task_args, task_id, status, attempts, available_at, created_at)
        VALUES (CAST(:id AS uuid), :name, CAST(:args AS jsonb), :task_id,
                'pending', 0, now(), now())
    """), {"id": str(uuid4()), "name": CONTINUATION_TASK,
           "args": json.dumps([event_id]), "task_id": event_id})
    return event_id
