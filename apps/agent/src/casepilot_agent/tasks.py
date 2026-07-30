from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import Any
from uuid import UUID

from celery import Celery
from sqlalchemy import delete, select, update

from casepilot_agent.config import get_settings
from casepilot_agent.contracts import (
    EmbeddingProvider,
    GenerationRequest,
    KnowledgeAnswer,
    QualityIssue,
    RequirementAnalysis,
    RewriteRequest,
    StructuredResultT,
    TestCaseDraft,
)
from casepilot_agent.knowledge import (
    attach_embeddings,
    build_chunks,
    parse_document,
    pretokenize,
)
from casepilot_agent.pipeline import (
    AwaitingInput,
    GenerationPipeline,
    GenerationQualityError,
    enforce_test_object_clarification,
    extract_explicit_test_object,
)
from casepilot_agent.providers import create_embedding_provider, create_provider
from casepilot_agent.store import (
    JobStore,
    case_change_sets,
    knowledge_chunks,
    knowledge_documents,
    knowledge_sources,
)

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
    beat_schedule={
        "cleanup-expired-temporary-knowledge": {
            "task": "casepilot.agent.cleanup_expired_knowledge",
            "schedule": 3600.0,
        }
    },
)

STAGE_PROGRESS = {
    "context.prepared": 10,
    "requirement.analyzed": 22,
    "generation.awaiting_input": 25,
    "feature.generated": 38,
    "test_point.generated": 52,
    "test_case.generated": 72,
    "enhancement.completed": 86,
    "quality.completed": 96,
}


class GenerationCancelled(RuntimeError):
    pass


def ensure_not_cancelled(store: JobStore, job_id: UUID) -> None:
    with store.connection() as connection:
        if store.is_cancelled(connection, job_id):
            raise GenerationCancelled("generation_cancelled")


def fail_job(store: JobStore, job_id: UUID, event_name: str, error: Exception) -> None:
    with store.connection() as connection:
        if store.is_cancelled(connection, job_id):
            return
        store.update_job(
            connection,
            job_id,
            status="failed",
            stage="failed",
            error_code=error.__class__.__name__,
        )
        store.fail_job_message(connection, job_id, error.__class__.__name__)
    store.publish(
        job_id,
        {
            "event": event_name,
            "job_id": str(job_id),
            "status": "failed",
            "error_code": error.__class__.__name__,
        },
    )


