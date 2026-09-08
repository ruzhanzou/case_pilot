"""add TestWeb and TestTool integration state

Revision ID: 20260908_0019
Revises: 20260907_0018
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260908_0019"
down_revision: str | Sequence[str] | None = "20260907_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'running' AFTER 'not_run'")
    op.add_column(
        "test_case_revisions",
        sa.Column("execution_level", sa.String(length=4), nullable=False, server_default="L0"),
    )
    op.add_column(
        "test_case_revisions",
        sa.Column("test_domains", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "test_case_revisions",
        sa.Column("automation_type", sa.String(length=24), nullable=False, server_default="manual"),
    )
    op.add_column(
        "execution_records",
        sa.Column("logs", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "execution_records",
        sa.Column("artifacts", postgresql.JSONB(), nullable=False, server_default="[]"),
    )

    op.execute("CREATE SEQUENCE case_project_public_id_seq START 1")
    op.execute("CREATE SEQUENCE generation_session_public_id_seq START 1")
    op.execute("CREATE SEQUENCE integration_task_public_id_seq START 1")

    op.create_table(
        "case_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_id", sa.String(length=24), nullable=False, unique=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_collections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_system", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("target_key", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("linked_fr_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("linked_qpm_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("test_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "space_id",
            "source_system",
            "target_type",
            "target_id",
            name="uq_case_project_external_target",
        ),
    )
    op.create_index("ix_case_projects_public_id", "case_projects", ["public_id"], unique=True)
    op.create_index("ix_case_projects_target_type", "case_projects", ["target_type"])
    op.create_index("ix_case_projects_target_id", "case_projects", ["target_id"])

    op.create_table(
        "case_generation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column(
            "case_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generation_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_jobs.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="generating"),
        sa.Column("error_code", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_case_generation_sessions_public_id",
        "case_generation_sessions",
        ["public_id"],
        unique=True,
    )
    op.create_index("ix_case_generation_sessions_status", "case_generation_sessions", ["status"])

    op.create_table(
        "integration_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_id", sa.String(length=24), nullable=False, unique=True),
        sa.Column("task_request_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "case_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_generation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "playlist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "execution_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("execution_runs.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("tester", sa.String(length=320), nullable=False),
        sa.Column("execution_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("task_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("selected_level", sa.String(length=4), nullable=False, server_default="L4"),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending_confirmation"
        ),
        sa.Column("logs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_integration_tasks_public_id", "integration_tasks", ["public_id"], unique=True
    )
    op.create_index("ix_integration_tasks_status", "integration_tasks", ["status"])
    op.create_index("ix_integration_tasks_tester", "integration_tasks", ["tester"])
    op.create_index("ix_integration_tasks_updated_at", "integration_tasks", ["updated_at"])

    op.create_table(
        "test_tool_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "integration_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integration_tasks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_test_tool_leases_expires_at", "test_tool_leases", ["expires_at"])

    op.create_table(
        "integration_updates",
        sa.Column("update_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "integration_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integration_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "callback_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_callback_deliveries_event_type", "callback_deliveries", ["event_type"])
    op.create_index("ix_callback_deliveries_aggregate_id", "callback_deliveries", ["aggregate_id"])
    op.create_index("ix_callback_deliveries_status", "callback_deliveries", ["status"])
    op.create_index(
        "ix_callback_deliveries_next_attempt_at", "callback_deliveries", ["next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("callback_deliveries")
    op.drop_table("integration_updates")
    op.drop_table("test_tool_leases")
    op.drop_table("integration_tasks")
    op.drop_table("case_generation_sessions")
    op.drop_table("case_projects")
    op.execute("DROP SEQUENCE integration_task_public_id_seq")
    op.execute("DROP SEQUENCE generation_session_public_id_seq")
    op.execute("DROP SEQUENCE case_project_public_id_seq")
    op.drop_column("execution_records", "artifacts")
    op.drop_column("execution_records", "logs")
    op.drop_column("test_case_revisions", "automation_type")
    op.drop_column("test_case_revisions", "test_domains")
    op.drop_column("test_case_revisions", "execution_level")
    # PostgreSQL enum values are intentionally retained; removing one is unsafe.
