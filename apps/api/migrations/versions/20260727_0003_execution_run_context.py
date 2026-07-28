"""add execution run target context

Revision ID: 20260727_0003
Revises: 20260726_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0003"
down_revision: str | None = "20260726_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column("software_version", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "execution_runs",
        sa.Column("build_number", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "execution_runs",
        sa.Column("environment", sa.String(length=120), nullable=True),
    )
    op.execute(
        "UPDATE execution_runs SET software_version = '历史版本', environment = '历史环境'"
    )
    op.alter_column("execution_runs", "software_version", nullable=False)
    op.alter_column("execution_runs", "environment", nullable=False)
    op.alter_column("execution_runs", "build_number", server_default=None)


def downgrade() -> None:
    op.drop_column("execution_runs", "environment")
    op.drop_column("execution_runs", "build_number")
    op.drop_column("execution_runs", "software_version")
