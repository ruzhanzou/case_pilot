"""add caller callback configuration and playlist creation sessions

Revision ID: 20260910_0022
Revises: 20260908_0021
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260910_0022"
down_revision: str | Sequence[str] | None = "20260908_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("case_generation_sessions", "integration_tasks"):
        op.add_column(table_name, sa.Column("callback_url", sa.Text()))
        op.add_column(
            table_name,
            sa.Column("callback_events", postgresql.JSONB(), nullable=False, server_default="[]"),
        )
        op.add_column(table_name, sa.Column("callback_correlation_id", sa.String(length=200)))

    op.create_table(
        "playlist_creation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "creator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "playlist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playlists.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("test_target", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("case_collections", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("playlist_draft", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column("callback_events", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("callback_correlation_id", sa.String(length=200)),
        sa.Column("callback_context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending_user_action"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_playlist_creation_sessions_case_project_id",
        "playlist_creation_sessions",
        ["case_project_id"],
    )
    op.create_index(
        "ix_playlist_creation_sessions_creator_id",
        "playlist_creation_sessions",
        ["creator_id"],
    )
    op.create_index(
        "ix_playlist_creation_sessions_status", "playlist_creation_sessions", ["status"]
    )
    op.create_index(
        "ix_playlist_creation_sessions_expires_at",
        "playlist_creation_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("playlist_creation_sessions")
    for table_name in ("integration_tasks", "case_generation_sessions"):
        op.drop_column(table_name, "callback_correlation_id")
        op.drop_column(table_name, "callback_events")
        op.drop_column(table_name, "callback_url")
