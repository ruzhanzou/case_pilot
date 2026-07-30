"""Rename the persisted assistant identity to CasePliot.

Revision ID: 20260730_0012
Revises: 20260729_0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0012"
down_revision: str | Sequence[str] | None = "20260729_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_text(column: str, table: str, old_name: str, new_name: str) -> None:
    op.execute(
        f"""
        UPDATE {table}
        SET {column} = replace({column}, '{old_name}', '{new_name}')
        WHERE {column} LIKE '%{old_name}%'
        """
    )


def _replace_json(column: str, table: str, old_name: str, new_name: str) -> None:
    op.execute(
        f"""
        UPDATE {table}
        SET {column} = replace({column}::text, '{old_name}', '{new_name}')::jsonb
        WHERE {column}::text LIKE '%{old_name}%'
        """
    )


def _rename(old_name: str, new_name: str) -> None:
    _replace_text("content", "conversation_messages", old_name, new_name)
    _replace_json("citations", "conversation_messages", old_name, new_name)
    _replace_json("metadata", "conversation_messages", old_name, new_name)
    _replace_json("context", "conversations", old_name, new_name)
    _replace_json("snapshot", "workspace_candidates", old_name, new_name)
    _replace_json("source_refs", "test_case_revisions", old_name, new_name)
    _replace_json("source_refs", "generation_artifacts", old_name, new_name)
    _replace_json("test_cases", "generation_artifacts", old_name, new_name)
    _replace_json("input_payload", "generation_jobs", old_name, new_name)
    _replace_json("output_payload", "generation_jobs", old_name, new_name)
    _replace_json("input_payload", "generation_job_stages", old_name, new_name)
    _replace_json("output_payload", "generation_job_stages", old_name, new_name)
    _replace_json("items", "case_change_sets", old_name, new_name)
    _replace_json("proposed_snapshot", "candidate_revisions", old_name, new_name)
    _replace_json("field_diff", "candidate_revisions", old_name, new_name)
    _replace_json("payload", "audit_events", old_name, new_name)


def upgrade() -> None:
    _rename("CodePliot", "CasePliot")
    _rename("CodePilot", "CasePliot")


def downgrade() -> None:
    _rename("CasePliot", "CodePliot")
