"""Index management search metadata; keep page reads bounded."""
from alembic import op
import sqlalchemy as sa
revision = '20261022_0032'
down_revision = '20261022_0031'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('test_case_revisions', sa.Column('management_search_text', sa.Text(), sa.Computed(
        "title || ' ' || module || ' ' || case_type || ' ' || priority || ' ' || COALESCE(source_refs->0->>'label', '') || ' ' || tags::text || ' ' || test_domains::text", persisted=True)))
    op.create_index('ix_case_revision_management_text', 'test_case_revisions', ['management_search_text'], postgresql_using='gin', postgresql_ops={'management_search_text': 'gin_trgm_ops'})
    op.execute('ANALYZE test_case_revisions')

def downgrade():
    op.drop_index('ix_case_revision_management_text', table_name='test_case_revisions')
    op.drop_column('test_case_revisions', 'management_search_text')
