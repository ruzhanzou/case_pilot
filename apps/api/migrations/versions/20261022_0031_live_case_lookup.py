"""Cover live space-scoped case IDs and current revisions for asset retrieval."""
from alembic import op
import sqlalchemy as sa
revision = '20261022_0031'
down_revision = '20261022_0030'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_test_case_live_space_id', 'test_cases', ['space_id', 'id'],
                    postgresql_include=['current_revision_id'],
                    postgresql_where=sa.text('deleted_at IS NULL'))
    # The preceding stored search-column migration rewrites rows; old column
    # statistics otherwise severely underestimate broad Chinese matches.
    op.execute('ANALYZE test_cases')
    op.execute('ANALYZE test_case_revisions')


def downgrade():
    op.drop_index('ix_test_case_live_space_id', table_name='test_cases')
