from uuid import UUID

from celery import Celery

from casepilot_agent.config import get_settings
from casepilot_agent.contracts import GenerationRequest, RewriteRequest, TestCaseDraft
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


def fail_job(store: JobStore, job_id: UUID, event_name: str, error: Exception) -> None:
    with store.connection() as connection:
        store.update_job(
            connection,
            job_id,
            status="failed",
            stage="failed",
            error_code=error.__class__.__name__,
        )
    store.publish(
        job_id,
        {
            "event": event_name,
            "job_id": str(job_id),
            "status": "failed",
            "error_code": error.__class__.__name__,
        },
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
    try:
        with store.connection() as connection:
            job = store.get_job(connection, parsed_job_id)
            store.update_job(connection, parsed_job_id, status="running")
        payload = job["input_payload"]
        request = GenerationRequest(
            prompt=str(payload["prompt"]),
            markdown_content=str(payload.get("markdown_content", "")),
            file_names=list(payload.get("file_names", [])),
            model_id=str(payload.get("model_id", "auto")),
        )
        pipeline = GenerationPipeline(create_provider(settings.provider))

        def publish_progress(stage: str, sequence: int, detail: dict) -> None:
            with store.connection() as connection:
                store.update_job(connection, parsed_job_id, stage=stage)
            store.publish(
                parsed_job_id,
                {
                    "event": stage,
                    "job_id": job_id,
                    "sequence": sequence,
                    "progress": sequence * 20,
                    **detail,
                },
            )

        result = pipeline.run(request, on_progress=publish_progress)
        output = result.model_dump(mode="json")
        with store.connection() as connection:
            case_ids = store.persist_generation(connection, job, output)
            completed = {**output, "case_ids": case_ids}
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=completed,
                error_code=None,
            )
        store.publish(
            parsed_job_id,
            {
                "event": "generation.completed",
                "job_id": job_id,
                "status": "completed",
                **completed,
            },
        )
        return completed
    except Exception as error:
        fail_job(store, parsed_job_id, "generation.failed", error)
        raise


@celery_app.task(name="casepilot.agent.rewrite")
def rewrite_test_case(job_id: str) -> dict:
    parsed_job_id = UUID(job_id)
    store = JobStore(settings.database_url, settings.redis_url)
    try:
        with store.connection() as connection:
            job = store.get_job(connection, parsed_job_id)
            payload = job["input_payload"]
            snapshot = store.load_case_snapshot(
                connection,
                UUID(payload["case_id"]),
                UUID(payload["base_revision_id"]),
            )
            store.update_job(connection, parsed_job_id, status="running", stage="rewriting")
        pipeline = GenerationPipeline(create_provider(settings.provider))
        candidate = pipeline.rewrite(
            RewriteRequest(
                test_case=TestCaseDraft.model_validate(snapshot),
                instruction=payload["instruction"],
                model_id=payload.get("model_id", "auto"),
            )
        )
        output = candidate.model_dump(mode="json")
        with store.connection() as connection:
            candidate_id = store.persist_candidate(connection, job, output)
            completed = {**output, "candidate_revision_id": str(candidate_id)}
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=completed,
            )
        store.publish(
            parsed_job_id,
            {
                "event": "rewrite.completed",
                "job_id": job_id,
                "status": "completed",
                **completed,
            },
        )
        return completed
    except Exception as error:
        fail_job(store, parsed_job_id, "rewrite.failed", error)
        raise
