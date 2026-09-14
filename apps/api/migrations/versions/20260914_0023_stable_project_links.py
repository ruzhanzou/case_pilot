"""persist stable case project link expiry

Revision ID: 20260914_0023
Revises: 20260910_0022
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0023"
down_revision: str | Sequence[str] | None = "20260910_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "case_projects",
        sa.Column("platform_link_expires_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "UPDATE case_projects SET platform_link_expires_at = now() + interval '1 day'"
    )
    op.alter_column("case_projects", "platform_link_expires_at", nullable=False)


def downgrade() -> None:
    op.drop_column("case_projects", "platform_link_expires_at")
