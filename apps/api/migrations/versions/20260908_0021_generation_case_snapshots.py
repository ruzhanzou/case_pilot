"""freeze approved cases per generation session

Revision ID: 20260908_0021
Revises: 20260908_0020
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260908_0021"
down_revision: str | Sequence[str] | None = "20260908_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_generation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_generation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "case_generation_id",
            "test_case_id",
            name="uq_case_generation_case",
        ),
    )
    op.create_index(
        "ix_case_generation_cases_case_generation_id",
        "case_generation_cases",
        ["case_generation_id"],
    )
    op.execute(
        """
        INSERT INTO case_generation_cases
            (id, case_generation_id, test_case_id, revision_id, position, created_at)
        SELECT
            gen_random_uuid(),
            generation.id,
            membership.test_case_id,
            test_case.current_revision_id,
            membership.position,
            now()
        FROM case_generation_sessions AS generation
        JOIN case_projects AS project ON project.id = generation.case_project_id
        JOIN collection_case_memberships AS membership
          ON membership.collection_id = project.collection_id
        JOIN test_cases AS test_case ON test_case.id = membership.test_case_id
        WHERE generation.status = 'approved'
          AND test_case.deleted_at IS NULL
          AND test_case.current_revision_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("case_generation_cases")