def _context_payload(
    store: JobStore,
    job: dict[str, Any],
    embedding_provider: EmbeddingProvider | None,
) -> dict[str, Any]:
    payload = job["input_payload"]
    query = " ".join(
        item
        for item in (
            str(payload.get("prompt", "")),
            str(payload.get("markdown_content", ""))[:3000],
        )
        if item
    )
    stage_input = {
        "query": query,
        "source_ids": payload.get("knowledge_source_ids", []),
        "document_ids": payload.get("document_ids", []),
        "use_space_knowledge": payload.get("use_space_knowledge", True),
        "embedding_provider": (
            embedding_provider.name if embedding_provider is not None else "disabled"
        ),
    }
    with store.connection() as connection:
        completed = store.load_completed_stage(
            connection,
            job["id"],
            "context.prepared",
            stage_input,
        )
        if completed:
            return completed["output_payload"]
    should_retrieve = bool(
        payload.get("use_space_knowledge", True)
        or payload.get("knowledge_source_ids")
        or payload.get("document_ids")
    )
    query_embedding: list[float] | None = None
    embedding_error: str | None = None
    if should_retrieve and embedding_provider is not None:
        try:
            query_embedding = embedding_provider.embed([query])[0]
        except Exception as error:
            if not settings.embedding_fallback_enabled:
                raise
            embedding_error = error.__class__.__name__
    elif should_retrieve:
        embedding_error = "EmbeddingProviderDisabled"
    with store.connection() as connection:
        rows = (
            store.retrieve_context(
                connection,
                space_id=job["space_id"],
                query=query,
                search_query=pretokenize(query),
                query_embedding=query_embedding,
                source_ids=[
                    UUID(item) for item in payload.get("knowledge_source_ids", [])
                ],
                document_ids=[UUID(item) for item in payload.get("document_ids", [])],
                use_space_knowledge=bool(payload.get("use_space_knowledge", True)),
            )
            if should_retrieve
            else []
        )
        evidence = [
            {
                "source_id": str(row["source_id"]),
                "document_id": str(row["document_id"]),
                "chunk_id": str(row["id"]),
                "label": row["document_name"],
                "locator": row["locator"],
                "excerpt": row["content"][:800],
                "rank": rank,
                "scores": {
                    "rrf": float(row["rrf"]),
                    "vector": (
                        1.0 - float(row["distance"])
                        if row["distance"] is not None
                        else 0.0
                    ),
                    "lexical": float(row["lexical"] or 0.0),
                },
            }
            for rank, row in enumerate(rows, start=1)
        ]
        retrieval_mode = (
            "none"
            if not should_retrieve
            else "hybrid"
            if query_embedding is not None
            else "lexical"
        )
        warnings = (
            [
                {
                    "code": "embedding_retrieval_degraded",
                    "message": (
                        "Embedding 暂不可用，本次已降级为全文与精确匹配检索；"
                        "语义召回可能减少。"
                    ),
                    "severity": "warning",
                    "diagnostic": embedding_error,
                }
            ]
            if embedding_error
            else []
        )
        output = {
            "query": query,
            "evidence": evidence,
            "retrieval_mode": retrieval_mode,
            "warnings": warnings,
        }
        store.persist_evidence(
            connection,
            job["id"],
            "context.prepared",
            query,
            rows,
        )
        store.record_stage(
            connection,
            job_id=job["id"],
            stage="context.prepared",
            input_payload=stage_input,
            output_payload=output,
            status="completed",
            model=(
                embedding_provider.name
                if query_embedding is not None and embedding_provider is not None
                else f"{retrieval_mode}:retrieval"
            ),
        )
        store.update_job(
            connection,
            job["id"],
            status="running",
            stage="context.prepared",
            output_payload={"context": output},
        )
    store.publish(
        job["id"],
        {
            "event": "context.prepared",
            "job_id": str(job["id"]),
            "progress": STAGE_PROGRESS["context.prepared"],
            "evidence_count": len(evidence),
            "retrieval_mode": retrieval_mode,
            "warnings": warnings,
        },
    )
    return output


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if not denominator:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _apply_persisted_asset_quality(
    store: JobStore,
    job: dict[str, Any],
    embedding_provider: EmbeddingProvider | None,
    context: dict[str, Any],
    result: Any,
) -> None:
    existing_issue_codes = {issue.code for issue in result.quality.issues}
    for warning in context.get("warnings", []):
        if warning.get("code") not in existing_issue_codes:
            result.quality.issues.append(
                QualityIssue(
                    code=str(warning.get("code", "retrieval_degraded")),
                    message=str(warning.get("message", "知识检索已降级")),
                )
            )
            existing_issue_codes.add(str(warning.get("code")))
    allowed_refs = {
        (
            item.get("source_id"),
            item.get("document_id"),
            item.get("chunk_id"),
        )
        for item in context.get("evidence", [])
    }
    for case in result.test_cases:
        for source_ref in case.source_refs:
            identity = (
                source_ref.source_id,
                source_ref.document_id,
                source_ref.chunk_id,
            )
            if any(identity) and identity not in allowed_refs:
                result.quality.issues.append(
                    QualityIssue(
                        code="invalid_source_reference",
                        message="来源引用不存在、越权或未用于当前生成阶段",
                        object_id=case.id,
                        severity="error",
                    )
                )
    with store.connection() as connection:
        existing = store.load_existing_case_titles(
            connection,
            job["collection_id"],
        )
    if existing and result.test_cases:
        existing_titles = [item["title"] for item in existing]
        generated_titles = [item.title for item in result.test_cases]
        normalized_existing = {
            title.strip().casefold(): index
            for index, title in enumerate(existing_titles)
        }
        exact_duplicate_ids: set[str] = set()
        for case in result.test_cases:
            existing_index = normalized_existing.get(case.title.strip().casefold())
            if existing_index is not None:
                exact_duplicate_ids.add(case.id)
                result.quality.issues.append(
                    QualityIssue(
                        code="possible_existing_case_duplicate",
                        message=(
                            f"疑似与已有用例 {existing[existing_index]['case_key']} 重复"
                            "（标题完全一致）"
                        ),
                        object_id=case.id,
                    )
                )
        try:
            if embedding_provider is None:
                raise RuntimeError("embedding_provider_unavailable")
            vectors = embedding_provider.embed([*existing_titles, *generated_titles])
            split = len(existing_titles)
            for case, vector in zip(
                result.test_cases,
                vectors[split:],
                strict=True,
            ):
                if case.id in exact_duplicate_ids:
                    continue
                best_index, _ = max(
                    enumerate(vectors[:split]),
                    key=lambda item: _cosine_similarity(item[1], vector),
                )
                similarity = _cosine_similarity(vectors[best_index], vector)
                if similarity >= 0.92:
                    result.quality.issues.append(
                        QualityIssue(
                            code="possible_existing_case_duplicate",
                            message=(
                                f"疑似与已有用例 {existing[best_index]['case_key']} 重复"
                                f"（相似度 {similarity:.2f}）"
                            ),
                            object_id=case.id,
                        )
                    )
        except Exception:
            if not settings.embedding_fallback_enabled:
                raise
            result.quality.issues.append(
                QualityIssue(
                    code="semantic_duplicate_check_degraded",
                    message=(
                        "Embedding 暂不可用，已保留标题精确去重并跳过语义去重；"
                        "请在人工评审时关注相似用例。"
                    ),
                )
            )
    errors = [
        issue for issue in result.quality.issues if issue.severity == "error"
    ]
    result.quality.passed = not errors
    result.quality.score = max(
        0,
        100
        - len(errors) * 25
        - len([issue for issue in result.quality.issues if issue.severity != "error"])
        * 8,
    )


