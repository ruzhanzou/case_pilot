"""Expose generated candidates' review limits, never confer quality certification."""

from sqlalchemy import select

from casepilot_api.models import GenerationJob, GenerationJobStage
from casepilot_api.schemas import CandidateGenerationReview, CandidateReviewIssue


def generation_reviews(db, conversation, candidates):
    job_ids = {item.generation_job_id for item in candidates if item.generation_job_id}
    if not job_ids:
        return {}
    jobs = {
        job.id: job
        for job in db.scalars(
            select(GenerationJob).where(
                GenerationJob.id.in_(job_ids),
                GenerationJob.account_id == conversation.account_id,
                GenerationJob.space_id == conversation.space_id,
                GenerationJob.operation == "generate",
                GenerationJob.input_payload["conversation_id"].astext == str(conversation.id),
            )
        )
    }
    history = {}
    for job_id, _attempt, checks in db.execute(
        select(
            GenerationJobStage.generation_job_id,
            GenerationJobStage.attempt,
            GenerationJobStage.output_payload["checks"],
        )
        .where(
            GenerationJobStage.generation_job_id.in_(jobs),
            GenerationJobStage.stage == "test_case.semantics_checked",
            GenerationJobStage.status == "completed",
        )
        .order_by(GenerationJobStage.created_at, GenerationJobStage.attempt)
    ):
        unreadable = not isinstance(checks, list)
        for check in checks if isinstance(checks, list) else []:
            if not isinstance(check, dict):
                unreadable = True
                continue
            risks = check.get("assertion_risks", [])
            if not isinstance(risks, list):
                unreadable = True
                continue
            for risk in risks:
                if isinstance(risk, str) and risk.strip():
                    history.setdefault(job_id, []).append(
                        {
                            "code": "prior_assertion_risk",
                            "severity": "warning",
                            "message": "此前候选检查曾报告，重生成不代表已独立消除该风险：" + risk,
                        }
                    )
                elif not isinstance(risk, str):
                    unreadable = True
        if unreadable:
            history.setdefault(job_id, []).append(
                {
                    "code": "prior_review_record_unreadable",
                    "severity": "unknown",
                    "message": (
                        "部分历史检查记录格式不完整，不能据此认定风险已消除，请人工复核原始资料。"
                    ),
                }
            )
    result = {}
    for job_id in job_ids:
        job = jobs.get(job_id)
        output = job.output_payload if job and isinstance(job.output_payload, dict) else {}
        quality = output.get("quality")
        quality = quality if isinstance(quality, dict) else {}
        issues = []
        raw_issues = quality.get("issues", [])
        malformed = not isinstance(raw_issues, list)
        for issue in raw_issues if isinstance(raw_issues, list) else []:
            if not isinstance(issue, dict) or not isinstance(issue.get("message"), str):
                malformed = True
                continue
            issues.append(
                CandidateReviewIssue(
                    code=issue.get("code") if isinstance(issue.get("code"), str) else "unknown",
                    message=issue["message"],
                    object_id=issue.get("object_id")
                    if isinstance(issue.get("object_id"), str)
                    else None,
                    severity=issue.get("severity")
                    if isinstance(issue.get("severity"), str)
                    else "unknown",
                )
            )
        if malformed:
            issues.append(
                CandidateReviewIssue(
                    code="review_record_incomplete",
                    severity="unknown",
                    message="部分生成复核记录格式不完整，不能视为已复核，请检查原始资料。",
                )
            )
        grounding = quality.get("grounding_status")
        result[str(job_id)] = CandidateGenerationReview(
            generation_job_id=job_id,
            status="pending_manual" if quality and not malformed else "not_assessed",
            structural_passed=(
                quality.get("structural_passed")
                if type(quality.get("structural_passed")) is bool
                else None
            ),
            grounding_status=(
                grounding
                if isinstance(grounding, str) and grounding in {"unverified", "model_reviewed"}
                else "unknown"
            ),
            issues=[
                CandidateReviewIssue.model_validate(note)
                for note in merge_generation_notes(
                    [issue.model_dump(mode="json") for issue in issues],
                    history.get(job_id),
                )
            ],
        )
    return result


def merge_generation_notes(*groups):
    """Retain historical notes; an equal current note cannot weaken an old error."""
    merged = {}
    severity_rank = {"error": 3, "warning": 2, "unknown": 1, "info": 0}
    for group in groups:
        for raw in group if isinstance(group, list) else []:
            if not isinstance(raw, dict) or not isinstance(raw.get("message"), str):
                continue
            note = {
                key: raw[key]
                for key in ("code", "message", "object_id", "severity")
                if isinstance(raw.get(key), str)
                or key == "object_id"
                and raw.get(key) is None
                and key in raw
            }
            identity = (note.get("code"), note.get("object_id"), note["message"])
            old = merged.get(identity)
            if old is None or severity_rank.get(note.get("severity"), 1) > severity_rank.get(
                old.get("severity"), 1
            ):
                merged[identity] = note
    return list(merged.values())
