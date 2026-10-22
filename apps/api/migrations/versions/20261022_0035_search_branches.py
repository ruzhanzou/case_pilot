"""Index optional case-key and scoped creator search branches."""
from alembic import op
revision = '20261022_0035'
down_revision = '20261022_0034'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('ix_test_case_key_search', 'test_cases', ['case_key'], postgresql_using='gin', postgresql_ops={'case_key': 'gin_trgm_ops'})
    op.create_index('ix_audit_space_actor', 'audit_events', ['space_id', 'actor_id', 'action', 'resource_type'])
    op.execute('ANALYZE test_cases')
    op.execute('ANALYZE audit_events')

def downgrade():
    op.drop_index('ix_audit_space_actor', table_name='audit_events')
    op.drop_index('ix_test_case_key_search', table_name='test_cases')