@celery_app.task(name="casepilot.agent.draft_brief")
def draft_test_brief(job_id: str) -> dict[str, Any]:
    parsed_job_id = UUID(job_id)
    store = JobStore(settings.database_url, settings.redis_url)
    provider = create_provider(settings.provider)
    try:
        embedding_provider = create_embedding_provider()
    except Exception:
        if not settings.embedding_fallback_enabled:
            raise
        embedding_provider = None
    try:
        with store.connection() as connection:
            job = store.get_job_for_update(connection, parsed_job_id)
            if str(getattr(job["status"], "value", job["status"])) == "cancelled":
                raise GenerationCancelled("generation_cancelled")
            store.update_job(
                connection,
                parsed_job_id,
                status="running",
                stage="context.prepared",
                error_code=None,
            )
        context = _context_payload(store, job, embedding_provider)
        ensure_not_cancelled(store, parsed_job_id)
        payload = job["input_payload"]
        stage_input = {
            "prompt": str(payload["prompt"]),
            "context": context,
            "current_test_brief": payload.get("current_test_brief"),
            "conversation_memory": list(payload.get("conversation_memory", [])),
        }
        requirement, usage = provider.complete(
            stage="requirement.analyzed",
            instruction=(
                "你是 CasePilot。只整理结构化测试说明，不生成测试点或测试用例。"
                "若用户在修改已有说明，应完整合并其修改并保留未被推翻的信息。"
                "先判断用户是否明确指定测试对象，写入 test_object 和 "
                "test_object_specified。若缺少测试对象，只提出一个测试对象澄清项；"
                "角色、流程、规则、约束、风险等其他内容均由你结合上下文分析，"
                "必要时记录为假设，不得要求用户澄清。"
            ),
            payload=stage_input,
            result_type=RequirementAnalysis,
            model_id=str(payload.get("model_id", "auto")),
        )
        provided_test_object = str(payload.get("provided_test_object", "")).strip()
        if not provided_test_object:
            provided_test_object = extract_explicit_test_object(str(payload["prompt"]))
        requirement = enforce_test_object_clarification(
            requirement,
            {"Q-TEST-OBJECT": provided_test_object}
            if provided_test_object
            else None,
        )
        ensure_not_cancelled(store, parsed_job_id)
        raw = requirement.model_dump(mode="json")
        content = {
            "test_object": raw["test_object"],
            "test_objective": raw["summary"],
            "scope": list(raw.get("flows", [])),
            "roles": list(raw.get("actors", [])),
            "core_flows": list(raw.get("flows", [])),
            "business_rules": list(raw.get("business_rules", [])),
            "constraints": list(raw.get("constraints", [])),
            "risks": list(raw.get("risks", [])),
            "coverage_dimensions": [
                "正常",
                "权限",
                "异常",
                "边界",
                "性能",
                "兼容性",
                "稳定性",
                "隐私",
            ],
            "assumptions": list(raw.get("assumptions", [])),
            "open_questions": list(raw.get("open_questions", [])),
        }
        with store.connection() as connection:
            locked_job = store.get_job_for_update(connection, parsed_job_id)
            if str(
                getattr(locked_job["status"], "value", locked_job["status"])
            ) == "cancelled":
                raise GenerationCancelled("generation_cancelled")
            store.record_stage(
                connection,
                job_id=parsed_job_id,
                stage="requirement.analyzed",
                input_payload=stage_input,
                output_payload=raw,
                status="completed",
                model=usage.model,
                latency_ms=usage.latency_ms,
                token_usage=usage.token_usage,
            )
            version = store.persist_test_brief(connection, job, content)
            output = {"test_brief": content, "version": version}
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=output,
                error_code=None,
            )
            blocker_count = sum(
                bool(item.get("blocking")) for item in content["open_questions"]
            )
            store.complete_job_message(
                connection,
                job,
                content=(
                    f"结构化测试说明 V{version} 已整理完成。"
                    + (
                        "尚未明确测试对象，请补充后再生成用例。"
                        if blocker_count
                        else "你可以继续修改；确认无误后再开始生成候选用例。"
                    )
                ),
                metadata_values={
                    "brief_version": version,
                    "brief_operation": str(
                        payload.get("brief_operation", "draft")
                    ),
                    "artifact_type": "test_brief",
                    "blocking_question_count": blocker_count,
                },
            )
        store.publish(
            parsed_job_id,
            {
                "event": "brief.completed",
                "job_id": job_id,
                "status": "completed",
                **output,
            },
        )
        return output
    except GenerationCancelled:
        return {"job_id": job_id, "status": "cancelled"}
    except Exception as error:
        fail_job(store, parsed_job_id, "brief.failed", error)
        raise


