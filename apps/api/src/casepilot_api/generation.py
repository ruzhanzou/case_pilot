import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from celery import Celery
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from redis import Redis
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session
from casepilot_api.models import (
    Account,
    CaseCollection,
    Conversation,
    ConversationMessage,
    GenerationJob,
    GenerationJobStage,
    KnowledgeDocument,
    KnowledgeSource,
)
from casepilot_api.schemas import (
    GenerationAnswersRequest,
    GenerationJobView,
    GenerationStartRequest,
)

router = APIRouter(prefix="/api/v1", tags=["generation"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db_session)]
task_client = Celery(
    "casepilot-api",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)


@router.get("/generation-models")
def list_generation_models(account: CurrentAccount) -> dict[str, object]:
    del account
    if settings.ai_mode == "mock" or settings.agent_provider == "mock":
        return {
            "default_model_id": "auto",
            "models": [
                {
                    "id": "auto",
                    "label": "Mock Agent",
                    "provider": "本地验收",
                }
            ],
        }

    configured = [
        (model, model, settings.agent_provider_label)
        for model in settings.available_agent_models
    ]
    models: list[dict[str, str]] = []
    seen_labels: set[str] = set()
    for model_id, label, provider in configured:
        normalized_label = label.strip()
        if not normalized_label or normalized_label.casefold() in seen_labels:
            continue
        seen_labels.add(normalized_label.casefold())
        models.append(
            {
                "id": model_id,
                "label": normalized_label,
                "provider": provider,
            }
        )
    return {
        "default_model_id": models[0]["id"] if models else "auto",
        "models": models,
    }


def ensure_job_access(db: Session, account: Account, job_id: UUID) -> GenerationJob:
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
    require_space_membership(db, account.id, job.space_id)
    return job


STAGE_PROGRESS = {
    "queued": 0,
    "context.prepared": 10,
    "requirement.analyzed": 22,
    "generation.awaiting_input": 25,
    "feature.generated": 38,
    "test_point.generated": 52,
    "test_case.generated": 72,
    "enhancement.completed": 86,
    "quality.completed": 96,
    "completed": 100,
    "failed": 100,
    "cancelled": 100,
}


def public_error_code(error_code: str | None) -> str | None:
    if not error_code:
        return None
    if error_code in {"TimeoutError", "ConnectionError"}:
        return "provider_temporarily_unavailable"
    if error_code in {"ProviderResponseError", "ValidationError"}:
        return "provider_response_invalid"
    if error_code == "GenerationQualityError":
        return "generation_quality_blocked"
    return "generation_failed"


def job_view(db: Session, job: GenerationJob) -> GenerationJobView:
    output = job.output_payload or {}
    requirement = output.get("requirement", {})
    stages = db.scalars(
        select(GenerationJobStage)
        .where(GenerationJobStage.generation_job_id == job.id)
        .order_by(
            GenerationJobStage.created_at.asc(),
            GenerationJobStage.attempt.asc(),
        )
    ).all()
    return GenerationJobView(
        id=job.id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        stage=job.stage,
        space_id=job.space_id,
        progress=STAGE_PROGRESS.get(job.stage, 0),
        error_code=public_error_code(job.error_code),
        questions=[
            item
            for item in requirement.get("open_questions", [])
            if item.get("blocking")
        ],
        stages=[
            {
                "stage": stage.stage,
                "attempt": stage.attempt,
                "status": stage.status,
                "model": stage.model,
                "latency_ms": stage.latency_ms,
                "token_usage": stage.token_usage,
                "created_at": stage.created_at.isoformat(),
            }
            for stage in stages
        ],
        requirement=requirement,
        feature_points=output.get("feature_points", []),
        test_points=output.get("test_points", []),
        test_cases=output.get("test_cases", []),
        coverage_matrix=output.get("coverage_matrix", []),
        quality=output.get("quality", {}),
        source_refs=output.get("source_refs", []),
    )


