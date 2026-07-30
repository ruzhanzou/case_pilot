"""Add collection workspaces, versioned briefs, candidates, and assignees.

Revision ID: 20260729_0011
Revises: 20260729_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0011"
down_revision: str | Sequence[str] | None = "20260729_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY collection_id
                       ORDER BY updated_at DESC, created_at DESC, id DESC
                   ) AS workspace_rank
            FROM conversations
            WHERE status = 'active'
        )
        UPDATE conversations
        SET status = 'archived'
        FROM ranked
        WHERE conversations.id = ranked.id
          AND ranked.workspace_rank > 1
        """
    )
    op.create_index(
        "uq_conversations_active_collection",
        "conversations",
        ["collection_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "workspace_test_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "confirmed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "conversation_id",
            "version",
            name="uq_workspace_test_brief_version",
        ),
    )
    op.create_index(
        "ix_workspace_test_briefs_conversation_id",
        "workspace_test_briefs",
        ["conversation_id"],
    )

    op.create_table(
        "workspace_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generation_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("ref", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "included",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "conversation_id",
            "ref",
            "version",
            name="uq_workspace_candidate_version",
        ),
    )
    op.create_index(
        "ix_workspace_candidates_conversation_id",
        "workspace_candidates",
        ["conversation_id"],
    )
    op.create_index(
        "ix_workspace_candidates_generation_job_id",
        "workspace_candidates",
        ["generation_job_id"],
    )

    op.create_table(
        "execution_run_assignees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "account_id",
            name="uq_execution_run_assignee",
        ),
    )
    op.create_index(
        "ix_execution_run_assignees_run_id",
        "execution_run_assignees",
        ["run_id"],
    )
    op.create_index(
        "ix_execution_run_assignees_account_id",
        "execution_run_assignees",
        ["account_id"],
    )

    op.add_column(
        "execution_records",
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_execution_records_assignee_id_accounts",
        "execution_records",
        "accounts",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_execution_records_assignee_id",
        "execution_records",
        ["assignee_id"],
    )
    op.execute(
        """
        UPDATE execution_records AS record
        SET assignee_id = run.executor_id
        FROM execution_runs AS run
        WHERE run.id = record.run_id
          AND record.assignee_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO execution_run_assignees (id, run_id, account_id, created_at)
        SELECT gen_random_uuid(), run.id, run.executor_id, run.created_at
        FROM execution_runs AS run
        ON CONFLICT (run_id, account_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_execution_records_assignee_id", table_name="execution_records")
    op.drop_constraint(
        "fk_execution_records_assignee_id_accounts",
        "execution_records",
        type_="foreignkey",
    )
    op.drop_column("execution_records", "assignee_id")
    op.drop_table("execution_run_assignees")
    op.drop_table("workspace_candidates")
    op.drop_table("workspace_test_briefs")
    op.drop_index(
        "uq_conversations_active_collection",
        table_name="conversations",
    )
