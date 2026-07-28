"""simplify execution run context to a task description

Revision ID: 20260727_0005
Revises: 20260727_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0005"
down_revision: str | None = "20260727_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE execution_runs
        SET description = concat_ws(
            ' · ',
            NULLIF(software_version, ''),
            NULLIF(build_number, ''),
            NULLIF(environment, '')
        )
        """
    )
    op.execute(
        """
        UPDATE execution_runs
        SET description = '历史执行任务'
        WHERE description IS NULL OR description = ''
        """
    )
    op.alter_column("execution_runs", "description", nullable=False)
    op.drop_column("execution_runs", "environment")
    op.drop_column("execution_runs", "build_number")
    op.drop_column("execution_runs", "software_version")


def downgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column(
            "software_version",
            sa.String(length=120),
            nullable=False,
            server_default="历史版本",
        ),
    )
    op.add_column(
        "execution_runs",
        sa.Column(
            "build_number",
            sa.String(length=120),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "execution_runs",
        sa.Column(
            "environment",
            sa.String(length=120),
            nullable=False,
            server_default="历史环境",
        ),
    )
    op.drop_column("execution_runs", "description")