@celery_app.task(
    name="casepilot.agent.generate",
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_test_cases(job_id: str) -> dict[str, Any]:
    parsed_job_id = UUID(job_id)
    store = JobStore(settings.database_url, settings.redis_url)
    provider = create_provider(settings.provider)
    try:
        embedding_provider = create_embedding_provider()
    except Exception:
        if not settings.embedding_fallback_enabled:
            raise
        embedding_provider = None
    partial_output: dict[str, Any] = {}
    try:
        with store.connection() as connection:
            job = store.get_job_for_update(connection, parsed_job_id)
            if str(getattr(job["status"], "value", job["status"])) == "cancelled":
                raise GenerationCancelled("generation_cancelled")
            store.update_job(
                connection,
                parsed_job_id,
                status="running",
                error_code=None,
            )
        payload = job["input_payload"]
        request = GenerationRequest(
            prompt=str(payload["prompt"]),
            markdown_content=str(payload.get("markdown_content", "")),
            file_names=list(payload.get("file_names", [])),
            conversation_memory=list(payload.get("conversation_memory", [])),
            model_id=str(payload.get("model_id", "auto")),
        )
        ensure_not_cancelled(store, parsed_job_id)
        context = _context_payload(store, job, embedding_provider)
        ensure_not_cancelled(store, parsed_job_id)
        partial_output["context"] = context
        pipeline = GenerationPipeline(provider)

        def execute_stage(
            stage: str,
            instruction: str,
            stage_input: dict[str, Any],
            result_type: type[StructuredResultT],
            model_id: str,
        ) -> StructuredResultT:
            ensure_not_cancelled(store, parsed_job_id)
            with store.connection() as connection:
                completed = store.load_completed_stage(
                    connection,
                    parsed_job_id,
                    stage,
                    stage_input,
                )
                if completed:
                    result = result_type.model_validate(completed["output_payload"])
                else:
                    result, usage = provider.complete(
                        stage=stage,
                        instruction=instruction,
                        payload=stage_input,
                        result_type=result_type,
                        model_id=model_id,
                    )
                    if store.is_cancelled(connection, parsed_job_id):
                        raise GenerationCancelled("generation_cancelled")
                    store.record_stage(
                        connection,
                        job_id=parsed_job_id,
                        stage=stage,
                        input_payload=stage_input,
                        output_payload=result.model_dump(mode="json"),
                        status="completed",
                        model=usage.model,
                        latency_ms=usage.latency_ms,
                        token_usage=usage.token_usage,
                    )
                stage_output = result.model_dump(mode="json")
                if stage == "requirement.analyzed":
                    partial_output["requirement"] = stage_output
                elif stage in {
                    "feature.generated",
                    "test_point.generated",
                    "test_case.generated",
                    "enhancement.completed",
                }:
                    partial_output.update(stage_output)
                store.update_job(
                    connection,
                    parsed_job_id,
                    stage=stage,
                    output_payload=partial_output,
                )
            store.publish(
                parsed_job_id,
                {
                    "event": stage,
                    "job_id": job_id,
                    "progress": STAGE_PROGRESS[stage],
                    "artifact": stage_output,
                },
            )
            return result

        result = pipeline.run(
            request,
            context=context,
            answers=dict(payload.get("answers", {})),
            execute_stage=execute_stage,
        )
        _apply_persisted_asset_quality(
            store,
            job,
            embedding_provider,
            context,
            result,
        )
        ensure_not_cancelled(store, parsed_job_id)
        if not result.quality.passed:
            raise GenerationQualityError(result.quality, result)
        output = result.model_dump(mode="json")
        quality_input = {
            "feature_points": output["feature_points"],
            "test_points": output["test_points"],
            "test_cases": output["test_cases"],
            "coverage_matrix": output["coverage_matrix"],
        }
        with store.connection() as connection:
            locked_job = store.get_job_for_update(connection, parsed_job_id)
            if str(
                getattr(locked_job["status"], "value", locked_job["status"])
            ) == "cancelled":
                raise GenerationCancelled("generation_cancelled")
            store.record_stage(
                connection,
                job_id=parsed_job_id,
                stage="quality.completed",
                input_payload=quality_input,
                output_payload=output["quality"],
                status="completed",
                model="deterministic-rules-v1",
            )
            case_ids = store.persist_generation(connection, job, output)
            workspace_candidate_ids = store.persist_workspace_candidates(
                connection,
                job,
                output["test_cases"],
            )
            completed = {
                **output,
                "case_ids": case_ids,
                "workspace_candidate_ids": workspace_candidate_ids,
            }
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=completed,
                error_code=None,
            )
            store.complete_job_message(
                connection,
                job,
                content=(
                    f"已生成 {len(output['test_cases'])} 条候选用例，"
                    f"质量评分 {output['quality']['score']}。请逐条确认后再写入用例集。"
                ),
                metadata_values={
                    "job_id": job_id,
                    "candidate_count": len(output["test_cases"]),
                    "quality_score": output["quality"]["score"],
                },
            )
        store.publish(
            parsed_job_id,
            {
                "event": "quality.completed",
                "job_id": job_id,
                "progress": STAGE_PROGRESS["quality.completed"],
                "quality": output["quality"],
            },
        )
        store.publish(
            parsed_job_id,
            {
                "event": "generation.completed",
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                **completed,
            },
        )
        return completed
    except GenerationCancelled:
        return {"job_id": job_id, "status": "cancelled"}
    except AwaitingInput as awaiting:
        partial_output["requirement"] = awaiting.requirement.model_dump(mode="json")
        with store.connection() as connection:
            locked_job = store.get_job_for_update(connection, parsed_job_id)
            if str(
                getattr(locked_job["status"], "value", locked_job["status"])
            ) == "cancelled":
                return {"job_id": job_id, "status": "cancelled"}
            store.update_job(
                connection,
                parsed_job_id,
                status="awaiting_input",
                stage="generation.awaiting_input",
                output_payload=partial_output,
            )
            store.complete_job_message(
                connection,
                job,
                content="尚未明确测试对象，请补充后再生成用例。",
                status="awaiting_clarification",
                metadata_values={
                    "job_id": job_id,
                    "questions": [
                        item.model_dump(mode="json")
                        for item in awaiting.requirement.open_questions[:3]
                    ],
                },
            )
        event = {
            "event": "generation.awaiting_input",
            "job_id": job_id,
            "status": "awaiting_input",
            "progress": STAGE_PROGRESS["generation.awaiting_input"],
            "questions": [
                item.model_dump(mode="json")
                for item in awaiting.requirement.open_questions
            ],
        }
        store.publish(parsed_job_id, event)
        return event
    except GenerationQualityError as error:
        with store.connection() as connection:
            store.update_job(
                connection,
                parsed_job_id,
                output_payload=error.result.model_dump(mode="json"),
            )
        fail_job(store, parsed_job_id, "generation.failed", error)
        raise
    except Exception as error:
        fail_job(store, parsed_job_id, "generation.failed", error)
        raise


