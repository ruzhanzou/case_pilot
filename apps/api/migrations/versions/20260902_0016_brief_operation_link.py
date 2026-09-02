"""Link test briefs to their source conversation operation.

Revision ID: 20260902_0016
Revises: 20260901_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0016"
down_revision: str | Sequence[str] | None = "20260901_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_test_briefs",
        sa.Column("source_operation_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "workspace_test_briefs_source_operation_id_fkey",
        "workspace_test_briefs",
        "conversation_operations",
        ["source_operation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workspace_test_briefs_source_operation_id",
        "workspace_test_briefs",
        ["source_operation_id"],
    )
    op.execute(
        """
        UPDATE workspace_test_briefs AS brief
        SET source_operation_id = (
            SELECT operation.id AS operation_id
            FROM conversation_messages AS message
            JOIN conversation_operations AS operation
              ON operation.related_job_id = message.related_job_id
            WHERE message.conversation_id = brief.conversation_id
              AND message.role = 'assistant'
              AND message.metadata->>'brief_version' = brief.version::text
            ORDER BY message.created_at DESC
            LIMIT 1
        )
        WHERE brief.source_operation_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_test_briefs_source_operation_id",
        table_name="workspace_test_briefs",
    )
    op.drop_constraint(
        "workspace_test_briefs_source_operation_id_fkey",
        "workspace_test_briefs",
        type_="foreignkey",
    )
    op.drop_column("workspace_test_briefs", "source_operation_id")
