"""Versioned explicit collection references and immutable proposal source bindings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261031_0039"
down_revision = "20261031_0038"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "case_collections",
        sa.Column("reference_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_sources",
        sa.Column("reference_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "case_change_sets",
        sa.Column("reference_binding", JSONB(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "collection_references",
        sa.Column(
            "collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("case_collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_sources.id"), primary_key=True
        ),
    )


def downgrade():
    op.drop_table("collection_references")
    op.drop_column("case_change_sets", "reference_binding")
    op.drop_column("knowledge_sources", "reference_revision")
    op.drop_column("case_collections", "reference_version")