@celery_app.task(name="casepilot.agent.rewrite")
def rewrite_test_case(job_id: str) -> dict[str, Any]:
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
                    conversation_memory=list(payload.get("conversation_memory", [])),
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


def _candidate_snapshot_to_draft(
    ref: str,
    snapshot: dict[str, Any],
) -> TestCaseDraft:
    normalized = {
        **snapshot,
        "id": str(snapshot.get("id") or snapshot.get("case_key") or ref),
        "case_type": str(snapshot.get("case_type", "功能")),
        "priority": str(snapshot.get("priority", "P1")),
        "tags": list(snapshot.get("tags", [])),
        "automated": bool(snapshot.get("automated", False)),
        "status": str(snapshot.get("status", "pending")),
        "preconditions": list(snapshot.get("preconditions", [])),
        "steps": [
            {
                "action": str(step.get("action", "")),
                "expected": str(step.get("expected", "")),
            }
            for step in snapshot.get("steps", [])
        ],
        "test_point_ids": list(snapshot.get("test_point_ids", [])),
        "source_refs": list(snapshot.get("source_refs", [])),
    }
    return TestCaseDraft.model_validate(normalized)


@celery_app.task(name="casepilot.agent.rewrite_batch")
def rewrite_test_cases_batch(job_id: str) -> dict[str, Any]:
    parsed_job_id = UUID(job_id)
    store = JobStore(settings.database_url, settings.redis_url)
    try:
        with store.connection() as connection:
            job = store.get_job(connection, parsed_job_id)
            payload = job["input_payload"]
            store.update_job(
                connection,
                parsed_job_id,
                status="running",
                stage="rewriting",
                error_code=None,
            )
        pipeline = GenerationPipeline(create_provider(settings.provider))
        items: list[dict[str, Any]] = []
        instruction = str(payload["instruction"])
        for target in payload.get("formal_targets", []):
            case_id = UUID(target["case_id"])
            base_revision_id = UUID(target["base_revision_id"])
            with store.connection() as connection:
                snapshot = store.load_case_snapshot(
                    connection,
                    case_id,
                    base_revision_id,
                )
            candidate = pipeline.rewrite(
                RewriteRequest(
                    test_case=TestCaseDraft.model_validate(snapshot),
                    instruction=instruction,
                    conversation_memory=list(payload.get("conversation_memory", [])),
                    model_id=str(payload.get("model_id", "auto")),
                )
            )
            candidate_payload = candidate.model_dump(mode="json")
            items.append(
                {
                    "ref": str(case_id),
                    "target_type": "formal",
                    "test_case_id": str(case_id),
                    "base_revision_id": str(base_revision_id),
                    "candidate_revision_id": None,
                    "base_snapshot": snapshot,
                    "proposed_snapshot": candidate_payload["proposed"],
                    "field_diff": candidate_payload["diff"],
                    "reason": candidate_payload["reason"],
                    "quality": candidate_payload["quality"],
                    "status": "ready",
                }
            )
        for target in payload.get("candidate_targets", []):
            ref = str(target["ref"])
            draft = _candidate_snapshot_to_draft(ref, dict(target["snapshot"]))
            candidate = pipeline.rewrite(
                RewriteRequest(
                    test_case=draft,
                    instruction=instruction,
                    conversation_memory=list(payload.get("conversation_memory", [])),
                    model_id=str(payload.get("model_id", "auto")),
                )
            )
            candidate_payload = candidate.model_dump(mode="json")
            items.append(
                {
                    "ref": ref,
                    "target_type": "candidate",
                    "base_version": int(target.get("version", 1)),
                    "base_snapshot": draft.model_dump(mode="json"),
                    "proposed_snapshot": candidate_payload["proposed"],
                    "field_diff": candidate_payload["diff"],
                    "reason": candidate_payload["reason"],
                    "quality": candidate_payload["quality"],
                    "status": "ready",
                }
            )
        output = {
            "change_set_id": str(payload["change_set_id"]),
            "items": items,
        }
        with store.connection() as connection:
            for item in items:
                if item["target_type"] != "formal":
                    continue
                candidate_id = store.create_grouped_candidate(
                    connection,
                    job=job,
                    case_id=UUID(item["test_case_id"]),
                    base_revision_id=UUID(item["base_revision_id"]),
                    instruction=instruction,
                    candidate={
                        "proposed": item["proposed_snapshot"],
                        "diff": item["field_diff"],
                        "reason": item["reason"],
                    },
                )
                item["candidate_revision_id"] = str(candidate_id)
            output["items"] = items
            store.persist_change_set(connection, job=job, items=items)
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=output,
                error_code=None,
            )
            store.complete_job_message(
                connection,
                job,
                content=f"已生成 {len(items)} 条用例的字段差异，请确认后应用。",
                metadata_values={
                    "change_set_id": str(payload["change_set_id"]),
                    "item_count": len(items),
                },
            )
        store.publish(
            parsed_job_id,
            {
                "event": "rewrite.completed",
                "job_id": job_id,
                "status": "completed",
                **output,
            },
        )
        return output
    except Exception as error:
        with store.connection() as connection:
            job = store.get_job(connection, parsed_job_id)
            change_set_id = job["input_payload"].get("change_set_id")
            if change_set_id:
                connection.execute(
                    update(case_change_sets)
                    .where(case_change_sets.c.id == UUID(str(change_set_id)))
                    .values(status="failed")
                )
        fail_job(store, parsed_job_id, "rewrite.failed", error)
        raise


