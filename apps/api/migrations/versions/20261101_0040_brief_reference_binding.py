"""Keep material authority across every persisted brief version."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261101_0040"
down_revision = "20261031_0039"
branch_labels = depends_on = None


def upgrade():
    # Legacy rows retain their existing operation/review guards. Do not fabricate
    # snapshots from current materials for artifacts produced in the past.
    op.add_column(
        "workspace_test_briefs",
        sa.Column("reference_binding", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("workspace_test_briefs", "reference_binding")
