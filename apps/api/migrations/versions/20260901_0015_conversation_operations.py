"""Decouple conversations from collections and persist ordered operations.

Revision ID: 20260901_0015
Revises: 20260730_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0015"
down_revision: str | Sequence[str] | None = "20260730_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_conversations_active_collection", table_name="conversations")
    op.alter_column("conversations", "collection_id", nullable=True)
    op.drop_constraint(
        "conversations_collection_id_fkey",
        "conversations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "conversations_collection_id_fkey",
        "conversations",
        "case_collections",
        ["collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "conversation_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column(
            "related_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "related_change_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_change_sets.id", ondelete="SET NULL"),
        ),
        sa.Column("error_code", sa.String(length=120)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "message_id",
            "sequence",
            name="uq_conversation_operation_sequence",
        ),
    )
    for column in (
        "conversation_id",
        "message_id",
        "intent",
        "related_job_id",
        "related_change_set_id",
    ):
        op.create_index(
            f"ix_conversation_operations_{column}",
            "conversation_operations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("conversation_operations")
    op.execute(
        "DELETE FROM conversations WHERE collection_id IS NULL"
    )
    op.drop_constraint(
        "conversations_collection_id_fkey",
        "conversations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "conversations_collection_id_fkey",
        "conversations",
        "case_collections",
        ["collection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("conversations", "collection_id", nullable=False)
    op.create_index(
        "uq_conversations_active_collection",
        "conversations",
        ["collection_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
