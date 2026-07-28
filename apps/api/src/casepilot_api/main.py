import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis

from casepilot_api.auth import ensure_demo_account
from casepilot_api.auth import router as auth_router
from casepilot_api.case_management import router as case_management_router
from casepilot_api.config import get_settings
from casepilot_api.database import check_database

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(ensure_demo_account)
    yield


app = FastAPI(
    title="CasePilot API",
    version="0.1.0",
    description="CasePilot 本地用例管理与 QA 执行 API。AI 生成与改写当前未启用。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(case_management_router)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "casepilot-api",
        "generation": "disabled",
    }


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
