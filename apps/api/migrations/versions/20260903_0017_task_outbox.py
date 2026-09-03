"""Add a transactional outbox for Celery task delivery.

Revision ID: 20260903_0017
Revises: 20260902_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260903_0017"
down_revision: str | Sequence[str] | None = "20260902_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_name", sa.String(length=160), nullable=False),
        sa.Column("task_args", postgresql.JSONB(), nullable=False),
        sa.Column("task_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=240)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_outbox_status", "task_outbox", ["status"])
    op.create_index("ix_task_outbox_available_at", "task_outbox", ["available_at"])
    op.create_index("ix_task_outbox_task_id", "task_outbox", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_outbox_task_id", table_name="task_outbox")
    op.drop_index("ix_task_outbox_available_at", table_name="task_outbox")
    op.drop_index("ix_task_outbox_status", table_name="task_outbox")
    op.drop_table("task_outbox")
