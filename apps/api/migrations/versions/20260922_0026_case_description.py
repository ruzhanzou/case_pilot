"""Add optional case descriptions to revisions."""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0026"
down_revision = "20260922_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_case_revisions",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("test_case_revisions", "description")
