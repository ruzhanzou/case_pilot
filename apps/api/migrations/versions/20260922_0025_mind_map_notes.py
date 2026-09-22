"""Persist collection mind map text nodes.

Revision ID: 20260922_0025
Revises: 20260917_0024
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260922_0025"
down_revision = "20260917_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "case_collections",
        sa.Column("mind_map_notes", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("case_collections", "mind_map_notes")
