"""store automation case bindings on test case revisions

Revision ID: 20260917_0024
Revises: 20260914_0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260917_0024"
down_revision: str | Sequence[str] | None = "20260914_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_case_revisions",
        sa.Column(
            "automation_cases", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("test_case_revisions", "automation_cases")
