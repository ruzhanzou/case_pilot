import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from redis import Redis
from sqlalchemy import JSON, Column, MetaData, String, Table, create_engine, select, update
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Connection

metadata = MetaData()
generation_jobs = Table(
    "generation_jobs",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column(
        "status",
        ENUM(
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            name="generation_status",
            create_type=False,
        ),
    ),
    Column("stage", String),
    Column("input_payload", JSON),
    Column("output_payload", JSON),
    Column("error_code", String),
)


class JobStore:
    def __init__(self, database_url: str, redis_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    @contextmanager
    def connection(self):
        with self.engine.begin() as connection:
            yield connection

    def get_input(self, connection: Connection, job_id: UUID) -> dict[str, Any]:
        payload = connection.execute(
            select(generation_jobs.c.input_payload).where(generation_jobs.c.id == job_id)
        ).scalar_one_or_none()
        if payload is None:
            raise ValueError("generation_job_not_found")
        return dict(payload)

    def update_job(self, connection: Connection, job_id: UUID, **values: Any) -> None:
        connection.execute(
            update(generation_jobs).where(generation_jobs.c.id == job_id).values(**values)
        )

    def publish(self, job_id: UUID, event: dict[str, Any]) -> None:
        key = f"casepilot:generation:{job_id}:events"
        self.redis.rpush(key, json.dumps(event, ensure_ascii=False))
        self.redis.expire(key, 24 * 3600)
