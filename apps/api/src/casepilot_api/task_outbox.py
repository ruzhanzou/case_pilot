from uuid import UUID

from sqlalchemy.orm import Session

from casepilot_api.models import TaskOutbox


def enqueue_task(
    db: Session,
    task_name: str,
    args: list[str],
    *,
    task_id: str | UUID,
) -> None:
    """Record a task in the caller's transaction for reliable later delivery."""
    db.add(
        TaskOutbox(
            task_name=task_name,
            task_args=args,
            task_id=str(task_id),
        )
    )