@celery_app.task(name="casepilot.agent.answer_question")
def answer_knowledge_question(job_id: str) -> dict[str, Any]:
    parsed_job_id = UUID(job_id)
    store = JobStore(settings.database_url, settings.redis_url)
    provider = create_provider(settings.provider)
    try:
        embedding_provider = create_embedding_provider()
    except Exception:
        if not settings.embedding_fallback_enabled:
            raise
        embedding_provider = None
    try:
        with store.connection() as connection:
            job = store.get_job(connection, parsed_job_id)
            store.update_job(
                connection,
                parsed_job_id,
                status="running",
                stage="context.prepared",
                error_code=None,
            )
        context = _context_payload(store, job, embedding_provider)
        payload = job["input_payload"]
        answer, usage = provider.complete(
            stage="knowledge.answered",
            instruction=(
                "检索阶段只负责提供候选证据，必须理解、归纳证据后回答用户问题，"
                "不得把检索片段直接拼接成答案。优先依据提供的用例与知识证据；"
                "不得修改用例，不得虚构资料中没有的确定性规则。"
                "引用只能来自本次提供的知识证据。没有直接证据时要明确说明，"
                "并给出可执行的补充信息建议。"
            ),
            payload={
                "prompt": str(payload["prompt"]),
                "context": context,
                "case_context": list(payload.get("case_context", [])),
                "conversation_memory": list(payload.get("conversation_memory", [])),
            },
            result_type=KnowledgeAnswer,
            model_id=str(payload.get("model_id", "auto")),
        )
        output = answer.model_dump(mode="json")
        with store.connection() as connection:
            store.record_stage(
                connection,
                job_id=parsed_job_id,
                stage="knowledge.answered",
                input_payload={
                    "prompt": str(payload["prompt"]),
                    "evidence_count": len(context.get("evidence", [])),
                },
                output_payload=output,
                status="completed",
                model=usage.model,
                latency_ms=usage.latency_ms,
                token_usage=usage.token_usage,
            )
            store.update_job(
                connection,
                parsed_job_id,
                status="completed",
                stage="completed",
                output_payload=output,
                error_code=None,
            )
            store.complete_job_message(
                connection,
                job,
                content=answer.answer,
                citations=output["citations"],
                metadata_values={
                    "assumptions": output["assumptions"],
                    "retrieval_performed": bool(context.get("evidence")),
                    "retrieval_mode": context.get("retrieval_mode", "none"),
                    "evidence_count": len(context.get("evidence", [])),
                    "model_interaction_performed": True,
                    "model": usage.model,
                    "token_usage": usage.token_usage,
                },
            )
        store.publish(
            parsed_job_id,
            {
                "event": "qa.completed",
                "job_id": job_id,
                "status": "completed",
                **output,
            },
        )
        return output
    except Exception as error:
        fail_job(store, parsed_job_id, "qa.failed", error)
        raise


