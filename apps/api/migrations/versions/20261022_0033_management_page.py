"""Read the first management page without sorting the entire space."""
from alembic import op
import sqlalchemy as sa
revision = '20261022_0033'
down_revision = '20261022_0032'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('ix_test_case_live_page', 'test_cases', ['space_id', 'created_at', 'id'], postgresql_include=['current_revision_id'], postgresql_where=sa.text('deleted_at IS NULL'))
    op.execute('ANALYZE test_cases')

def downgrade():
    op.drop_index('ix_test_case_live_page', table_name='test_cases')
