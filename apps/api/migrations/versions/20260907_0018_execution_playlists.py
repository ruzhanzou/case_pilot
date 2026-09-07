"""add reusable execution playlists

Revision ID: 20260907_0018
Revises: 20260903_0017
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0018"
down_revision: str | Sequence[str] | None = "20260903_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "playlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "creator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_playlists_space_id", "playlists", ["space_id"])
    op.create_index("ix_playlists_creator_id", "playlists", ["creator_id"])

    op.create_table(
        "playlist_case_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "playlist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "test_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("playlist_id", "test_case_id", name="uq_playlist_case"),
    )
    op.create_index(
        "ix_playlist_case_memberships_playlist_id",
        "playlist_case_memberships",
        ["playlist_id"],
    )
    op.create_index(
        "ix_playlist_case_memberships_test_case_id",
        "playlist_case_memberships",
        ["test_case_id"],
    )

    op.create_table(
        "playlist_source_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "playlist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("case_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "playlist_id", "collection_id", name="uq_playlist_source_collection"
        ),
    )
    op.create_index(
        "ix_playlist_source_collections_playlist_id",
        "playlist_source_collections",
        ["playlist_id"],
    )
    op.create_index(
        "ix_playlist_source_collections_collection_id",
        "playlist_source_collections",
        ["collection_id"],
    )

    op.add_column(
        "execution_runs",
        sa.Column("playlist_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "execution_runs",
        sa.Column("source_type", sa.String(length=24), server_default="collection"),
    )
    op.add_column(
        "execution_runs",
        sa.Column("source_name", sa.String(length=160), server_default=""),
    )
    op.add_column(
        "execution_runs",
        sa.Column("source_collection_count", sa.Integer(), server_default="1"),
    )
    op.execute(
        """
        UPDATE execution_runs AS run
        SET source_name = collection.name
        FROM case_collections AS collection
        WHERE collection.id = run.collection_id
        """
    )
    op.alter_column("execution_runs", "source_type", nullable=False)
    op.alter_column("execution_runs", "source_name", nullable=False)
    op.alter_column("execution_runs", "source_collection_count", nullable=False)
    op.alter_column("execution_runs", "collection_id", nullable=True)
    op.create_foreign_key(
        "fk_execution_runs_playlist",
        "execution_runs",
        "playlists",
        ["playlist_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_execution_runs_playlist_id", "execution_runs", ["playlist_id"])


def downgrade() -> None:
    op.execute(
        """
        UPDATE execution_runs
        SET collection_id = (
            SELECT collection_id
            FROM playlist_source_collections
            WHERE playlist_id = execution_runs.playlist_id
            ORDER BY position
            LIMIT 1
        )
        WHERE collection_id IS NULL
        """
    )
    missing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM execution_runs WHERE collection_id IS NULL")
    ).scalar_one()
    if missing:
        raise RuntimeError("cannot downgrade: playlist runs have no surviving source collection")
    op.alter_column("execution_runs", "collection_id", nullable=False)
    op.drop_index("ix_execution_runs_playlist_id", table_name="execution_runs")
    op.drop_constraint("fk_execution_runs_playlist", "execution_runs", type_="foreignkey")
    op.drop_column("execution_runs", "source_collection_count")
    op.drop_column("execution_runs", "source_name")
    op.drop_column("execution_runs", "source_type")
    op.drop_column("execution_runs", "playlist_id")
    op.drop_table("playlist_source_collections")
    op.drop_table("playlist_case_memberships")
    op.drop_table("playlists")
