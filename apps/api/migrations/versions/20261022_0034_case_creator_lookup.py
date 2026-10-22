"""Bound creator provenance lookup to the displayed case IDs."""
from alembic import op
revision = '20261022_0034'
down_revision = '20261022_0033'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('ix_audit_case_creator', 'audit_events', ['resource_type', 'action', 'resource_id', 'created_at', 'id'], postgresql_include=['actor_id'])
    op.execute('ANALYZE audit_events')

def downgrade():
    op.drop_index('ix_audit_case_creator', table_name='audit_events')
