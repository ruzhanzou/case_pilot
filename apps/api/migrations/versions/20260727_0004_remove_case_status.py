"""remove execution status from test case assets

Revision ID: 20260727_0004
Revises: 20260727_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0004"
down_revision: str | None = "20260727_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

case_status = postgresql.ENUM(
    "pending",
    "passed",
    "failed",
    "skipped",
    "blocked",
    name="case_status",
    create_type=False,
)


def upgrade() -> None:
    op.drop_table("test_case_status_events")
    op.drop_index("ix_test_cases_current_status", table_name="test_cases")
    op.drop_column("test_cases", "current_status")
    case_status.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    case_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "test_cases",
        sa.Column(
            "current_status",
            case_status,
            nullable=False,
            server_default="pending",
        ),
    )
    op.create_index(
        "ix_test_cases_current_status",
        "test_cases",
        ["current_status"],
    )
    op.create_table(
        "test_case_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_case_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", case_status),
        sa.Column("to_status", case_status, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_test_case_status_events_test_case_id",
        "test_case_status_events",
        ["test_case_id"],
    )
