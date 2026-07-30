"""Add Agent generation artifacts and candidate revisions.

Revision ID: 20260728_0007
Revises: 20260727_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0007"
down_revision: str | Sequence[str] | None = "20260727_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column(
            "operation",
            sa.String(length=32),
            nullable=False,
            server_default="generate",
        ),
    )
    op.add_column(
        "generation_jobs",
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_collections.id", ondelete="CASCADE"),
        ),
    )
    op.create_index(
        "ix_generation_jobs_collection_id",
        "generation_jobs",
        ["collection_id"],
    )
    op.create_table(
        "generation_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "generation_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("requirement_analysis", postgresql.JSONB(), nullable=False),
        sa.Column("feature_points", postgresql.JSONB(), nullable=False),
        sa.Column("test_points", postgresql.JSONB(), nullable=False),
        sa.Column("open_questions", postgresql.JSONB(), nullable=False),
        sa.Column("quality_report", postgresql.JSONB(), nullable=False),
        sa.Column("model_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "base_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_case_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generation_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("proposed_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("field_diff", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_revisions_test_case_id",
        "candidate_revisions",
        ["test_case_id"],
    )


def downgrade() -> None:
    op.drop_table("candidate_revisions")
    op.drop_table("generation_artifacts")
    op.drop_index("ix_generation_jobs_collection_id", table_name="generation_jobs")
    op.drop_column("generation_jobs", "collection_id")
    op.drop_column("generation_jobs", "operation")
