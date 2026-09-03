import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis
from starlette.responses import Response

from casepilot_api.auth import ensure_demo_account
from casepilot_api.auth import router as auth_router
from casepilot_api.case_management import router as case_management_router
from casepilot_api.cases import router as candidate_router
from casepilot_api.config import get_settings
from casepilot_api.conversations import router as conversation_router
from casepilot_api.database import check_database
from casepilot_api.generation import router as generation_router
from casepilot_api.knowledge import router as knowledge_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.seed_demo_data:
        await asyncio.to_thread(ensure_demo_account)
    yield


app = FastAPI(
    title="CasePilot API",
    version="1.0.0",
    description="CasePilot 本地用例管理、AI 测试设计与 QA 执行 API。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_web_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(case_management_router)
app.include_router(generation_router)
app.include_router(knowledge_router)
app.include_router(candidate_router)
app.include_router(conversation_router)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "casepilot-api",
        "generation": settings.ai_mode,
    }


@app.get("/health/ready", response_model=None)
async def ready() -> Response:
    checks: dict[str, str] = {}
    try:
        await asyncio.to_thread(check_database)
        checks["postgres"] = "ok"
    except Exception as error:
        checks["postgres"] = f"unavailable: {error.__class__.__name__}"

    redis_client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        await asyncio.to_thread(redis_client.ping)
        checks["redis"] = "ok"
    except Exception as error:
        checks["redis"] = f"unavailable: {error.__class__.__name__}"

    finally:
        redis_client.close()

    status_code = 200 if all(value == "ok" for value in checks.values()) else 503
    status_text = "ok" if status_code == 200 else "degraded"
    return JSONResponse(status_code=status_code, content={"status": status_text, **checks})