@router.post("/generation-jobs", response_model=GenerationJobView, status_code=202)
def start_generation(
    payload: GenerationStartRequest,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    if not settings.is_agent_model_allowed(payload.model_id):
        raise HTTPException(status_code=422, detail="generation_model_not_configured")
    collection = db.scalar(
        select(CaseCollection).where(
            CaseCollection.id == payload.collection_id,
            CaseCollection.deleted_at.is_(None),
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="collection_not_found")
    require_space_membership(db, account.id, collection.space_id)
    if payload.document_ids:
        documents = db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id.in_(payload.document_ids),
                KnowledgeDocument.space_id == collection.space_id,
                KnowledgeDocument.status == "ready",
            )
        ).all()
        if len(documents) != len(set(payload.document_ids)):
            raise HTTPException(status_code=409, detail="documents_not_ready_or_inaccessible")
    if payload.knowledge_source_ids:
        sources = db.scalars(
            select(KnowledgeSource).where(
                KnowledgeSource.id.in_(payload.knowledge_source_ids),
                KnowledgeSource.space_id == collection.space_id,
                KnowledgeSource.status == "ready",
                KnowledgeSource.deleted_at.is_(None),
            )
        ).all()
        if len(sources) != len(set(payload.knowledge_source_ids)):
            raise HTTPException(status_code=409, detail="sources_not_ready_or_inaccessible")
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
            "document_ids": [str(item) for item in payload.document_ids],
            "knowledge_source_ids": [
                str(item) for item in payload.knowledge_source_ids
            ],
            "use_space_knowledge": payload.use_space_knowledge,
            "answers": {},
            "persist_cases": False,
        },
        output_payload={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    task_client.send_task(
        "casepilot.agent.generate",
        args=[str(job.id)],
        task_id=str(job.id),
    )
    return job_view(db, job)


@router.get("/generation-jobs/{job_id}", response_model=GenerationJobView)
def get_generation(
    job_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    job = ensure_job_access(db, account, job_id)
    return job_view(db, job)


@router.post(
    "/generation-jobs/{job_id}/answers",
    response_model=GenerationJobView,
    status_code=202,
)
def answer_generation_questions(
    job_id: UUID,
    payload: GenerationAnswersRequest,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    job = ensure_job_access(db, account, job_id)
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status != "awaiting_input":
        raise HTTPException(status_code=409, detail="generation_not_awaiting_input")
    input_payload = dict(job.input_payload)
    answers = dict(input_payload.get("answers", {}))
    answers.update({item.question_id: item.answer.strip() for item in payload.answers})
    input_payload["answers"] = answers
    job.input_payload = input_payload
    job.status = "queued"
    job.stage = "requirement.analyzed"
    job.error_code = None
    db.commit()
    Redis.from_url(settings.redis_url).delete(
        f"casepilot:generation:{job.id}:events"
    )
    task_client.send_task(
        "casepilot.agent.generate",
        args=[str(job.id)],
        task_id=str(job.id),
    )
    return job_view(db, job)


@router.post(
    "/generation-jobs/{job_id}/retry",
    response_model=GenerationJobView,
    status_code=202,
)
def retry_generation(
    job_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    job = ensure_job_access(db, account, job_id)
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status != "failed":
        raise HTTPException(status_code=409, detail="only_failed_generation_can_retry")
    job.status = "queued"
    job.error_code = None
    db.commit()
    Redis.from_url(settings.redis_url).delete(
        f"casepilot:generation:{job.id}:events"
    )
    task_client.send_task(
        "casepilot.agent.generate",
        args=[str(job.id)],
        task_id=str(job.id),
    )
    return job_view(db, job)


@router.post(
    "/generation-jobs/{job_id}/cancel",
    response_model=GenerationJobView,
)
def cancel_generation(
    job_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> GenerationJobView:
    job = ensure_job_access(db, account, job_id)
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status in {"completed", "failed", "cancelled"}:
        if status == "cancelled":
            return job_view(db, job)
        raise HTTPException(status_code=409, detail="generation_job_already_terminal")
    cancelled_id = db.scalar(
        update(GenerationJob)
        .where(
            GenerationJob.id == job.id,
            GenerationJob.status.in_(
                ("queued", "running", "awaiting_input")
            ),
        )
        .values(
            status="cancelled",
            stage="cancelled",
            error_code=None,
        )
        .returning(GenerationJob.id)
    )
    if cancelled_id is None:
        db.expire(job)
        db.refresh(job)
        fresh_status = (
            job.status.value if hasattr(job.status, "value") else str(job.status)
        )
        if fresh_status == "cancelled":
            return job_view(db, job)
        raise HTTPException(status_code=409, detail="generation_job_already_terminal")
    db.execute(
        update(ConversationMessage)
        .where(ConversationMessage.related_job_id == job.id)
        .values(
            status="cancelled",
            content="已停止生成。已确认的结构化测试说明仍保留，可随时重新开始。",
            message_metadata={"cancelled": True},
        )
    )
    conversation_id = job.input_payload.get("conversation_id")
    if conversation_id:
        conversation = db.get(Conversation, UUID(str(conversation_id)))
        if conversation is not None:
            conversation.context = {
                **dict(conversation.context),
                "phase": (
                    "brief_review"
                    if conversation.context.get("confirmed_brief_version")
                    else "idle"
                ),
                "active_job_id": None,
            }
    db.commit()
    task_client.control.revoke(str(job.id), terminate=False)
    Redis.from_url(settings.redis_url, decode_responses=True).rpush(
        f"casepilot:generation:{job.id}:events",
        json.dumps(
            {
                "event": "generation.cancelled",
                "job_id": str(job.id),
                "status": "cancelled",
                "progress": 100,
            },
            ensure_ascii=False,
        ),
    )
    db.refresh(job)
    return job_view(db, job)


async def event_stream(job_id: UUID, start_cursor: int = 0) -> AsyncIterator[str]:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    key = f"casepilot:generation:{job_id}:events"
    cursor = max(0, start_cursor)
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
                    "generation.awaiting_input",
                    "generation.completed",
                    "generation.failed",
                    "generation.cancelled",
                    "rewrite.completed",
                    "rewrite.failed",
                    "brief.completed",
                    "brief.failed",
                    "qa.completed",
                    "qa.failed",
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
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    ensure_job_access(db, account, job_id)
    try:
        cursor = int(last_event_id or 0)
    except ValueError:
        cursor = 0
    return StreamingResponse(
        event_stream(job_id, cursor),
        media_type="text/event-stream",
    )
