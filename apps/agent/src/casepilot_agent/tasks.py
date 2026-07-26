from uuid import UUID

from celery import Celery

from casepilot_agent.config import get_settings
from casepilot_agent.contracts import GenerationRequest
from casepilot_agent.pipeline import GenerationPipeline
from casepilot_agent.providers import create_provider
from casepilot_agent.store import JobStore

settings = get_settings()
celery_app = Celery(
    "casepilot-agent",
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


@celery_app.task(
    name="casepilot.agent.generate",
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_test_cases(job_id: str) -> dict:
    parsed_job_id = UUID(job_id)
    store = JobStore(settings.database_url, settings.redis_url)

    with store.connection() as connection:
        payload = store.get_input(connection, parsed_job_id)
        store.update_job(connection, parsed_job_id, status="running")

    request = GenerationRequest(
        prompt=str(payload["prompt"]),
        file_names=list(payload.get("file_names", [])),
        model_id=str(payload.get("model_id", "auto")),
    )
    pipeline = GenerationPipeline(create_provider(settings.provider))

    def publish_progress(stage: str, sequence: int, total: int) -> None:
        with store.connection() as connection:
            store.update_job(connection, parsed_job_id, stage=stage)
        store.publish(
            parsed_job_id,
            {
                "event": "generation.progress",
                "job_id": job_id,
                "sequence": sequence,
                "stage": stage,
                "progress": round(sequence / total * 100),
                "status": "running",
            },
        )

    try:
        result = pipeline.run(request, on_progress=publish_progress)
        output = result.model_dump(mode="json")
        with store.connection() as connection:
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=output,
                error_code=None,
            )
        store.publish(
            parsed_job_id,
            {
                "event": "generation.completed",
                "job_id": job_id,
                "sequence": len(result.stages) + 1,
                "status": "completed",
                "risks": output["risks"],
                "test_cases": output["test_cases"],
            },
        )
        return output
    except Exception as error:
        with store.connection() as connection:
            store.update_job(
                connection,
                parsed_job_id,
                status="failed",
                stage="failed",
                error_code=error.__class__.__name__,
            )
        store.publish(
            parsed_job_id,
            {
                "event": "generation.failed",
                "job_id": job_id,
                "status": "failed",
                "error_code": error.__class__.__name__,
            },
        )
        raise
