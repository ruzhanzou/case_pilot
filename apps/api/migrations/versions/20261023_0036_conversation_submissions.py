"""Persist atomic natural-language submission receipts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '20261023_0036'
down_revision = '20261022_0035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'conversation_submissions',
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('response', postgresql.JSONB(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table('conversation_submissions')
