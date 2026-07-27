"""Add persisted case management and execution records.

Revision ID: 20260726_0002
Revises: 20260723_0001
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0002"
down_revision: str | Sequence[str] | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

execution_status = postgresql.ENUM(
    "not_run",
    "passed",
    "failed",
    "skipped",
    "blocked",
    name="execution_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    execution_status.create(bind, checkfirst=True)

    op.add_column(
        "case_collections",
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )

    op.add_column("test_cases", sa.Column("case_key", sa.String(length=40)))
    op.execute(
        """
        UPDATE test_cases
        SET case_key = 'CASE-' || upper(substr(replace(id::text, '-', ''), 1, 8))
        WHERE case_key IS NULL
        """
    )
    op.alter_column("test_cases", "case_key", nullable=False)
    op.add_column(
        "test_cases",
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_unique_constraint(
        "uq_test_case_space_key",
        "test_cases",
        ["space_id", "case_key"],
    )
    op.create_foreign_key(
        "fk_test_cases_current_revision",
        "test_cases",
        "test_case_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "test_case_revisions",
        sa.Column(
            "module",
            sa.String(length=160),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "test_case_revisions",
        sa.Column(
            "priority",
            sa.String(length=8),
            nullable=False,
            server_default="P1",
        ),
    )
    op.add_column(
        "test_case_revisions",
        sa.Column(
            "case_type",
            sa.String(length=40),
            nullable=False,
            server_default="功能",
        ),
    )
    op.add_column(
        "test_case_revisions",
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_table(
        "collection_case_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "collection_id",
            "test_case_id",
            name="uq_collection_case_membership",
        ),
    )
    op.create_index(
        "ix_collection_case_memberships_collection_id",
        "collection_case_memberships",
        ["collection_id"],
    )
    op.create_index(
        "ix_collection_case_memberships_test_case_id",
        "collection_case_memberships",
        ["test_case_id"],
    )

    op.create_table(
        "execution_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_collections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "executor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_runs_space_id", "execution_runs", ["space_id"])
    op.create_index(
        "ix_execution_runs_collection_id",
        "execution_runs",
        ["collection_id"],
    )
    op.create_index(
        "ix_execution_runs_executor_id",
        "execution_runs",
        ["executor_id"],
    )

    op.create_table(
        "execution_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_case_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            execution_status,
            nullable=False,
            server_default="not_run",
        ),
        sa.Column(
            "completed_step_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("actual_result", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "defect_ref",
            sa.String(length=160),
            nullable=False,
            server_default="",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "test_case_id", name="uq_execution_run_case"),
    )
    op.create_index("ix_execution_records_run_id", "execution_records", ["run_id"])
    op.create_index(
        "ix_execution_records_test_case_id",
        "execution_records",
        ["test_case_id"],
    )
    op.create_index(
        "ix_execution_records_status",
        "execution_records",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("execution_records")
    op.drop_table("execution_runs")
    op.drop_table("collection_case_memberships")
    op.drop_constraint(
        "fk_test_cases_current_revision",
        "test_cases",
        type_="foreignkey",
    )
    op.drop_constraint("uq_test_case_space_key", "test_cases", type_="unique")
    op.drop_column("test_case_revisions", "tags")
    op.drop_column("test_case_revisions", "case_type")
    op.drop_column("test_case_revisions", "priority")
    op.drop_column("test_case_revisions", "module")
    op.drop_column("test_cases", "deleted_at")
    op.drop_column("test_cases", "case_key")
    op.drop_column("case_collections", "deleted_at")
    bind = op.get_bind()
    execution_status.drop(bind, checkfirst=True)