@celery_app.task(name="casepilot.agent.index_knowledge_source")
def index_knowledge_source(source_id: str) -> dict[str, Any]:
    parsed_source_id = UUID(source_id)
    store = JobStore(settings.database_url, settings.redis_url)
    try:
        embedding_provider = create_embedding_provider()
    except Exception:
        if not settings.embedding_fallback_enabled:
            raise
        embedding_provider = None
    try:
        with store.connection() as connection:
            store.get_source(connection, parsed_source_id)
            documents = store.get_source_documents(connection, parsed_source_id)
            store.update_source(
                connection,
                parsed_source_id,
                status="parsing",
                error_code=None,
            )
        source_degraded = embedding_provider is None
        for document in documents:
            with store.connection() as connection:
                store.update_document(
                    connection,
                    document["id"],
                    status="parsing",
                    error_code=None,
                )
            path = Path(settings.knowledge_storage_path) / document["storage_key"]
            blocks = parse_document(path, document["mime_type"])
            if not blocks or not any(block.content.strip() for block in blocks):
                raise ValueError("document_contains_no_extractable_text")
            chunks = build_chunks(
                title=document["original_name"],
                blocks=blocks,
            )
            document_degraded = embedding_provider is None
            if embedding_provider is not None:
                try:
                    attach_embeddings(chunks, embedding_provider)
                except Exception:
                    if not settings.embedding_fallback_enabled:
                        raise
                    document_degraded = True
            source_degraded = source_degraded or document_degraded
            degraded_code = (
                "embedding_unavailable_lexical_only"
                if document_degraded
                else None
            )
            with store.connection() as connection:
                store.replace_document_chunks(connection, document, chunks)
                store.update_document(
                    connection,
                    document["id"],
                    status="ready",
                    error_code=degraded_code,
                )
        with store.connection() as connection:
            store.update_source(
                connection,
                parsed_source_id,
                status="ready",
                error_code=(
                    "embedding_unavailable_lexical_only"
                    if source_degraded
                    else None
                ),
            )
        return {
            "source_id": source_id,
            "status": "ready",
            "document_count": len(documents),
            "retrieval_mode": "lexical" if source_degraded else "hybrid",
        }
    except Exception as error:
        with store.connection() as connection:
            store.update_source(
                connection,
                parsed_source_id,
                status="failed",
                error_code=error.__class__.__name__,
            )
            for document in store.get_source_documents(connection, parsed_source_id):
                if document["status"] != "ready":
                    store.update_document(
                        connection,
                        document["id"],
                        status="failed",
                        error_code=error.__class__.__name__,
                    )
        raise


