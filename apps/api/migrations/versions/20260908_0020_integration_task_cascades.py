"""make integration task ownership cascades deterministic

Revision ID: 20260908_0020
Revises: 20260908_0019
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0020"
down_revision: str | Sequence[str] | None = "20260908_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "integration_tasks_case_generation_id_fkey",
        "integration_tasks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "integration_tasks_playlist_id_fkey",
        "integration_tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "integration_tasks_case_generation_id_fkey",
        "integration_tasks",
        "case_generation_sessions",
        ["case_generation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "integration_tasks_playlist_id_fkey",
        "integration_tasks",
        "playlists",
        ["playlist_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "integration_tasks_playlist_id_fkey",
        "integration_tasks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "integration_tasks_case_generation_id_fkey",
        "integration_tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "integration_tasks_playlist_id_fkey",
        "integration_tasks",
        "playlists",
        ["playlist_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "integration_tasks_case_generation_id_fkey",
        "integration_tasks",
        "case_generation_sessions",
        ["case_generation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
