import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session
from casepilot_api.models import Account, CaseCollection, GenerationJob
from casepilot_api.schemas import GenerationJobView, GenerationStartRequest

router = APIRouter(prefix="/api/v1", tags=["generation"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db_session)]
task_client = Celery(
    "casepilot-api",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)


def ensure_job_access(db: Session, account: Account, job_id: UUID) -> GenerationJob:
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
    require_space_membership(db, account.id, job.space_id)
    return job


@router.post("/generation-jobs", response_model=GenerationJobView, status_code=202)
def start_generation(
    payload: GenerationStartRequest,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    collection = db.scalar(
        select(CaseCollection).where(
            CaseCollection.id == payload.collection_id,
            CaseCollection.deleted_at.is_(None),
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    require_space_membership(db, account.id, collection.space_id)
    job = GenerationJob(
        space_id=collection.space_id,
        account_id=account.id,
        operation="generate",
        collection_id=collection.id,
        status="queued",
        stage="queued",
        input_payload={
            "prompt": payload.prompt,
            "markdown_content": payload.markdown_content,
            "file_names": payload.file_names,
            "mode": settings.ai_mode,
            "model_id": payload.model_id,
            "persist_cases": False,
        },
        output_payload={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    task_client.send_task("casepilot.agent.generate", args=[str(job.id)])
    return GenerationJobView(
        id=job.id,
        status=job.status,
        stage=job.stage,
        space_id=job.space_id,
    )


@router.get("/generation-jobs/{job_id}", response_model=GenerationJobView)
def get_generation(
    job_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    job = ensure_job_access(db, account, job_id)
    return GenerationJobView(
        id=job.id,
        status=job.status,
        stage=job.stage,
        space_id=job.space_id,
    )


async def event_stream(job_id: UUID) -> AsyncIterator[str]:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    key = f"casepilot:generation:{job_id}:events"
    cursor = 0
    idle_cycles = 0
    while idle_cycles < 300:
        events = await asyncio.to_thread(redis_client.lrange, key, cursor, -1)
        if events:
            idle_cycles = 0
            for raw_event in events:
                cursor += 1
                event = json.loads(raw_event)
                event_name = event.pop("event")
                payload = json.dumps(event, ensure_ascii=False)
                yield f"id: {cursor}\nevent: {event_name}\ndata: {payload}\n\n"
                if event_name in {
                    "generation.completed",
                    "generation.failed",
                    "rewrite.completed",
                    "rewrite.failed",
                }:
                    return
        else:
            idle_cycles += 1
            yield ": keep-alive\n\n"
        await asyncio.sleep(0.25)


@router.get("/generation-jobs/{job_id}/events")
def stream_generation(
    job_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> StreamingResponse:
    ensure_job_access(db, account, job_id)
    return StreamingResponse(event_stream(job_id), media_type="text/event-stream")
