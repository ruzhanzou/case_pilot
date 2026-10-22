"""Store the searchable body once per immutable revision instead of per lookup."""
from alembic import op
import sqlalchemy as sa
revision='20261022_0030'
down_revision='20261016_0029'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('test_case_revisions',sa.Column('reuse_search_text',sa.Text(),sa.Computed(
        "title || ' ' || module || ' ' || preconditions::text || ' ' || steps::text",persisted=True)))
    op.create_index('ix_case_revision_reuse_text','test_case_revisions',['reuse_search_text'],postgresql_using='gin',postgresql_ops={'reuse_search_text':'gin_trgm_ops'})

def downgrade():
    op.drop_index('ix_case_revision_reuse_text',table_name='test_case_revisions')
    op.drop_column('test_case_revisions','reuse_search_text')
