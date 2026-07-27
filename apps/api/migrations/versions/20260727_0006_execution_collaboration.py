"""track collaborative execution contributors

Revision ID: 20260727_0006
Revises: 20260727_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0006"
down_revision: str | None = "20260727_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_records",
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_execution_records_updated_by",
        "execution_records",
        "accounts",
        ["updated_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_execution_records_updated_by_id",
        "execution_records",
        ["updated_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_records_updated_by_id",
        table_name="execution_records",
    )
    op.drop_constraint(
        "fk_execution_records_updated_by",
        "execution_records",
        type_="foreignkey",
    )
    op.drop_column("execution_records", "updated_by_id")
