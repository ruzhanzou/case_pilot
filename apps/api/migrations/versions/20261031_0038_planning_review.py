"""Bounded full-plan second opinion and human-approved revision."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261031_0038"
down_revision = "20261028_0037"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "planning_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "brief_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspace_test_briefs.id"),
            nullable=False,
        ),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("binding", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requests_used", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("applied_brief_id", UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "requests_used >= 0 AND requests_used <= 2", name="ck_planning_review_budget"
        ),
    )
    op.create_index("ix_planning_reviews_conversation_id", "planning_reviews", ["conversation_id"])


def downgrade():
    op.drop_table("planning_reviews")
