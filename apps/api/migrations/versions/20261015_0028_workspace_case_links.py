"""Persist version-scoped test point links without rewriting case bodies."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261015_0028"
down_revision = "20261008_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_case_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_test_briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test_point_id", sa.String(200), nullable=False),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_case_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "brief_id", "test_point_id", "test_case_id", name="uq_workspace_point_case"
        ),
    )
    op.create_index("ix_workspace_case_links_brief_id", "workspace_case_links", ["brief_id"])
    op.create_index(
        "ix_workspace_case_links_test_case_id", "workspace_case_links", ["test_case_id"]
    )


def downgrade():
    op.drop_table("workspace_case_links")
