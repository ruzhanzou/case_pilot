import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from redis import Redis

from casepilot_api.auth import router as auth_router
from casepilot_api.config import get_settings
from casepilot_api.database import check_database
from casepilot_api.generation import router as generation_router
from casepilot_api.mock_ai import create_mock_job
from casepilot_api.schemas import MockGenerationJob, MockGenerationRequest

settings = get_settings()
app = FastAPI(
    title="CasePilot API",
    version="0.1.0",
    description="CasePilot 本地开发 API。AI 能力当前使用可重复的 Mock 数据。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(generation_router)

JOBS: dict[UUID, MockGenerationJob] = {}


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "service": "casepilot-api", "ai_mode": settings.ai_mode}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        await asyncio.to_thread(check_database)
        checks["postgres"] = "ok"
    except Exception as error:
        checks["postgres"] = f"unavailable: {error.__class__.__name__}"

    try:
        redis_client = Redis.from_url(settings.redis_url, socket_timeout=1)
        await asyncio.to_thread(redis_client.ping)
        checks["redis"] = "ok"
    except Exception as error:
        checks["redis"] = f"unavailable: {error.__class__.__name__}"

    overall = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": overall, **checks}


@app.post("/api/v1/mock/generation-jobs", response_model=MockGenerationJob, status_code=202)
async def start_mock_generation(payload: MockGenerationRequest) -> MockGenerationJob:
    job = create_mock_job(payload)
    JOBS[job.id] = job
    return job


@app.get("/api/v1/mock/generation-jobs/{job_id}", response_model=MockGenerationJob)
async def get_mock_generation(job_id: UUID) -> MockGenerationJob:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
    return job


async def mock_event_stream(job: MockGenerationJob) -> AsyncIterator[str]:
    for index, stage in enumerate(job.stages):
        payload = {
            "sequence": index + 1,
            "job_id": str(job.id),
            "stage": stage,
            "progress": round(((index + 1) / len(job.stages)) * 100),
            "status": "running",
        }
        data = json.dumps(payload, ensure_ascii=False)
        yield f"id: {index + 1}\nevent: generation.progress\ndata: {data}\n\n"
        await asyncio.sleep(0.65)

    job.status = "completed"
    payload = {
        "sequence": len(job.stages) + 1,
        "job_id": str(job.id),
        "status": "completed",
        "risks": [risk.model_dump() for risk in job.risks],
        "test_cases": [case.model_dump() for case in job.test_cases],
    }
    yield f"event: generation.completed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/v1/mock/generation-jobs/{job_id}/events")
async def stream_mock_generation(job_id: UUID) -> StreamingResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
    return StreamingResponse(mock_event_stream(job), media_type="text/event-stream")
