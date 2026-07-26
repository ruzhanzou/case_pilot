import json
import time
from uuid import UUID

from celery import Celery
from redis import Redis
from sqlalchemy import select

from casepilot_api.config import get_settings
from casepilot_api.database import get_session_factory
from casepilot_api.mock_ai import create_mock_job
from casepilot_api.models import GenerationJob, GenerationStatus
from casepilot_api.schemas import MockGenerationRequest

settings = get_settings()
celery_app = Celery(
    "casepilot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    task_track_started=True,
)


def publish_event(redis_client: Redis, job_id: UUID, event: dict) -> None:
    key = f"casepilot:generation:{job_id}:events"
    redis_client.rpush(key, json.dumps(event, ensure_ascii=False))
    redis_client.expire(key, 24 * 3600)


@celery_app.task(
    name="casepilot.mock.generate",
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_mock_test_cases(job_id: str) -> dict:
    parsed_job_id = UUID(job_id)
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.scalar(select(GenerationJob).where(GenerationJob.id == parsed_job_id))
        if job is None:
            raise ValueError("generation_job_not_found")
        payload = MockGenerationRequest(
            prompt=str(job.input_payload["prompt"]),
            file_names=list(job.input_payload.get("file_names", [])),
        )
        mock_result = create_mock_job(payload)
        job.status = GenerationStatus.RUNNING
        db.commit()

        try:
            for index, stage in enumerate(mock_result.stages):
                job.stage = stage
                db.commit()
                publish_event(
                    redis_client,
                    parsed_job_id,
                    {
                        "event": "generation.progress",
                        "job_id": job_id,
                        "sequence": index + 1,
                        "stage": stage,
                        "progress": round(
                            ((index + 1) / len(mock_result.stages)) * 100
                        ),
                        "status": "running",
                    },
                )
                time.sleep(0.55)

            mock_result.status = "completed"
            result = mock_result.model_dump(mode="json")
            job.status = GenerationStatus.COMPLETED
            job.stage = "completed"
            job.output_payload = result
            db.commit()
            publish_event(
                redis_client,
                parsed_job_id,
                {
                    "event": "generation.completed",
                    "job_id": job_id,
                    "sequence": len(mock_result.stages) + 1,
                    "status": "completed",
                    "risks": result["risks"],
                    "test_cases": result["test_cases"],
                },
            )
            return result
        except Exception as error:
            job.status = GenerationStatus.FAILED
            job.stage = "failed"
            job.error_code = error.__class__.__name__
            db.commit()
            publish_event(
                redis_client,
                parsed_job_id,
                {
                    "event": "generation.failed",
                    "job_id": job_id,
                    "status": "failed",
                    "error_code": error.__class__.__name__,
                },
            )
            raise
