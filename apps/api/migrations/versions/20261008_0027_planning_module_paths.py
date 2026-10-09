"""Allow complete business planning paths on test cases."""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0027"
down_revision = "20260922_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "test_case_revisions", "module", type_=sa.String(4000), existing_type=sa.String(160)
    )


def downgrade() -> None:
    # Never silently truncate user-authored paths during rollback.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM test_case_revisions WHERE length(module) > 160) "
        "THEN RAISE EXCEPTION 'Planning paths exceed legacy module length'; "
        "END IF; END $$;"
    )
    op.alter_column(
        "test_case_revisions", "module", type_=sa.String(160), existing_type=sa.String(4000)
    )
