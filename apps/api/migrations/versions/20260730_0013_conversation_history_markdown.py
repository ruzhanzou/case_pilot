"""Add conversation history metadata and Markdown test briefs.

Revision ID: 20260730_0013
Revises: 20260730_0012
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0013"
down_revision: str | Sequence[str] | None = "20260730_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


BRIEF_SECTIONS = (
    ("测试范围", "scope"),
    ("角色", "roles"),
    ("核心流程", "core_flows"),
    ("业务规则", "business_rules"),
    ("约束", "constraints"),
    ("风险", "risks"),
    ("覆盖维度", "coverage_dimensions"),
    ("假设", "assumptions"),
)


def _render_markdown(version: int, content: dict[str, Any]) -> str:
    lines = [
        f"# 结构化测试说明 V{version}",
        "",
        "## 测试目标",
        "",
        str(content.get("test_objective") or "未提供"),
    ]
    for title, key in BRIEF_SECTIONS:
        lines.extend(["", f"## {title}", ""])
        values = content.get(key) or []
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("未提供")
    lines.extend(["", "## 待确认项", ""])
    questions = content.get("open_questions") or []
    if not questions:
        lines.append("无待确认项。")
    for item in questions:
        prefix = "阻塞" if item.get("blocking") else "建议确认"
        lines.append(f"- **{prefix}**：{item.get('question', '')}")
        if item.get("impact"):
            lines.append(f"  - 影响：{item['impact']}")
    return "\n".join(lines).strip() + "\n"


def upgrade() -> None:
    op.add_column(
        "workspace_test_briefs",
        sa.Column(
            "markdown_content",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
    )
    connection = op.get_bind()
    briefs = connection.execute(
        sa.text("SELECT id, version, content FROM workspace_test_briefs")
    ).mappings()
    for brief in briefs:
        connection.execute(
            sa.text(
                """
                UPDATE workspace_test_briefs
                SET markdown_content = :markdown_content
                WHERE id = :brief_id
                """
            ),
            {
                "brief_id": brief["id"],
                "markdown_content": _render_markdown(
                    int(brief["version"]),
                    dict(brief["content"] or {}),
                ),
            },
        )

    conversations = connection.execute(
        sa.text(
            """
            SELECT c.id, c.context, c.title,
                   (
                       SELECT m.content
                       FROM conversation_messages m
                       WHERE m.conversation_id = c.id
                         AND m.role = 'user'
                         AND m.intent IN ('CASE_GENERATE', 'CASE_MODIFY')
                       ORDER BY m.created_at, m.id
                       LIMIT 1
                   ) AS first_message
            FROM conversations c
            WHERE c.status = 'active'
            """
        )
    ).mappings()
    for conversation in conversations:
        first_message = " ".join(
            str(conversation["first_message"] or "").split()
        )
        context = dict(conversation["context"] or {})
        context["title_initialized"] = bool(first_message)
        connection.execute(
            sa.text(
                """
                UPDATE conversations
                SET title = :title,
                    context = CAST(:context AS jsonb)
                WHERE id = :conversation_id
                """
            ),
            {
                "conversation_id": conversation["id"],
                "title": first_message[:40] or conversation["title"],
                "context": json.dumps(
                    context,
                    ensure_ascii=False,
                ),
            },
        )


def downgrade() -> None:
    op.drop_column("workspace_test_briefs", "markdown_content")