def _unlink_storage_key(storage_key: str) -> None:
    root = Path(settings.knowledge_storage_path).resolve()
    target = (root / storage_key).resolve()
    if target.parent != root:
        raise ValueError("invalid_knowledge_storage_key")
    target.unlink(missing_ok=True)


@celery_app.task(name="casepilot.agent.cleanup_knowledge_source")
def cleanup_knowledge_source(source_id: str) -> dict[str, Any]:
    parsed_source_id = UUID(source_id)
    store = JobStore(settings.database_url, settings.redis_url)
    with store.connection() as connection:
        storage_keys = store.cleanup_source(connection, parsed_source_id)
    for storage_key in storage_keys:
        _unlink_storage_key(storage_key)
    return {"source_id": source_id, "deleted_files": len(storage_keys)}


@celery_app.task(name="casepilot.agent.cleanup_expired_knowledge")
def cleanup_expired_knowledge() -> dict[str, int]:
    store = JobStore(settings.database_url, settings.redis_url)
    now = datetime.now(UTC)
    with store.connection() as connection:
        rows = list(
            connection.execute(
                select(
                    knowledge_documents.c.id,
                    knowledge_documents.c.storage_key,
                ).where(
                    knowledge_documents.c.expires_at.is_not(None),
                    knowledge_documents.c.expires_at < now,
                )
            ).mappings()
        )
        document_ids = [row["id"] for row in rows]
        if document_ids:
            connection.execute(
                delete(knowledge_chunks).where(
                    knowledge_chunks.c.document_id.in_(document_ids)
                )
            )
            connection.execute(
                delete(knowledge_documents).where(
                    knowledge_documents.c.id.in_(document_ids)
                )
            )
        empty_sources = list(
            connection.scalars(
                select(knowledge_sources.c.id)
                .where(knowledge_sources.c.persistence == "temporary")
                .where(
                    ~knowledge_sources.c.id.in_(
                        select(knowledge_documents.c.source_id)
                    )
                )
            )
        )
        if empty_sources:
            connection.execute(
                delete(knowledge_sources).where(
                    knowledge_sources.c.id.in_(empty_sources)
                )
            )
    for row in rows:
        _unlink_storage_key(row["storage_key"])
    return {"deleted_documents": len(rows)}
