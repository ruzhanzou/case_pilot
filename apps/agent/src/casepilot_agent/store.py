import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import HALFVEC
from redis import Redis
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    case,
    create_engine,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Connection

metadata = MetaData()
generation_status = ENUM(
    "queued",
    "running",
    "awaiting_input",
    "completed",
    "failed",
    "cancelled",
    name="generation_status",
    create_type=False,
)

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


def lexical_search_terms(search_query: str) -> list[str]:
    """Return stable, meaningful terms for multilingual substring ranking."""
    terms: list[str] = []
    for token in search_query.split():
        normalized = token.strip().lower()
        if (
            normalized
            and normalized not in terms
            and re.search(r"[a-z0-9\u3400-\u9fff]", normalized)
            and (len(normalized) > 1 or normalized.isdigit())
        ):
            terms.append(normalized)
    return terms[:32]


def render_test_brief_markdown(version: int, content: dict[str, Any]) -> str:
    lines = [
        f"# 结构化测试说明 V{version}",
        "",
        "## 测试对象",
        "",
        str(content.get("test_object") or "待澄清"),
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
    lines.extend(["", "## 测试对象澄清", ""])
    questions = content.get("open_questions") or []
    if not questions:
        lines.append("测试对象已明确，无需澄清。")
    for item in questions:
        lines.append(f"- **待澄清**：{item.get('question', '')}")
        if item.get("impact"):
            lines.append(f"  - 影响：{item['impact']}")
    return "\n".join(lines).strip() + "\n"


generation_jobs = Table(
    "generation_jobs",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("space_id", PGUUID(as_uuid=True)),
    Column("account_id", PGUUID(as_uuid=True)),
    Column("operation", String),
    Column("collection_id", PGUUID(as_uuid=True)),
    Column("status", generation_status),
    Column("stage", String),
    Column("input_payload", JSONB),
    Column("output_payload", JSONB),
    Column("error_code", String),
)
test_cases = Table(
    "test_cases",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("space_id", PGUUID(as_uuid=True)),
    Column("case_key", String),
    Column("current_revision_id", PGUUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True)),
)
test_case_revisions = Table(
    "test_case_revisions",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("test_case_id", PGUUID(as_uuid=True)),
    Column("revision_number", Integer),
    Column("title", String),
    Column("module", String),
    Column("priority", String),
    Column("case_type", String),
    Column("tags", JSONB),
    Column("preconditions", JSONB),
    Column("steps", JSONB),
    Column("source_refs", JSONB),
    Column("created_at", DateTime(timezone=True)),
)
collection_items = Table(
    "collection_case_memberships",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("collection_id", PGUUID(as_uuid=True)),
    Column("test_case_id", PGUUID(as_uuid=True)),
    Column("position", Integer),
    Column("created_at", DateTime(timezone=True)),
)
artifacts = Table(
    "generation_artifacts",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("generation_job_id", PGUUID(as_uuid=True)),
    Column("requirement_analysis", JSONB),
    Column("feature_points", JSONB),
    Column("test_points", JSONB),
    Column("open_questions", JSONB),
    Column("quality_report", JSONB),
    Column("model_metadata", JSONB),
    Column("coverage_matrix", JSONB),
    Column("test_cases", JSONB),
    Column("source_refs", JSONB),
    Column("created_at", DateTime(timezone=True)),
)
knowledge_sources = Table(
    "knowledge_sources",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("space_id", PGUUID(as_uuid=True)),
    Column("account_id", PGUUID(as_uuid=True)),
    Column("name", String),
    Column("kind", String),
    Column("persistence", String),
    Column("status", String),
    Column("error_code", String),
    Column("deleted_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
knowledge_documents = Table(
    "knowledge_documents",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("source_id", PGUUID(as_uuid=True)),
    Column("space_id", PGUUID(as_uuid=True)),
    Column("original_name", String),
    Column("mime_type", String),
    Column("storage_key", String),
    Column("size_bytes", Integer),
    Column("checksum", String),
    Column("version", Integer),
    Column("status", String),
    Column("error_code", String),
    Column("expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("document_id", PGUUID(as_uuid=True)),
    Column("source_id", PGUUID(as_uuid=True)),
    Column("space_id", PGUUID(as_uuid=True)),
    Column("parent_chunk_id", PGUUID(as_uuid=True)),
    Column("chunk_type", String),
    Column("ordinal", Integer),
    Column("section_path", String),
    Column("locator", String),
    Column("content", Text),
    Column("contextual_content", Text),
    Column("search_text", Text),
    Column("token_count", Integer),
    Column("embedding", HALFVEC(2048)),
    Column("metadata", JSONB),
    Column("created_at", DateTime(timezone=True)),
)
generation_stages = Table(
    "generation_job_stages",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("generation_job_id", PGUUID(as_uuid=True)),
    Column("stage", String),
    Column("attempt", Integer),
    Column("status", String),
    Column("input_payload", JSONB),
    Column("output_payload", JSONB),
    Column("prompt_version", String),
    Column("schema_version", String),
    Column("model", String),
    Column("latency_ms", Integer),
    Column("token_usage", JSONB),
    Column("input_hash", String),
    Column("created_at", DateTime(timezone=True)),
)
generation_evidence = Table(
    "generation_evidence",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("generation_job_id", PGUUID(as_uuid=True)),
    Column("stage", String),
    Column("chunk_id", PGUUID(as_uuid=True)),
    Column("query", Text),
    Column("rank", Integer),
    Column("scores", JSONB),
    Column("created_at", DateTime(timezone=True)),
)
candidates = Table(
    "candidate_revisions",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("test_case_id", PGUUID(as_uuid=True)),
    Column("base_revision_id", PGUUID(as_uuid=True)),
    Column("generation_job_id", PGUUID(as_uuid=True)),
    Column("instruction", Text),
    Column("proposed_snapshot", JSONB),
    Column("field_diff", JSONB),
    Column("reason", Text),
    Column("status", String),
    Column("created_by", PGUUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True)),
)
conversation_messages = Table(
    "conversation_messages",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("conversation_id", PGUUID(as_uuid=True)),
    Column("role", String),
    Column("content", Text),
    Column("intent", String),
    Column("intent_confidence", String),
    Column("status", String),
    Column("target_case_ids", JSONB),
    Column("related_job_id", PGUUID(as_uuid=True)),
    Column("citations", JSONB),
    Column("metadata", JSONB),
    Column("created_at", DateTime(timezone=True)),
)
conversation_operations = Table(
    "conversation_operations",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("conversation_id", PGUUID(as_uuid=True)),
    Column("message_id", PGUUID(as_uuid=True)),
    Column("sequence", Integer),
    Column("intent", String),
    Column("confidence", String),
    Column("status", String),
    Column("target", JSONB),
    Column("payload", JSONB),
    Column("result", JSONB),
    Column("requires_confirmation", Boolean),
    Column("related_job_id", PGUUID(as_uuid=True)),
    Column("related_change_set_id", PGUUID(as_uuid=True)),
    Column("error_code", String),
    Column("completed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
conversations = Table(
    "conversations",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("context", JSONB),
    Column("updated_at", DateTime(timezone=True)),
)
workspace_test_briefs = Table(
    "workspace_test_briefs",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("conversation_id", PGUUID(as_uuid=True)),
    Column("source_operation_id", PGUUID(as_uuid=True)),
    Column("version", Integer),
    Column("content", JSONB),
    Column("markdown_content", Text),
    Column("status", String),
    Column("created_by", PGUUID(as_uuid=True)),
    Column("confirmed_by", PGUUID(as_uuid=True)),
    Column("confirmed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
workspace_candidates = Table(
    "workspace_candidates",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("conversation_id", PGUUID(as_uuid=True)),
    Column("generation_job_id", PGUUID(as_uuid=True)),
    Column("ref", String),
    Column("version", Integer),
    Column("position", Integer),
    Column("snapshot", JSONB),
    Column("included", Boolean),
    Column("status", String),
    Column("created_by", PGUUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
case_change_sets = Table(
    "case_change_sets",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("conversation_id", PGUUID(as_uuid=True)),
    Column("generation_job_id", PGUUID(as_uuid=True)),
    Column("instruction", Text),
    Column("scope", String),
    Column("status", String),
    Column("items", JSONB),
    Column("created_by", PGUUID(as_uuid=True)),
    Column("applied_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
audit_events = Table(
    "audit_events",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("space_id", PGUUID(as_uuid=True)),
    Column("actor_id", PGUUID(as_uuid=True)),
    Column("action", String),
    Column("resource_type", String),
    Column("resource_id", PGUUID(as_uuid=True)),
    Column("payload", JSONB),
    Column("created_at", DateTime(timezone=True)),
)


class JobStore:
    def __init__(self, database_url: str, redis_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    @contextmanager
    def connection(self):
        with self.engine.begin() as connection:
            yield connection

    def get_job(self, connection: Connection, job_id: UUID) -> dict[str, Any]:
        row = connection.execute(
            select(generation_jobs).where(generation_jobs.c.id == job_id)
        ).mappings().one_or_none()
        if row is None:
            raise ValueError("generation_job_not_found")
        return dict(row)

    def get_job_for_update(
        self,
        connection: Connection,
        job_id: UUID,
    ) -> dict[str, Any]:
        row = connection.execute(
            select(generation_jobs)
            .where(generation_jobs.c.id == job_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise ValueError("generation_job_not_found")
        return dict(row)

    def update_job(self, connection: Connection, job_id: UUID, **values: Any) -> None:
        connection.execute(
            update(generation_jobs).where(generation_jobs.c.id == job_id).values(**values)
        )
        if "status" not in values:
            return
        job = self.get_job(connection, job_id)
        operation_id = dict(job.get("input_payload") or {}).get(
            "conversation_operation_id"
        )
        if not operation_id:
            return
        job_status = str(getattr(values["status"], "value", values["status"]))
        operation_status = {
            "queued": "queued",
            "running": "running",
            "awaiting_input": "awaiting_confirmation",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(job_status)
        if job_status == "completed":
            operation_status = (
                "awaiting_confirmation"
                if job["operation"] in {"draft_brief", "conversation_modify"}
                else "completed"
            )
        if operation_status:
            operation_values: dict[str, Any] = {
                "status": operation_status,
                "related_job_id": job_id,
            }
            if job_status == "completed" and operation_status == "completed":
                output_payload = dict(values.get("output_payload", {}) or {})
                operation_values["result"] = {
                    **output_payload,
                    "candidate_ids": output_payload.get(
                        "workspace_candidate_ids",
                        output_payload.get("candidate_ids", []),
                    ),
                }
                operation_values["completed_at"] = datetime.now(UTC)
            if job_status == "failed":
                operation_values["error_code"] = values.get("error_code")
                operation_values["completed_at"] = datetime.now(UTC)
            connection.execute(
                update(conversation_operations)
                .where(conversation_operations.c.id == UUID(str(operation_id)))
                .values(**operation_values)
            )

    def is_cancelled(self, connection: Connection, job_id: UUID) -> bool:
        status = connection.scalar(
            select(generation_jobs.c.status).where(generation_jobs.c.id == job_id)
        )
        return str(getattr(status, "value", status)) == "cancelled"

    def update_workspace_context(
        self,
        connection: Connection,
        conversation_id: UUID,
        **values: Any,
    ) -> None:
        current = connection.execute(
            select(conversations.c.context).where(conversations.c.id == conversation_id)
        ).scalar_one_or_none()
        connection.execute(
            update(conversations)
            .where(conversations.c.id == conversation_id)
            .values(
                context={**dict(current or {}), **values},
                updated_at=datetime.now(UTC),
            )
        )

    def get_source(self, connection: Connection, source_id: UUID) -> dict[str, Any]:
        row = connection.execute(
            select(knowledge_sources).where(knowledge_sources.c.id == source_id)
        ).mappings().one_or_none()
        if row is None:
            raise ValueError("knowledge_source_not_found")
        return dict(row)

    def get_source_documents(
        self,
        connection: Connection,
        source_id: UUID,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in connection.execute(
                select(knowledge_documents)
                .where(knowledge_documents.c.source_id == source_id)
                .order_by(knowledge_documents.c.created_at)
            ).mappings()
        ]

    def update_source(
        self,
        connection: Connection,
        source_id: UUID,
        **values: Any,
    ) -> None:
        connection.execute(
            update(knowledge_sources)
            .where(knowledge_sources.c.id == source_id)
            .values(**values)
        )

    def update_document(
        self,
        connection: Connection,
        document_id: UUID,
        **values: Any,
    ) -> None:
        connection.execute(
            update(knowledge_documents)
            .where(knowledge_documents.c.id == document_id)
            .values(**values)
        )

    def replace_document_chunks(
        self,
        connection: Connection,
        document: dict[str, Any],
        chunks: list[dict[str, Any]],
    ) -> None:
        connection.execute(
            delete(knowledge_chunks).where(
                knowledge_chunks.c.document_id == document["id"]
            )
        )
        now = datetime.now(UTC)
        parent_ids: dict[str, UUID] = {}
        for chunk in chunks:
            chunk_id = uuid4()
            key = str(chunk["key"])
            if chunk["chunk_type"] == "parent":
                parent_ids[key] = chunk_id
            connection.execute(
                insert(knowledge_chunks).values(
                    id=chunk_id,
                    document_id=document["id"],
                    source_id=document["source_id"],
                    space_id=document["space_id"],
                    parent_chunk_id=(
                        parent_ids.get(str(chunk.get("parent_key")))
                        if chunk.get("parent_key")
                        else None
                    ),
                    chunk_type=chunk["chunk_type"],
                    ordinal=chunk["ordinal"],
                    section_path=chunk["section_path"],
                    locator=chunk["locator"],
                    content=chunk["content"],
                    contextual_content=chunk["contextual_content"],
                    search_text=chunk["search_text"],
                    token_count=chunk["token_count"],
                    embedding=chunk["embedding"],
                    metadata=chunk.get("metadata", {}),
                    created_at=now,
                )
            )

    def cleanup_source(self, connection: Connection, source_id: UUID) -> list[str]:
        storage_keys = list(
            connection.scalars(
                select(knowledge_documents.c.storage_key).where(
                    knowledge_documents.c.source_id == source_id
                )
            )
        )
        connection.execute(
            delete(knowledge_chunks).where(knowledge_chunks.c.source_id == source_id)
        )
        return storage_keys

    def load_completed_stage(
        self,
        connection: Connection,
        job_id: UUID,
        stage: str,
        input_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        input_hash = sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        row = connection.execute(
            select(generation_stages)
            .where(
                generation_stages.c.generation_job_id == job_id,
                generation_stages.c.stage == stage,
                generation_stages.c.status == "completed",
                generation_stages.c.input_hash == input_hash,
            )
            .order_by(generation_stages.c.attempt.desc())
        ).mappings().first()
        return dict(row) if row else None

    def record_stage(
        self,
        connection: Connection,
        *,
        job_id: UUID,
        stage: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        status: str,
        model: str,
        latency_ms: int = 0,
        token_usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_hash = sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        attempt = (
            connection.scalar(
                select(func.max(generation_stages.c.attempt)).where(
                    generation_stages.c.generation_job_id == job_id,
                    generation_stages.c.stage == stage,
                )
            )
            or 0
        ) + 1
        values = {
            "id": uuid4(),
            "generation_job_id": job_id,
            "stage": stage,
            "attempt": attempt,
            "status": status,
            "input_payload": input_payload,
            "output_payload": output_payload,
            "prompt_version": "casepilot-agent-v1",
            "schema_version": "casepilot-artifact-v1",
            "model": model,
            "latency_ms": latency_ms,
            "token_usage": token_usage or {},
            "input_hash": input_hash,
            "created_at": datetime.now(UTC),
        }
        connection.execute(insert(generation_stages).values(**values))
        return values

    def retrieve_context(
        self,
        connection: Connection,
        *,
        space_id: UUID,
        query: str,
        search_query: str,
        query_embedding: list[float] | None,
        source_ids: list[UUID],
        document_ids: list[UUID],
        use_space_knowledge: bool,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        filters = [
            knowledge_chunks.c.space_id == space_id,
            knowledge_chunks.c.chunk_type == "child",
            knowledge_sources.c.status == "ready",
            knowledge_sources.c.deleted_at.is_(None),
        ]
        if source_ids and document_ids:
            filters.append(
                or_(
                    knowledge_chunks.c.source_id.in_(source_ids),
                    knowledge_chunks.c.document_id.in_(document_ids),
                )
            )
        elif source_ids:
            filters.append(knowledge_chunks.c.source_id.in_(source_ids))
        elif not use_space_knowledge and document_ids:
            filters.append(knowledge_chunks.c.document_id.in_(document_ids))
        elif not use_space_knowledge:
            return []
        distance = (
            knowledge_chunks.c.embedding.cosine_distance(query_embedding)
            if query_embedding is not None
            else literal(None)
        )
        lexical_terms = lexical_search_terms(search_query)
        lexical = (
            sum(
                (
                    case(
                        (
                            knowledge_chunks.c.search_text.contains(
                                term,
                                autoescape=True,
                            ),
                            1.0,
                        ),
                        else_=0.0,
                    )
                    for term in lexical_terms
                ),
                literal(0.0),
            )
            / max(len(lexical_terms), 1)
        )
        base = (
            select(
                knowledge_chunks,
                knowledge_documents.c.original_name.label("document_name"),
                distance.label("distance"),
                lexical.label("lexical"),
            )
            .join(
                knowledge_sources,
                knowledge_sources.c.id == knowledge_chunks.c.source_id,
            )
            .join(
                knowledge_documents,
                knowledge_documents.c.id == knowledge_chunks.c.document_id,
            )
            .where(*filters)
        )
        vector_rows = (
            list(
                connection.execute(
                    base.where(knowledge_chunks.c.embedding.is_not(None))
                    .order_by(distance.asc())
                    .limit(limit * 3)
                ).mappings()
            )
            if query_embedding is not None
            else []
        )
        lexical_rows = list(
            connection.execute(base.order_by(lexical.desc()).limit(limit * 3)).mappings()
        )
        merged: dict[UUID, dict[str, Any]] = {}
        exact_terms = {
            item.upper()
            for item in re.findall(
                r"\b(?:REQ[-_A-Z0-9]*\d|[A-Z]\d{3,})\b",
                query,
                flags=re.IGNORECASE,
            )
        }
        for ranking, rows in (("vector", vector_rows), ("lexical", lexical_rows)):
            for rank, row in enumerate(rows, start=1):
                item = merged.setdefault(
                    row["id"],
                    {**dict(row), "rrf": 0.0, "ranks": {}},
                )
                item["rrf"] += 1.0 / (60 + rank)
                item["ranks"][ranking] = rank
                content_upper = str(row["content"]).upper()
                if exact_terms and any(term in content_upper for term in exact_terms):
                    item["rrf"] += 1.0 / 30
                    item["ranks"]["exact"] = 1
        return sorted(merged.values(), key=lambda item: item["rrf"], reverse=True)[
            :limit
        ]

    def persist_evidence(
        self,
        connection: Connection,
        job_id: UUID,
        stage: str,
        query: str,
        evidence: list[dict[str, Any]],
    ) -> None:
        connection.execute(
            delete(generation_evidence).where(
                generation_evidence.c.generation_job_id == job_id,
                generation_evidence.c.stage == stage,
            )
        )
        now = datetime.now(UTC)
        for rank, item in enumerate(evidence, start=1):
            connection.execute(
                insert(generation_evidence).values(
                    id=uuid4(),
                    generation_job_id=job_id,
                    stage=stage,
                    chunk_id=item["id"],
                    query=query,
                    rank=rank,
                    scores={
                        "rrf": float(item["rrf"]),
                        "vector": 1.0 - float(item["distance"] or 1.0),
                        "lexical": float(item["lexical"] or 0.0),
                    },
                    created_at=now,
                )
            )

    def load_existing_case_titles(
        self,
        connection: Connection,
        collection_id: UUID,
    ) -> list[dict[str, str]]:
        rows = connection.execute(
            select(
                test_cases.c.case_key,
                test_case_revisions.c.title,
            )
            .join(
                collection_items,
                collection_items.c.test_case_id == test_cases.c.id,
            )
            .join(
                test_case_revisions,
                test_case_revisions.c.id == test_cases.c.current_revision_id,
            )
            .where(collection_items.c.collection_id == collection_id)
        ).mappings()
        return [
            {"case_key": row["case_key"], "title": row["title"]}
            for row in rows
        ]

    def persist_generation(
        self,
        connection: Connection,
        job: dict[str, Any],
        output: dict[str, Any],
    ) -> list[str]:
        now = datetime.now(UTC)
        requirement = output["requirement"]
        connection.execute(
            insert(artifacts).values(
                id=uuid4(),
                generation_job_id=job["id"],
                requirement_analysis=requirement,
                feature_points=output["feature_points"],
                test_points=output["test_points"],
                open_questions=requirement.get("open_questions", []),
                quality_report=output["quality"],
                model_metadata=output.get("model_metadata", {}),
                coverage_matrix=output.get("coverage_matrix", []),
                test_cases=output.get("test_cases", []),
                source_refs=output.get("source_refs", []),
                created_at=now,
            )
        )
        case_ids: list[str] = []
        persist_cases = bool(job["input_payload"].get("persist_cases", True))
        current_count = (
            connection.scalar(
                select(func.count(collection_items.c.id)).where(
                    collection_items.c.collection_id == job["collection_id"]
                )
            )
            or 0
        )
        for index, draft in enumerate(output["test_cases"] if persist_cases else []):
            case_id = uuid4()
            revision_id = uuid4()
            connection.execute(
                insert(test_cases).values(
                    id=case_id,
                    space_id=job["space_id"],
                    case_key=draft["id"],
                    current_revision_id=revision_id,
                    created_at=now,
                )
            )
            connection.execute(
                insert(test_case_revisions).values(
                    id=revision_id,
                    test_case_id=case_id,
                    revision_number=1,
                    title=draft["title"],
                    module=draft["module"],
                    case_type=draft["case_type"],
                    priority=draft["priority"],
                    tags=draft.get("tags", []),
                    preconditions=draft.get("preconditions", []),
                    steps=[
                        {
                            "id": str(step.get("id") or uuid4()),
                            "action": step["action"],
                            "expected": step["expected"],
                        }
                        for step in draft.get("steps", [])
                    ],
                    source_refs=draft.get("source_refs", []),
                    created_at=now,
                )
            )
            connection.execute(
                insert(collection_items).values(
                    id=uuid4(),
                    collection_id=job["collection_id"],
                    test_case_id=case_id,
                    position=current_count + index,
                    created_at=now,
                )
            )
            case_ids.append(str(case_id))
        connection.execute(
            insert(audit_events).values(
                id=uuid4(),
                space_id=job["space_id"],
                actor_id=job["account_id"],
                action="generation.completed",
                resource_type="case_collection",
                resource_id=job["collection_id"],
                payload={"job_id": str(job["id"]), "case_ids": case_ids},
                created_at=now,
            )
        )
        return case_ids

    def persist_test_brief(
        self,
        connection: Connection,
        job: dict[str, Any],
        content: dict[str, Any],
    ) -> int:
        conversation_id = UUID(str(job["input_payload"]["conversation_id"]))
        current_version = connection.scalar(
            select(func.max(workspace_test_briefs.c.version)).where(
                workspace_test_briefs.c.conversation_id == conversation_id
            )
        ) or 0
        connection.execute(
            update(workspace_test_briefs)
            .where(
                workspace_test_briefs.c.conversation_id == conversation_id,
                workspace_test_briefs.c.status.in_(("draft", "confirmed")),
            )
            .values(status="superseded")
        )
        version = current_version + 1
        now = datetime.now(UTC)
        connection.execute(
            insert(workspace_test_briefs).values(
                id=uuid4(),
                conversation_id=conversation_id,
                source_operation_id=(
                    UUID(str(job["input_payload"]["conversation_operation_id"]))
                    if job["input_payload"].get("conversation_operation_id")
                    else None
                ),
                version=version,
                content=content,
                markdown_content=render_test_brief_markdown(version, content),
                status="draft",
                created_by=job["account_id"],
                confirmed_by=None,
                confirmed_at=None,
                created_at=now,
            )
        )
        self.update_workspace_context(
            connection,
            conversation_id,
            phase="brief_review",
            active_job_id=None,
            confirmed_brief_version=None,
        )
        return version

    def persist_workspace_candidates(
        self,
        connection: Connection,
        job: dict[str, Any],
        drafts: list[dict[str, Any]],
    ) -> list[str]:
        raw_conversation_id = job["input_payload"].get("conversation_id")
        if not raw_conversation_id:
            return []
        conversation_id = UUID(str(raw_conversation_id))
        connection.execute(
            update(workspace_candidates)
            .where(
                workspace_candidates.c.conversation_id == conversation_id,
                workspace_candidates.c.status == "candidate",
            )
            .values(status="archived", updated_at=datetime.now(UTC))
        )
        now = datetime.now(UTC)
        candidate_ids: list[str] = []
        for position, draft in enumerate(drafts):
            ref = str(draft["id"])
            version = (
                connection.scalar(
                    select(func.max(workspace_candidates.c.version)).where(
                        workspace_candidates.c.conversation_id == conversation_id,
                        workspace_candidates.c.ref == ref,
                    )
                )
                or 0
            ) + 1
            candidate_id = uuid4()
            connection.execute(
                insert(workspace_candidates).values(
                    id=candidate_id,
                    conversation_id=conversation_id,
                    generation_job_id=job["id"],
                    ref=ref,
                    version=version,
                    position=position,
                    snapshot=draft,
                    included=True,
                    status="candidate",
                    created_by=job["account_id"],
                    created_at=now,
                    updated_at=now,
                )
            )
            candidate_ids.append(str(candidate_id))
        self.update_workspace_context(
            connection,
            conversation_id,
            phase="candidate_review",
            active_job_id=None,
            completed_job_id=str(job["id"]),
        )
        return candidate_ids

    def load_case_snapshot(
        self,
        connection: Connection,
        case_id: UUID,
        revision_id: UUID,
    ) -> dict[str, Any]:
        row = connection.execute(
            select(test_case_revisions, test_cases.c.case_key)
            .join(test_cases, test_cases.c.id == test_case_revisions.c.test_case_id)
            .where(
                test_case_revisions.c.id == revision_id,
                test_case_revisions.c.test_case_id == case_id,
            )
        ).mappings().one_or_none()
        if row is None:
            raise ValueError("base_revision_not_found")
        return {
            "id": row["case_key"],
            "title": row["title"],
            "module": row["module"],
            "case_type": row["case_type"],
            "priority": row["priority"],
            "tags": row["tags"],
            "automated": False,
            "status": "pending",
            "preconditions": row["preconditions"],
            "steps": row["steps"],
            "test_point_ids": [],
            "source_refs": row["source_refs"],
        }

    def persist_candidate(
        self,
        connection: Connection,
        job: dict[str, Any],
        candidate: dict[str, Any],
    ) -> UUID:
        payload = job["input_payload"]
        candidate_id = uuid4()
        connection.execute(
            insert(candidates).values(
                id=candidate_id,
                test_case_id=UUID(payload["case_id"]),
                base_revision_id=UUID(payload["base_revision_id"]),
                generation_job_id=job["id"],
                instruction=payload["instruction"],
                proposed_snapshot=candidate["proposed"],
                field_diff=candidate["diff"],
                reason=candidate["reason"],
                status="pending",
                created_by=job["account_id"],
                created_at=datetime.now(UTC),
            )
        )
        connection.execute(
            insert(audit_events).values(
                id=uuid4(),
                space_id=job["space_id"],
                actor_id=job["account_id"],
                action="candidate_revision.created",
                resource_type="test_case",
                resource_id=UUID(payload["case_id"]),
                payload={
                    "candidate_id": str(candidate_id),
                    "job_id": str(job["id"]),
                    "base_revision_id": payload["base_revision_id"],
                },
                created_at=datetime.now(UTC),
            )
        )
        return candidate_id

    def update_conversation_message(
        self,
        connection: Connection,
        message_id: UUID,
        **values: Any,
    ) -> None:
        connection.execute(
            update(conversation_messages)
            .where(conversation_messages.c.id == message_id)
            .values(**values)
        )

    def complete_job_message(
        self,
        connection: Connection,
        job: dict[str, Any],
        *,
        content: str,
        status: str = "completed",
        citations: list[dict[str, Any]] | None = None,
        metadata_values: dict[str, Any] | None = None,
    ) -> None:
        message_id = job["input_payload"].get("assistant_message_id")
        if not message_id:
            return
        values: dict[str, Any] = {"content": content, "status": status}
        if citations is not None:
            values["citations"] = citations
        if metadata_values is not None:
            values["metadata"] = metadata_values
        self.update_conversation_message(
            connection,
            UUID(str(message_id)),
            **values,
        )

    def fail_job_message(
        self,
        connection: Connection,
        job_id: UUID,
        error_code: str,
    ) -> None:
        friendly_message = {
            "ProviderResponseError": "模型返回内容暂时无法解析，请稍后重试或更换模型。",
            "TimeoutError": "模型响应超时，请稍后重试。",
            "ConnectionError": "网络连接中断，请检查网络后重试。",
            "GenerationQualityError": "候选用例未通过质量校验，请补充需求后重试。",
        }.get(error_code, "处理暂时未完成，请稍后重试。")
        connection.execute(
            update(conversation_messages)
            .where(conversation_messages.c.related_job_id == job_id)
            .values(
                status="failed",
                content=friendly_message,
                metadata={"error_kind": "provider_or_generation"},
            )
        )

    def persist_change_set(
        self,
        connection: Connection,
        *,
        job: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> None:
        change_set_id = UUID(str(job["input_payload"]["change_set_id"]))
        connection.execute(
            update(case_change_sets)
            .where(case_change_sets.c.id == change_set_id)
            .values(status="ready", items=items)
        )

    def create_grouped_candidate(
        self,
        connection: Connection,
        *,
        job: dict[str, Any],
        case_id: UUID,
        base_revision_id: UUID,
        instruction: str,
        candidate: dict[str, Any],
    ) -> UUID:
        candidate_id = uuid4()
        connection.execute(
            insert(candidates).values(
                id=candidate_id,
                test_case_id=case_id,
                base_revision_id=base_revision_id,
                generation_job_id=job["id"],
                instruction=instruction,
                proposed_snapshot=candidate["proposed"],
                field_diff=candidate["diff"],
                reason=candidate["reason"],
                status="pending",
                created_by=job["account_id"],
                created_at=datetime.now(UTC),
            )
        )
        return candidate_id

    def publish(self, job_id: UUID, event: dict[str, Any]) -> None:
        key = f"casepilot:generation:{job_id}:events"
        self.redis.rpush(key, json.dumps(event, ensure_ascii=False))
        self.redis.expire(key, 24 * 3600)
