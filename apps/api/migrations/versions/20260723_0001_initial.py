"""Create the initial CasePilot domain tables.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0001"
down_revision: str | Sequence[str] | None = None
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
generation_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="generation_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    case_status.create(bind, checkfirst=True)
    generation_status.create(bind, checkfirst=True)

    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_accounts_email"),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)

    op.create_table(
        "account_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_account_sessions_token_hash"),
    )
    op.create_index(
        "ix_account_sessions_account_id",
        "account_sessions",
        ["account_id"],
    )

    op.create_table(
        "spaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "space_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "space_id",
            "account_id",
            name="uq_space_membership",
        ),
    )
    op.create_index(
        "ix_space_memberships_space_id",
        "space_memberships",
        ["space_id"],
    )
    op.create_index(
        "ix_space_memberships_account_id",
        "space_memberships",
        ["account_id"],
    )
    op.create_table(
        "case_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_case_collections_space_id", "case_collections", ["space_id"])

    op.create_table(
        "test_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("current_status", case_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_test_cases_space_id", "test_cases", ["space_id"])
    op.create_index("ix_test_cases_current_status", "test_cases", ["current_status"])

    op.create_table(
        "test_case_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("preconditions", postgresql.JSONB(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "test_case_id",
            "revision_number",
            name="uq_test_case_revision_number",
        ),
    )
    op.create_index(
        "ix_test_case_revisions_test_case_id",
        "test_case_revisions",
        ["test_case_id"],
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

    op.create_table(
        "generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("status", generation_status, nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generation_jobs_space_id", "generation_jobs", ["space_id"])
    op.create_index("ix_generation_jobs_account_id", "generation_jobs", ["account_id"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_space_id", "audit_events", ["space_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("generation_jobs")
    op.drop_table("test_case_status_events")
    op.drop_table("test_case_revisions")
    op.drop_table("test_cases")
    op.drop_table("case_collections")
    op.drop_table("space_memberships")
    op.drop_table("spaces")
    op.drop_table("account_sessions")
    op.drop_table("accounts")
    bind = op.get_bind()
    generation_status.drop(bind, checkfirst=True)
    case_status.drop(bind, checkfirst=True)
