"""Unify the persisted assistant identity with the CasePilot product name.

Revision ID: 20260730_0014
Revises: 20260730_0013
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0014"
down_revision: str | Sequence[str] | None = "20260730_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_text(column: str, table: str, old_name: str) -> None:
    op.execute(
        f"""
        UPDATE {table}
        SET {column} = replace({column}, '{old_name}', 'CasePilot')
        WHERE {column} LIKE '%{old_name}%'
        """
    )


def _replace_json(column: str, table: str, old_name: str) -> None:
    op.execute(
        f"""
        UPDATE {table}
        SET {column} = replace(
            {column}::text,
            '{old_name}',
            'CasePilot'
        )::jsonb
        WHERE {column}::text LIKE '%{old_name}%'
        """
    )


def _rename_legacy_identity(old_name: str) -> None:
    _replace_text("content", "conversation_messages", old_name)
    _replace_json("citations", "conversation_messages", old_name)
    _replace_json("metadata", "conversation_messages", old_name)
    _replace_json("context", "conversations", old_name)
    _replace_json("snapshot", "workspace_candidates", old_name)
    _replace_json("source_refs", "test_case_revisions", old_name)
    _replace_json("source_refs", "generation_artifacts", old_name)
    _replace_json("test_cases", "generation_artifacts", old_name)
    _replace_json("input_payload", "generation_jobs", old_name)
    _replace_json("output_payload", "generation_jobs", old_name)
    _replace_json("input_payload", "generation_job_stages", old_name)
    _replace_json("output_payload", "generation_job_stages", old_name)
    _replace_json("items", "case_change_sets", old_name)
    _replace_json("proposed_snapshot", "candidate_revisions", old_name)
    _replace_json("field_diff", "candidate_revisions", old_name)
    _replace_json("payload", "audit_events", old_name)


def upgrade() -> None:
    for old_name in ("CasePliot", "CodePliot", "CodePilot"):
        _rename_legacy_identity(old_name)


def downgrade() -> None:
    # CasePilot was already the product brand before this migration. Persisted
    # occurrences cannot safely be split back into product and assistant names.
    pass
