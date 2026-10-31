"""Durable workbench runs and unique domain continuation events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261028_0037"
down_revision = "20261023_0036"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workbench_reservations",
        *[sa.Column(name, UUID(as_uuid=True), primary_key=True)
          for name in ("account_id", "conversation_id", "request_id")],
        sa.Column("budget", JSONB(), nullable=False),
        sa.Column("used", JSONB(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "workbench_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", UUID(as_uuid=True), nullable=False),
        sa.Column("root_message_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversation_messages.id"), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        *[sa.Column(name, JSONB(), nullable=False)
          for name in ("plan", "binding", "checkpoint", "budget", "used")],
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_workbench_run_request"),
    )
    op.create_index("ix_workbench_run_conversation_status", "workbench_runs",
                    ["conversation_id", "status"])
    op.create_table(
        "workbench_continuations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True),
                  sa.ForeignKey("workbench_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_kind", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("source_version", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expected_epoch", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("receipt", JSONB(), nullable=False),
        sa.Column("claim_token", UUID(as_uuid=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "event_kind", "source_id", "source_version",
                            name="uq_workbench_continuation_source"),
    )
    op.create_index("ix_workbench_continuation_status", "workbench_continuations", ["status"])


def downgrade():
    op.drop_table("workbench_continuations")
    op.drop_table("workbench_runs")
    op.drop_table("workbench_reservations")
