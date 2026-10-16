"""Index case body lookup used by historical case reuse."""

from alembic import op

revision = "20261016_0029"
down_revision = "20261015_0028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""CREATE INDEX ix_case_revision_reuse_search ON test_case_revisions USING gin
        ((title || ' ' || module || ' ' ||
          preconditions::text || ' ' || steps::text) gin_trgm_ops)""")


def downgrade():
    op.drop_index("ix_case_revision_reuse_search", table_name="test_case_revisions")
