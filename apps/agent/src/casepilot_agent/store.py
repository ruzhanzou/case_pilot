import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from redis import Redis
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
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
    "completed",
    "failed",
    "cancelled",
    name="generation_status",
    create_type=False,
)
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

    def update_job(self, connection: Connection, job_id: UUID, **values: Any) -> None:
        connection.execute(
            update(generation_jobs).where(generation_jobs.c.id == job_id).values(**values)
        )

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

    def publish(self, job_id: UUID, event: dict[str, Any]) -> None:
        key = f"casepilot:generation:{job_id}:events"
        self.redis.rpush(key, json.dumps(event, ensure_ascii=False))
        self.redis.expire(key, 24 * 3600)
