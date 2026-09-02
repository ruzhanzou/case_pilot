import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID, uuid4

from celery import Celery
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from redis import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from casepilot_api.agent_router import needs_intent_confirmation, plan_intents
from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.case_management import (
    case_to_view,
    create_test_case_record,
    ensure_collection,
    normalize_tags,
    write_audit,
)
from casepilot_api.config import get_settings
from casepilot_api.database import get_db_session
from casepilot_api.knowledge import _store_uploads
from casepilot_api.models import (
    CandidateRevision,
    CaseChangeSet,
    CaseCollection,
    CollectionCaseMembership,
    Conversation,
    ConversationMessage,
    ConversationOperation,
    GenerationJob,
    GenerationJobStage,
    TestCase,
    TestCaseRevision,
    WorkspaceCandidate,
    WorkspaceTestBrief,
)
from casepilot_api.schemas import (
    CaseChangeSetApplyView,
    CaseChangeSetView,
    ChangeSetApplyRequest,
    ConversationBindingUpdate,
    ConversationCreate,
    ConversationHistoryPage,
    ConversationMessageCreate,
    ConversationMessageView,
    ConversationOperationCollectionConfirmRequest,
    ConversationOperationContinueRequest,
    ConversationOperationPlanView,
    ConversationOperationResumeRequest,
    ConversationOperationView,
    ConversationSummaryView,
    ConversationTarget,
    ConversationTargetSnapshot,
    ConversationTurnView,
    ConversationView,
    ConversationWorkflowRunView,
    ConversationWorkflowStageView,
    GenerationAnswersRequest,
    IntentConfirmationRequest,
    KnowledgeUploadView,
    TestBriefConfirmRequest,
    TestBriefContent,
    TestBriefCreate,
    TestCaseCreate,
    TestCaseView,
    WorkspaceCandidateCommitRequest,
    WorkspaceCandidateUpdate,
    WorkspaceCandidateView,
    WorkspaceStateUpdate,
    WorkspaceTestBriefView,
)

router = APIRouter(prefix="/api/v1", tags=["conversations"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db_session)]
task_client = Celery(
    "casepilot-api-conversations",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

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
    "knowledge.answered": 96,
    "completed": 100,
    "failed": 100,
    "cancelled": 100,
}
BRIEF_SECTIONS = (
    ("测试范围", "scope"),
    ("角色", "roles"),
    ("核心流程", "core_flows"),
    ("业务规则", "business_rules"),
    ("约束", "constraints"),
    ("风险", "risks"),
    ("覆盖维度", "coverage_dimensions"),
    ("假设", "assumptions"),
)

INTENTS = {
    "CASE_GENERATE",
    "CASE_MODIFY",
    "CASE_DELETE",
    "CASE_QUERY",
    "KNOWLEDGE_QA",
    "SMALL_TALK",
    "UNRESOLVED",
}
ASSET_INTENTS = {"CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE", "CASE_QUERY"}
CHANGE_FIELDS = {
    "title",
    "module",
    "priority",
    "case_type",
    "tags",
    "preconditions",
    "steps",
    "source_refs",
}
GENERATE_TERMS = (
    "生成",
    "新增用例",
    "补充用例",
    "用例补充",
    "覆盖缺口",
    "重新设计",
    "重新生成",
    "测试场景",
)
MODIFY_TERMS = (
    "修改",
    "改写",
    "删除步骤",
    "替换预期",
    "调整优先级",
    "合并重复",
    "改成",
    "改为",
)
MODIFY_OBJECT_TERMS = ("当前用例", "这条用例", "步骤", "预期结果", "前置条件", "优先级")
DELETE_TERMS = ("删除用例", "删除当前用例", "移除用例", "作废用例")
QUERY_TERMS = ("查询用例", "查找用例", "列出用例", "搜索用例", "有哪些用例")
NEGATED_ASSET_DELETE = re.compile(
    r"(?:不要|无需|不用|别|禁止|先别|暂不|暂时不要).{0,16}(?:删除|移除|作废)"
)
EXPLICIT_ASSET_DELETE = re.compile(
    r"(?:删除|移除|作废).{0,24}(?:用例|场景)|"
    r"(?:用例|场景).{0,24}(?:删除|移除|作废)"
)
EXPLICIT_ASSET_QUERY = re.compile(
    r"(?:查询|查找|列出|搜索|筛选|检索).{0,40}(?:用例|场景)|"
    r"(?:用例|场景).{0,24}(?:有哪些|列表|清单)"
)
EXPLICIT_ASSET_MODIFY = re.compile(
    r"(?:修改|改写|调整|替换|优化|完善|改得|改成|改为).{0,40}"
    r"(?:用例|场景|步骤|预期结果|前置条件|优先级)|"
    r"(?:用例|场景|步骤|预期结果|前置条件|优先级).{0,40}"
    r"(?:修改|改写|调整|替换|优化|完善|改得|改成|改为)"
)
SMALL_TALK_TERMS = (
    "你好",
    "您好",
    "嗨",
    "早上好",
    "下午好",
    "晚上好",
    "晚安",
    "hello",
    "hi",
    "在吗",
    "谢谢",
    "辛苦了",
    "再见",
    "好的",
    "收到",
    "明白了",
    "你是谁",
    "叫什么",
)
CAPABILITY_TERMS = (
    "能做什么",
    "可以做什么",
    "能帮我做什么",
    "可以帮我做什么",
    "能帮我完成哪些",
    "可以帮我完成哪些",
    "支持什么",
    "支持哪些工作",
    "支持哪些功能",
    "有哪些能力",
    "有什么能力",
    "会什么",
    "擅长什么",
    "主要做什么",
)
QA_TERMS = (
    "什么是",
    "是什么",
    "为什么",
    "怎么",
    "如何",
    "如何理解",
    "区别",
    "介绍一下",
    "讲讲",
    "说明一下",
    "最佳实践",
    "应该",
    "能否",
    "是否",
    "是否提到",
    "有没有提到",
    "覆盖情况",
    "解释",
    "多少",
    "哪些",
    "哪个",
    "哪里",
    "何时",
    "吗",
    "？",
    "?",
)
DOMAIN_QA_TERMS = (
    "测试",
    "用例",
    "质量",
    "需求",
    "缺陷",
    "接口",
    "性能",
    "安全",
    "自动化",
    "验收",
    "冒烟",
    "回归",
    "边界值",
    "等价类",
)
TITLE_LIMIT = 32
AGENT_MEMORY_MESSAGE_LIMIT = 100
AGENT_MEMORY_CONTENT_LIMIT = 1200
UNKNOWN_TEST_OBJECT_TERMS = (
    "不知道",
    "不清楚",
    "不确定",
    "未明确",
    "没有明确",
    "尚未明确",
    "待定",
    "是什么",
    "是哪个",
    "不是明确",
)


def _extract_explicit_test_object(content: str) -> str:
    normalized = " ".join(content.strip().split())
    if not normalized or any(term in normalized for term in UNKNOWN_TEST_OBJECT_TERMS):
        return ""

    candidate = ""
    for pattern in (
        r"(?:测试对象|被测对象)\s*(?:是|为|：|:|包括|包含)\s*(.+)",
        r"(?:测试对象|被测对象)\s+(.+)",
        r"(?:为|针对|围绕)\s*(.+?)\s*(?:生成|设计|编写|创建)"
        r"(?:相关)?(?:测试)?用例",
        r"(?:生成|设计|编写|创建)\s*(.+?)\s*(?:测试)?用例",
    ):
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1)
            break

    candidate = candidate.strip(" ：:，,。；;“”\"'的")
    embedded_object = re.search(r"\s为\s*(.+)", candidate)
    if embedded_object:
        candidate = embedded_object.group(1).strip()
    candidate = re.sub(
        r"(?:生成|设计|编写|创建)(?:相关)?(?:测试)?用例.*$",
        "",
        candidate,
    )
    candidate = re.sub(r"(?:测试)?用例(?:设计|生成)?$", "", candidate)
    candidate = candidate.strip(" ：:，,。；;“”\"'的")
    if (
        len(candidate) < 2
        or candidate in {"测试", "用例", "功能", "系统", "产品"}
        or any(term in candidate for term in UNKNOWN_TEST_OBJECT_TERMS)
    ):
        return ""
    return candidate[:200]


def _test_object_from_messages(
    messages: list[ConversationMessage],
    *,
    before: datetime | None = None,
) -> str:
    for message in reversed(messages):
        if message.role != "user" or (before and message.created_at > before):
            continue
        test_object = _extract_explicit_test_object(message.content)
        if test_object:
            return test_object
    return ""


def _test_object_from_memory(memory: list[dict[str, str]]) -> str:
    for message in reversed(memory):
        if message.get("role") != "user":
            continue
        test_object = _extract_explicit_test_object(message.get("content", ""))
        if test_object:
            return test_object
    return ""


def summarize_conversation_title(content: str) -> str:
    """Create a stable, compact title from the first user turn."""
    normalized = " ".join(content.strip().split())
    if not normalized:
        return "新对话"

    compact = normalized.casefold().strip("。！？!?，, ")
    if compact in {"你好", "您好", "嗨", "hello", "hi", "在吗"}:
        return "与 CasePilot 打招呼"
    if "casepilot" in compact and any(
        term in compact for term in ("能做什么", "可以做什么", "帮我做什么", "能力")
    ):
        return "了解 CasePilot 能力"
    if any(term in compact for term in ("你是谁", "叫什么名字")):
        return "了解 CasePilot"

    cleaned = re.sub(
        r"^(?:请|麻烦|劳烦)?(?:帮我|协助我|替我)?",
        "",
        normalized,
    ).strip(" ：:，,")
    generation_match = re.search(
        r"(?:生成|设计|编写|创建|新增|补充)(?:一组|一些|相关)?(.{1,36}?)(?:测试)?用例",
        cleaned,
    )
    generation_position = re.search(
        r"(?:生成|设计|编写|创建|新增|补充|重新生成|重新设计)",
        cleaned,
    )
    subject = ""
    if generation_position and generation_position.start() > 0:
        subject = cleaned[: generation_position.start()]
        subject = re.sub(r"^(?:为|针对|围绕|基于)", "", subject)
    elif generation_match:
        subject = generation_match.group(1)
    subject = subject.strip(" ：:，,。的")
    if subject:
        subject = re.sub(r"(?:相关)?(?:测试)?用例$", "", subject).strip()
        title = f"{subject}用例设计"
    else:
        title = cleaned.rstrip("。！？!?")
        title = title.replace("有什么区别", "的区别")
        title = re.sub(r"(?:是什么|有哪些)[吗呢]?$", "", title).strip(" 的")

    title = " ".join(title.split()).strip("。！？!?，, ")
    if not title:
        title = "新对话"
    return title if len(title) <= TITLE_LIMIT else f"{title[: TITLE_LIMIT - 1]}…"


def classify_intent(
    content: str,
    has_targets: bool = False,
    phase: str = "idle",
) -> tuple[str, float]:
    normalized = " ".join(content.strip().split())
    compact = normalized.casefold().strip("。！？!?，, ")
    asks_about_capabilities = (
        "casepilot" in compact or "你" in compact
    ) and any(term in compact for term in CAPABILITY_TERMS)
    if (
        compact in SMALL_TALK_TERMS
        or any(
            term in compact
            for term in ("你是谁", "叫什么名字", "谢谢", "辛苦了", "再见")
        )
        or asks_about_capabilities
    ):
        return "SMALL_TALK", 0.99
    question_like = any(term in normalized for term in QA_TERMS)
    question_like = question_like or any(
        term in normalized for term in ("什么", "为何", "含义", "指什么")
    )
    generation_request = any(
        term in normalized
        for term in ("帮我", "请为", "请生成", "给我生成", "替我")
    )
    if NEGATED_ASSET_DELETE.search(normalized):
        return "KNOWLEDGE_QA", 0.96
    if any(term in normalized for term in DELETE_TERMS) or EXPLICIT_ASSET_DELETE.search(
        normalized
    ):
        explicit_delete_request = any(
            term in normalized
            for term in ("请删除", "帮我删除", "我要删除", "立即删除", "现在删除")
        )
        if question_like and not explicit_delete_request:
            return "KNOWLEDGE_QA", 0.94
        return "CASE_DELETE", 0.98
    if any(term in normalized for term in QUERY_TERMS) or EXPLICIT_ASSET_QUERY.search(
        normalized
    ):
        return "CASE_QUERY", 0.96
    if phase == "brief_review":
        if any(term in normalized for term in ("补充", "增加", "覆盖", "修改", "调整")):
            return "CASE_GENERATE", 0.97
        if question_like:
            return "KNOWLEDGE_QA", 0.94
        if re.fullmatch(r"(?:继续|照这个|按这个|改一下)[吧。！!]?", normalized):
            return "UNRESOLVED", 0.55
        return "KNOWLEDGE_QA", 0.82
    if "测试说明" in normalized and any(
        term in normalized for term in ("修改", "调整", "补充", "增加", "删除")
    ):
        return "CASE_GENERATE", 0.98
    explicitly_generates_cases = bool(
        re.search(
            r"(?:生成|设计|编写|创建|新增|补充|重新生成|重新设计)"
            r".{0,40}?(?:测试)?用例",
            normalized,
        )
    )
    if question_like and not generation_request:
        return "KNOWLEDGE_QA", 0.94
    if explicitly_generates_cases and not has_targets:
        return "CASE_GENERATE", 0.98
    if EXPLICIT_ASSET_MODIFY.search(normalized):
        return "CASE_MODIFY", 0.96 if has_targets else 0.91
    generate_score = sum(term in normalized for term in GENERATE_TERMS)
    modify_score = sum(term in normalized for term in MODIFY_TERMS)
    qa_score = sum(term in normalized for term in QA_TERMS)

    if "补充" in normalized:
        if any(term in normalized for term in MODIFY_OBJECT_TERMS):
            modify_score += 2
        elif "用例" in normalized or "场景" in normalized:
            generate_score += 2
    if (
        modify_score
        and has_targets
        and any(term in normalized for term in MODIFY_OBJECT_TERMS)
    ):
        modify_score += 1
    if generate_score and modify_score:
        winner = "CASE_MODIFY" if modify_score > generate_score else "CASE_GENERATE"
        margin = abs(modify_score - generate_score)
        return winner, 0.84 if margin >= 2 else 0.68
    if modify_score:
        return "CASE_MODIFY", 0.96 if modify_score >= 2 else 0.88
    if generate_score:
        return "CASE_GENERATE", 0.96 if generate_score >= 2 else 0.88
    if has_targets and any(term in normalized for term in ("优化", "完善", "调整")):
        return "CASE_MODIFY", 0.68
    if qa_score or any(term in normalized for term in DOMAIN_QA_TERMS):
        return "KNOWLEDGE_QA", 0.88 if qa_score else 0.84
    if any(term in normalized for term in ("改一下", "调整一下", "处理一下", "弄一下")):
        return "UNRESOLVED", 0.55
    return "KNOWLEDGE_QA", 0.82


def _looks_like_brief_confirmation(content: str) -> bool:
    normalized = " ".join(content.strip().split())
    return (
        any(
            phrase in normalized
            for phrase in (
                "确认说明",
                "确认测试说明",
                "确认结构化测试说明",
                "测试说明没问题",
                "测试说明没有问题",
                "说明没问题",
                "说明没有问题",
            )
        )
        and any(term in normalized for term in ("生成", "开始", "确认"))
    )


def render_test_brief_markdown(version: int, content: dict[str, Any]) -> str:
    lines = [
        f"# 结构化测试说明 V{version}",
        "",
        "## 测试对象",
        "",
        str(content.get("test_object") or "待澄清"),
        "",
        "## 测试目标",
        "",
        str(content.get("test_objective") or "未提供"),
    ]
    for title, key in BRIEF_SECTIONS:
        lines.extend(["", f"## {title}", ""])
        values = content.get(key) or []
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("未提供")
    lines.extend(["", "## 测试对象澄清", ""])
    questions = content.get("open_questions") or []
    if not questions:
        lines.append("测试对象已明确，无需澄清。")
    for item in questions:
        lines.append(f"- **待澄清**：{item.get('question', '')}")
        if item.get("impact"):
            lines.append(f"  - 影响：{item['impact']}")
    return "\n".join(lines).strip() + "\n"


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


def _message_view(message: ConversationMessage) -> ConversationMessageView:
    return ConversationMessageView(
        id=message.id,
        role=message.role,
        content=message.content,
        intent=message.intent,
        intent_confidence=message.intent_confidence,
        status=message.status,
        target_case_ids=list(message.target_case_ids),
        related_job_id=message.related_job_id,
        citations=list(message.citations),
        metadata=dict(message.message_metadata),
        created_at=message.created_at,
    )


def _operation_view(operation: ConversationOperation) -> ConversationOperationView:
    return ConversationOperationView(
        id=operation.id,
        sequence=operation.sequence,
        intent=operation.intent,
        confidence=operation.confidence,
        status=operation.status,
        target=dict(operation.target),
        payload=dict(operation.payload),
        result=dict(operation.result),
        requires_confirmation=operation.requires_confirmation,
        related_job_id=operation.related_job_id,
        related_change_set_id=operation.related_change_set_id,
        error_code=operation.error_code,
        created_at=operation.created_at,
    )


def _operation_plan_view(
    operations: list[ConversationOperation],
) -> ConversationOperationPlanView | None:
    if not operations:
        return None
    current = next(
        (
            item
            for item in operations
            if item.status
            not in {"completed", "failed", "cancelled", "skipped"}
        ),
        None,
    )
    status = (
        "failed"
        if any(item.status == "failed" for item in operations)
        else "completed"
        if all(item.status in {"completed", "skipped"} for item in operations)
        else "paused"
        if current and current.status.startswith("awaiting_")
        else "running"
    )
    return ConversationOperationPlanView(
        status=status,
        source_message_id=operations[0].message_id,
        current_operation_id=current.id if current else None,
        operations=[_operation_view(item) for item in operations],
    )


def _operation_runtime_status(
    operation: ConversationOperation,
    assistant: ConversationMessage,
    action: dict[str, Any],
) -> None:
    if assistant.status == "completed" and not action.get("job_id"):
        operation.status = "completed"
        operation.completed_at = datetime.now(UTC)
    elif assistant.status == "awaiting_confirmation":
        operation.status = "awaiting_confirmation"
    elif assistant.status.startswith("awaiting_"):
        operation.status = (
            "awaiting_intent"
            if operation.intent == "UNRESOLVED"
            else "awaiting_collection"
            if assistant.status == "awaiting_collection"
            else "awaiting_target"
        )
    else:
        operation.status = "running"
    if assistant.related_job_id:
        operation.related_job_id = assistant.related_job_id
    if action.get("change_set_id"):
        operation.related_change_set_id = UUID(str(action["change_set_id"]))
    if action.get("type") == "new_conversation_required":
        operation.result = {
            **dict(operation.result),
            "requested_collection_id": action["requested_collection_id"],
            "draft_text": action.get("draft_text", ""),
        }


def _brief_view(
    brief: WorkspaceTestBrief,
    resolved_test_object: str = "",
) -> WorkspaceTestBriefView:
    stored_content = dict(brief.content)
    recovered_test_object = bool(
        resolved_test_object
        and not str(stored_content.get("test_object") or "").strip()
    )
    if recovered_test_object:
        stored_content["test_object"] = resolved_test_object
        stored_content["open_questions"] = []
    content = TestBriefContent.model_validate(stored_content)
    normalized_content = content.model_dump(mode="json")
    return WorkspaceTestBriefView(
        id=brief.id,
        source_operation_id=brief.source_operation_id,
        version=brief.version,
        content=content,
        markdown_content=(
            brief.markdown_content
            if not recovered_test_object and brief.markdown_content
            else render_test_brief_markdown(brief.version, normalized_content)
        ),
        status=brief.status,
        confirmed_at=brief.confirmed_at,
        created_at=brief.created_at,
    )


def _candidate_view(candidate: WorkspaceCandidate) -> WorkspaceCandidateView:
    return WorkspaceCandidateView(
        id=candidate.id,
        generation_job_id=candidate.generation_job_id,
        ref=candidate.ref,
        version=candidate.version,
        position=candidate.position,
        snapshot=dict(candidate.snapshot),
        included=candidate.included,
        status=candidate.status,
        updated_at=candidate.updated_at,
    )


def _conversation_view(db: Session, conversation: Conversation) -> ConversationView:
    messages = list(
        db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.created_at, ConversationMessage.id)
        )
    )
    briefs = list(
        db.scalars(
            select(WorkspaceTestBrief)
            .where(WorkspaceTestBrief.conversation_id == conversation.id)
            .order_by(WorkspaceTestBrief.version)
        )
    )
    candidates = list(
        db.scalars(
            select(WorkspaceCandidate)
            .where(
                WorkspaceCandidate.conversation_id == conversation.id,
                WorkspaceCandidate.status == "candidate",
            )
            .order_by(WorkspaceCandidate.position, WorkspaceCandidate.created_at)
        )
    )
    operations = list(
        db.scalars(
            select(ConversationOperation)
            .where(ConversationOperation.conversation_id == conversation.id)
            .order_by(
                ConversationOperation.created_at,
                ConversationOperation.message_id,
                ConversationOperation.sequence,
            )
        )
    )
    if operations:
        active_operation = next(
            (
                item
                for item in operations
                if item.status not in {"completed", "failed", "cancelled", "skipped"}
            ),
            None,
        )
        latest_operation_message_id = (
            active_operation.message_id
            if active_operation is not None
            else operations[-1].message_id
        )
        operations = [
            item
            for item in operations
            if item.message_id == latest_operation_message_id
        ]
    message_by_job_id = {
        message.related_job_id: message
        for message in messages
        if message.related_job_id is not None
    }
    jobs = (
        list(
            db.scalars(
                select(GenerationJob)
                .where(GenerationJob.id.in_(message_by_job_id))
                .order_by(GenerationJob.created_at)
            )
        )
        if message_by_job_id
        else []
    )
    workflow_runs: list[ConversationWorkflowRunView] = []
    for job in jobs:
        stages = list(
            db.scalars(
                select(GenerationJobStage)
                .where(GenerationJobStage.generation_job_id == job.id)
                .order_by(
                    GenerationJobStage.created_at,
                    GenerationJobStage.attempt,
                )
            )
        )
        status = (
            job.status.value if hasattr(job.status, "value") else str(job.status)
        )
        workflow_runs.append(
            ConversationWorkflowRunView(
                job_id=job.id,
                message_id=message_by_job_id[job.id].id,
                operation=job.operation,
                status=status,
                current_stage=job.stage,
                progress=STAGE_PROGRESS.get(job.stage, 0),
                error_code=public_error_code(job.error_code),
                stages=[
                    ConversationWorkflowStageView(
                        stage=stage.stage,
                        attempt=stage.attempt,
                        status=stage.status,
                        progress=STAGE_PROGRESS.get(stage.stage, 0),
                        model=stage.model,
                        latency_ms=stage.latency_ms,
                        created_at=stage.created_at,
                    )
                    for stage in stages
                ],
                created_at=job.created_at,
                updated_at=stages[-1].created_at if stages else job.created_at,
            )
        )
    return ConversationView(
        id=conversation.id,
        space_id=conversation.space_id,
        collection_id=conversation.collection_id,
        title=conversation.title,
        status=conversation.status,
        context=dict(conversation.context),
        messages=[_message_view(message) for message in messages],
        test_briefs=[
            _brief_view(
                brief,
                _test_object_from_messages(messages, before=brief.created_at),
            )
            for brief in briefs
        ],
        candidates=[_candidate_view(candidate) for candidate in candidates],
        workflow_runs=workflow_runs,
        operation_plan=_operation_plan_view(operations),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _ensure_conversation(
    db: Session,
    account_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    require_space_membership(db, account_id, conversation.space_id)
    return conversation


def _change_set_view(change_set: CaseChangeSet) -> CaseChangeSetView:
    return CaseChangeSetView(
        id=change_set.id,
        conversation_id=change_set.conversation_id,
        generation_job_id=change_set.generation_job_id,
        instruction=change_set.instruction,
        scope=change_set.scope,
        status=change_set.status,
        items=list(change_set.items),
        created_at=change_set.created_at,
        applied_at=change_set.applied_at,
    )


def _new_assistant_message(
    conversation_id: UUID,
    *,
    content: str,
    intent: str,
    confidence: float,
    status: str,
    target_case_ids: list[str],
    metadata: dict[str, Any] | None = None,
) -> ConversationMessage:
    return ConversationMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        intent=intent,
        intent_confidence=confidence,
        status=status,
        target_case_ids=target_case_ids,
        citations=[],
        message_metadata=metadata or {},
    )


def _agent_conversation_memory(
    db: Session,
    conversation_id: UUID,
) -> list[dict[str, str]]:
    messages = list(
        db.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                func.length(func.trim(ConversationMessage.content)) > 0,
            )
            .order_by(
                ConversationMessage.created_at.desc(),
                ConversationMessage.id.desc(),
            )
            .limit(AGENT_MEMORY_MESSAGE_LIMIT)
        )
    )[:AGENT_MEMORY_MESSAGE_LIMIT]
    memory: list[dict[str, str]] = []
    for message in reversed(messages):
        content = message.content.strip()
        if len(content) > AGENT_MEMORY_CONTENT_LIMIT:
            content = f"{content[: AGENT_MEMORY_CONTENT_LIMIT - 1]}…"
        memory.append({"role": message.role, "content": content})
    return memory


def _collection_candidates(
    db: Session,
    conversation: Conversation,
    content: str,
) -> tuple[list[dict[str, str]], UUID | None]:
    collections = list(
        db.scalars(
            select(CaseCollection)
            .where(
                CaseCollection.space_id == conversation.space_id,
                CaseCollection.deleted_at.is_(None),
            )
            .order_by(CaseCollection.created_at.desc(), CaseCollection.name)
            .limit(100)
        )
    )
    normalized = "".join(content.casefold().split())
    candidates = [
        {"id": str(item.id), "name": item.name}
        for item in collections
    ]
    matches = [
        item.id
        for item in collections
        if len("".join(item.name.casefold().split())) >= 2
        and "".join(item.name.casefold().split()) in normalized
    ]
    return candidates, matches[0] if len(matches) == 1 else None


def _collection_gate(
    db: Session,
    conversation: Conversation,
    payload: ConversationMessageCreate,
    intent: str,
    confidence: float,
    operation_id: UUID | None,
) -> tuple[ConversationMessage, dict[str, Any], str | None] | None:
    if intent not in ASSET_INTENTS:
        return None
    candidates, mentioned_collection_id = _collection_candidates(
        db,
        conversation,
        payload.content,
    )
    if conversation.collection_id is None:
        assistant = _new_assistant_message(
            conversation.id,
            content="请先确认本次对话要维护的用例集合。确认后，该对话将只维护这一集合。",
            intent=intent,
            confidence=confidence,
            status="awaiting_collection",
            target_case_ids=[],
            metadata={
                "collection_candidates": candidates,
                "suggested_collection_id": (
                    str(mentioned_collection_id) if mentioned_collection_id else None
                ),
                "allow_create_collection": intent == "CASE_GENERATE",
                "operation_id": str(operation_id) if operation_id else None,
            },
        )
        db.add(assistant)
        db.flush()
        return (
            assistant,
            {
                "type": "collection_confirmation",
                "suggested_collection_id": (
                    str(mentioned_collection_id) if mentioned_collection_id else None
                ),
                "allow_create_collection": intent == "CASE_GENERATE",
            },
            None,
        )
    if mentioned_collection_id and mentioned_collection_id != conversation.collection_id:
        requested = next(
            item for item in candidates if item["id"] == str(mentioned_collection_id)
        )
        current = db.get(CaseCollection, conversation.collection_id)
        assistant = _new_assistant_message(
            conversation.id,
            content=(
                f"当前对话已绑定“{current.name if current else '当前集合'}”，"
                f"不能切换到“{requested['name']}”。请新建对话后继续。"
            ),
            intent=intent,
            confidence=confidence,
            status="awaiting_confirmation",
            target_case_ids=[],
            metadata={
                "action": "new_conversation_required",
                "current_collection_id": str(conversation.collection_id),
                "requested_collection_id": requested["id"],
                "requested_collection_name": requested["name"],
                "draft_text": payload.content.strip(),
                "operation_id": str(operation_id) if operation_id else None,
            },
        )
        db.add(assistant)
        db.flush()
        return (
            assistant,
            {
                "type": "new_conversation_required",
                "requested_collection_id": requested["id"],
                "draft_text": payload.content.strip(),
            },
            None,
        )
    return None


def _start_action(
    db: Session,
    account: Any,
    conversation: Conversation,
    user_message: ConversationMessage,
    payload: ConversationMessageCreate,
    intent: str,
    confidence: float,
    operation_id: UUID | None = None,
) -> tuple[ConversationMessage, dict[str, Any], str | None]:
    collection_gate = _collection_gate(
        db,
        conversation,
        payload,
        intent,
        confidence,
        operation_id,
    )
    if collection_gate is not None:
        return collection_gate
    if intent == "UNRESOLVED":
        assistant = _new_assistant_message(
            conversation.id,
            content="我还不能可靠判断这句话要执行什么操作，请补充具体对象和期望动作。",
            intent=intent,
            confidence=confidence,
            status="awaiting_clarification",
            target_case_ids=[],
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None
    target_ids = [str(item) for item in payload.target_case_ids]
    case_context: list[dict[str, Any]] = [
        {
            "ref": item.ref,
            "target_type": "candidate",
            "snapshot": item.snapshot,
        }
        for item in payload.target_candidate_snapshots
    ]
    for case_id in payload.target_case_ids:
        test_case = db.scalar(
            select(TestCase).where(
                TestCase.id == case_id,
                TestCase.space_id == conversation.space_id,
                TestCase.deleted_at.is_(None),
            )
        )
        if test_case is None:
            raise HTTPException(status_code=404, detail="test_case_not_found")
        case_context.append(
            {
                "ref": str(test_case.id),
                "target_type": "formal",
                "snapshot": case_to_view(db, test_case).model_dump(mode="json"),
            }
        )

    if intent == "CASE_QUERY":
        cases = list(
            db.scalars(
                select(TestCase)
                .join(
                    CollectionCaseMembership,
                    CollectionCaseMembership.test_case_id == TestCase.id,
                )
                .where(
                    CollectionCaseMembership.collection_id
                    == conversation.collection_id,
                    TestCase.deleted_at.is_(None),
                )
                .order_by(CollectionCaseMembership.position, TestCase.created_at)
                .limit(20)
            )
        )
        items = [case_to_view(db, test_case) for test_case in cases]
        summary = (
            "当前集合暂无正式用例。"
            if not items
            else "当前集合用例：\n"
            + "\n".join(
                f"- {item.case_key}｜{item.title}｜{item.module or '未分类'}"
                for item in items
            )
        )
        assistant = _new_assistant_message(
            conversation.id,
            content=summary,
            intent=intent,
            confidence=confidence,
            status="completed",
            target_case_ids=[str(item.id) for item in items],
            metadata={"result_count": len(items), "retrieval_performed": False},
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "case_query", "count": len(items)}, None

    if intent == "CASE_DELETE":
        if not payload.target_case_ids:
            assistant = _new_assistant_message(
                conversation.id,
                content="请先选择当前用例或当前模块，再说明删除原因。",
                intent=intent,
                confidence=confidence,
                status="awaiting_clarification",
                target_case_ids=[],
            )
            db.add(assistant)
            db.flush()
            return assistant, {"type": "clarification"}, None
        items = [
            {
                "operation": "delete",
                "ref": item["ref"],
                "target_type": "formal",
                "test_case_id": item["ref"],
                "base_revision_id": item["snapshot"]["current_revision_id"],
                "base_snapshot": item["snapshot"],
                "proposed_snapshot": item["snapshot"],
                "field_diff": [
                    {
                        "field": "delete",
                        "before": False,
                        "after": True,
                    }
                ],
                "status": "pending",
            }
            for item in case_context
            if item["target_type"] == "formal"
        ]
        change_set = CaseChangeSet(
            conversation_id=conversation.id,
            generation_job_id=None,
            instruction=payload.content.strip(),
            scope=payload.scope,
            status="ready",
            items=items,
            created_by=account.id,
        )
        db.add(change_set)
        db.flush()
        assistant = _new_assistant_message(
            conversation.id,
            content=(
                f"将软删除 {len(items)} 条用例。请审阅受影响清单并明确确认；"
                "取消不会改变任何资产。"
            ),
            intent=intent,
            confidence=confidence,
            status="awaiting_confirmation",
            target_case_ids=[item["ref"] for item in items],
            metadata={"change_set_id": str(change_set.id), "operation": "delete"},
        )
        db.add(assistant)
        db.flush()
        return (
            assistant,
            {"type": "change_set", "change_set_id": str(change_set.id)},
            None,
        )

    conversation_memory = _agent_conversation_memory(db, conversation.id)
    provided_test_object = _test_object_from_memory(conversation_memory)
    input_payload = {
        "prompt": payload.content.strip(),
        "markdown_content": payload.content.strip(),
        "file_names": [],
        "mode": settings.ai_mode,
        "model_id": payload.model_id,
        "document_ids": [str(item) for item in payload.document_ids],
        "knowledge_source_ids": [str(item) for item in payload.knowledge_source_ids],
        "use_space_knowledge": payload.use_space_knowledge,
        "answers": {},
        "persist_cases": False,
        "conversation_id": str(conversation.id),
        "user_message_id": str(user_message.id),
        "case_context": case_context,
        "conversation_memory": conversation_memory,
        "conversation_operation_id": str(operation_id) if operation_id else None,
    }

    if intent == "CASE_MODIFY" and not (
        payload.target_case_ids or payload.target_candidate_snapshots
    ):
        assistant = _new_assistant_message(
            conversation.id,
            content="请先选择要修改的当前用例或当前模块。",
            intent=intent,
            confidence=confidence,
            status="awaiting_clarification",
            target_case_ids=[],
            metadata={
                "questions": [
                    {
                        "id": "modify-target",
                        "question": "本次要修改哪些用例？",
                        "impact": "未确定修改对象，无法生成安全的字段差异。",
                    }
                ]
            },
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None

    latest_brief = db.scalar(
        select(WorkspaceTestBrief)
        .where(WorkspaceTestBrief.conversation_id == conversation.id)
        .order_by(WorkspaceTestBrief.version.desc())
    )
    if latest_brief is not None:
        current_test_brief = dict(latest_brief.content)
        if provided_test_object and not str(
            current_test_brief.get("test_object") or ""
        ).strip():
            current_test_brief["test_object"] = provided_test_object
            current_test_brief["open_questions"] = []
        input_payload["current_test_brief"] = current_test_brief
        input_payload["current_test_brief_version"] = latest_brief.version
    if provided_test_object:
        input_payload["provided_test_object"] = provided_test_object
    brief_operation = "update" if latest_brief is not None else "draft"
    input_payload["brief_operation"] = brief_operation

    job = GenerationJob(
        space_id=conversation.space_id,
        account_id=account.id,
        operation={
            "CASE_GENERATE": "draft_brief",
            "CASE_MODIFY": "conversation_modify",
            "KNOWLEDGE_QA": "knowledge_qa",
            "SMALL_TALK": "knowledge_qa",
        }[intent],
        collection_id=conversation.collection_id,
        status="queued",
        stage="queued",
        input_payload=input_payload,
        output_payload={},
    )
    db.add(job)
    db.flush()

    if intent == "CASE_GENERATE":
        db.execute(
            update(WorkspaceCandidate)
            .where(
                WorkspaceCandidate.conversation_id == conversation.id,
                WorkspaceCandidate.status == "candidate",
            )
            .values(status="archived")
        )
        assistant = _new_assistant_message(
            conversation.id,
            content="",
            intent=intent,
            confidence=confidence,
            status="running",
            target_case_ids=target_ids,
            metadata={
                "workflow": True,
                "brief_operation": brief_operation,
            },
        )
        task_name = "casepilot.agent.draft_brief"
        action: dict[str, Any] = {"type": "test_brief", "job_id": str(job.id)}
    elif intent in {"KNOWLEDGE_QA", "SMALL_TALK"}:
        assistant = _new_assistant_message(
            conversation.id,
            content="",
            intent=intent,
            confidence=confidence,
            status="running",
            target_case_ids=target_ids,
            metadata={"hidden_progress": True},
        )
        task_name = "casepilot.agent.answer_question"
        action = {
            "type": "small_talk" if intent == "SMALL_TALK" else "knowledge_qa",
            "job_id": str(job.id),
        }
    else:
        formal_targets: list[dict[str, str]] = []
        for case_id in payload.target_case_ids:
            test_case = db.scalar(
                select(TestCase).where(
                    TestCase.id == case_id,
                    TestCase.space_id == conversation.space_id,
                    TestCase.deleted_at.is_(None),
                )
            )
            if test_case is None or test_case.current_revision_id is None:
                raise HTTPException(status_code=404, detail="test_case_not_found")
            formal_targets.append(
                {
                    "case_id": str(test_case.id),
                    "base_revision_id": str(test_case.current_revision_id),
                }
            )
        change_set = CaseChangeSet(
            conversation_id=conversation.id,
            generation_job_id=job.id,
            instruction=payload.content.strip(),
            scope=payload.scope,
            status="generating",
            items=[],
            created_by=account.id,
        )
        db.add(change_set)
        db.flush()
        input_payload.update(
            {
                "instruction": payload.content.strip(),
                "change_set_id": str(change_set.id),
                "formal_targets": formal_targets,
                "candidate_targets": [
                    item.model_dump(mode="json")
                    for item in payload.target_candidate_snapshots
                ],
            }
        )
        job.input_payload = input_payload
        assistant = _new_assistant_message(
            conversation.id,
            content=(
                f"正在为 {len(formal_targets) + len(payload.target_candidate_snapshots)} "
                "条用例生成字段差异。"
            ),
            intent=intent,
            confidence=confidence,
            status="running",
            target_case_ids=[
                *target_ids,
                *(item.ref for item in payload.target_candidate_snapshots),
            ],
            metadata={"change_set_id": str(change_set.id)},
        )
        task_name = "casepilot.agent.rewrite_batch"
        action = {
            "type": "change_set",
            "job_id": str(job.id),
            "change_set_id": str(change_set.id),
        }

    db.add(assistant)
    db.flush()
    assistant.related_job_id = job.id
    job.input_payload = {
        **dict(job.input_payload),
        "assistant_message_id": str(assistant.id),
    }
    context_update = {
        **dict(conversation.context),
        "active_job_id": str(job.id),
        "last_intent": intent,
        "phase": "brief_drafting" if intent == "CASE_GENERATE" else dict(
            conversation.context
        ).get("phase", "maintenance"),
    }
    if intent in {"CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE"}:
        context_update["active_operation_id"] = (
            str(operation_id) if operation_id else None
        )
    conversation.context = context_update
    conversation.updated_at = datetime.now(UTC)
    db.flush()
    return assistant, action, task_name


@router.post("/conversations", response_model=ConversationView, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    collection = (
        ensure_collection(db, account, payload.collection_id)
        if payload.collection_id
        else None
    )
    if collection and payload.space_id and collection.space_id != payload.space_id:
        raise HTTPException(status_code=422, detail="collection_space_mismatch")
    space_id = collection.space_id if collection else payload.space_id
    if space_id is None:
        raise HTTPException(status_code=422, detail="conversation_space_required")
    require_space_membership(db, account.id, space_id)
    conversation = Conversation(
        space_id=space_id,
        collection_id=collection.id if collection else None,
        account_id=account.id,
        title=payload.title.strip(),
        status="active",
        context={
            "knowledge_source_ids": [str(item) for item in payload.knowledge_source_ids],
            "document_ids": [str(item) for item in payload.document_ids],
            "use_space_knowledge": payload.use_space_knowledge,
            "phase": "idle",
            "draft_text": "",
            "active_view": "list",
            "search_query": "",
            "filters": {},
            "chat_width": 360,
            "inspector_width": 360,
            "selected_brief_version": None,
            "title_initialized": False,
        },
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _conversation_view(db, conversation)


@router.put(
    "/collections/{collection_id}/workspace",
    response_model=ConversationView,
)
def get_or_create_workspace(
    collection_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    collection = ensure_collection(db, account, collection_id)
    existing = db.scalar(
        select(Conversation)
        .where(
            Conversation.collection_id == collection.id,
            Conversation.status == "active",
        )
        .order_by(Conversation.updated_at.desc())
    )
    if existing is not None:
        return _conversation_view(db, existing)
    return create_conversation(
        ConversationCreate(
            space_id=collection.space_id,
            collection_id=collection_id,
            title="集合工作区",
        ),
        account,
        db,
    )


@router.patch(
    "/conversations/{conversation_id}/collection",
    response_model=ConversationView,
)
def bind_conversation_collection(
    conversation_id: UUID,
    payload: ConversationBindingUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    collection = ensure_collection(db, account, payload.collection_id)
    if collection.space_id != conversation.space_id:
        raise HTTPException(status_code=422, detail="collection_space_mismatch")
    if conversation.collection_id is not None:
        if conversation.collection_id == collection.id:
            return _conversation_view(db, conversation)
        raise HTTPException(status_code=409, detail="conversation_collection_locked")
    conversation.collection_id = collection.id
    current_phase = str(dict(conversation.context).get("phase", "idle"))
    conversation.context = {
        **dict(conversation.context),
        "phase": "maintenance" if current_phase == "idle" else current_phase,
    }
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)
    return _conversation_view(db, conversation)


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=KnowledgeUploadView,
    status_code=202,
)
def upload_conversation_attachments(
    conversation_id: UUID,
    account: CurrentAccount,
    db: DbSession,
    files: Annotated[list[UploadFile], File()],
) -> KnowledgeUploadView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    allowed = {
        ".pdf": {"application/pdf"},
        ".txt": {"text/plain"},
    }
    for upload in files:
        extension = Path(upload.filename or "").suffix.lower()
        mime_type = (upload.content_type or "").lower()
        if extension not in allowed or mime_type not in allowed[extension]:
            raise HTTPException(
                status_code=415,
                detail="conversation_attachment_type_not_supported",
            )
    result = _store_uploads(
        db,
        account.id,
        conversation.space_id,
        f"对话附件 {conversation.title}",
        files,
        "temporary",
    )
    source_ids = list(dict(conversation.context).get("knowledge_source_ids", []))
    source_ids.append(str(result.source.id))
    document_ids = list(dict(conversation.context).get("document_ids", []))
    document_ids.extend(str(item) for item in result.document_ids)
    conversation.context = {
        **dict(conversation.context),
        "knowledge_source_ids": list(dict.fromkeys(source_ids)),
        "document_ids": list(dict.fromkeys(document_ids)),
    }
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    return result


@router.get(
    "/collections/{collection_id}/conversations/latest",
    response_model=ConversationView,
)
def get_latest_conversation(
    collection_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    collection = ensure_collection(db, account, collection_id)
    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.collection_id == collection.id,
            Conversation.status == "active",
        )
        .order_by(Conversation.updated_at.desc())
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return _conversation_view(db, conversation)


def _encode_history_cursor(conversation: Conversation) -> str:
    payload = json.dumps(
        {
            "updated_at": conversation.updated_at.isoformat(),
            "id": str(conversation.id),
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_history_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + padding).decode()
        )
        return datetime.fromisoformat(payload["updated_at"]), UUID(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail="invalid_history_cursor") from error


@router.get("/conversations/history", response_model=ConversationHistoryPage)
def list_conversation_history(
    account: CurrentAccount,
    db: DbSession,
    space_id: Annotated[UUID | None, Query()] = None,
    query: Annotated[str, Query(alias="q", max_length=160)] = "",
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> ConversationHistoryPage:
    last_message = (
        select(ConversationMessage.content)
        .where(ConversationMessage.conversation_id == Conversation.id)
        .order_by(
            ConversationMessage.created_at.desc(),
            ConversationMessage.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    statement = (
        select(
            Conversation,
            CaseCollection.name.label("collection_name"),
            last_message.label("last_message"),
        )
        .outerjoin(CaseCollection, CaseCollection.id == Conversation.collection_id)
        .where(
            Conversation.account_id == account.id,
            Conversation.status == "active",
            or_(
                Conversation.collection_id.is_(None),
                CaseCollection.deleted_at.is_(None),
            ),
        )
    )
    if space_id is not None:
        require_space_membership(db, account.id, space_id)
        statement = statement.where(Conversation.space_id == space_id)
    normalized_query = " ".join(query.split())
    if normalized_query:
        escaped = (
            normalized_query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        statement = statement.where(
            or_(
                Conversation.title.ilike(pattern, escape="\\"),
                CaseCollection.name.ilike(pattern, escape="\\"),
                last_message.ilike(pattern, escape="\\"),
            )
        )
    if cursor:
        cursor_time, cursor_id = _decode_history_cursor(cursor)
        statement = statement.where(
            or_(
                Conversation.updated_at < cursor_time,
                (
                    (Conversation.updated_at == cursor_time)
                    & (Conversation.id < cursor_id)
                ),
            )
        )
    rows = db.execute(
        statement.order_by(
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        ).limit(limit + 1)
    ).all()
    visible_rows = rows[:limit]
    items = []
    for conversation, collection_name, latest_message in visible_rows:
        items.append(
            ConversationSummaryView(
                id=conversation.id,
                collection_id=conversation.collection_id,
                title=(
                    conversation.title
                    if dict(conversation.context).get("title_initialized")
                    else f"{collection_name or '新对话'}（未开始）"
                ),
                collection_name=collection_name,
                phase=str(dict(conversation.context).get("phase", "idle")),
                last_message_preview=" ".join(
                    str(latest_message or "").split()
                )[:80],
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
    return ConversationHistoryPage(
        items=items,
        next_cursor=(
            _encode_history_cursor(visible_rows[-1][0])
            if len(rows) > limit and visible_rows
            else None
        ),
    )


@router.get(
    "/collections/{collection_id}/workspace",
    response_model=ConversationView,
)
def get_workspace(
    collection_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    return get_latest_conversation(collection_id, account, db)


@router.get("/conversations/{conversation_id}", response_model=ConversationView)
def get_conversation(
    conversation_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    return _conversation_view(
        db,
        _ensure_conversation(db, account.id, conversation_id),
    )


@router.patch(
    "/workspaces/{conversation_id}",
    response_model=ConversationView,
)
def update_workspace_state(
    conversation_id: UUID,
    payload: WorkspaceStateUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    updates = payload.model_dump(exclude_none=True)
    model_id = updates.get("model_id")
    if model_id and not settings.is_agent_model_allowed(model_id):
        raise HTTPException(status_code=422, detail="generation_model_not_configured")
    conversation.context = {**dict(conversation.context), **updates}
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)
    return _conversation_view(db, conversation)


@router.post(
    "/workspaces/{conversation_id}/test-briefs",
    response_model=WorkspaceTestBriefView,
    status_code=201,
)
def create_test_brief(
    conversation_id: UUID,
    payload: TestBriefCreate,
    account: CurrentAccount,
    db: DbSession,
) -> WorkspaceTestBriefView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    latest_version = db.scalar(
        select(func.max(WorkspaceTestBrief.version)).where(
            WorkspaceTestBrief.conversation_id == conversation.id
        )
    ) or 0
    db.execute(
        update(WorkspaceTestBrief)
        .where(
            WorkspaceTestBrief.conversation_id == conversation.id,
            WorkspaceTestBrief.status.in_(("draft", "confirmed")),
        )
        .values(status="superseded")
    )
    brief = WorkspaceTestBrief(
        conversation_id=conversation.id,
        version=latest_version + 1,
        content=payload.content.model_dump(mode="json"),
        markdown_content=render_test_brief_markdown(
            latest_version + 1,
            payload.content.model_dump(mode="json"),
        ),
        status="draft",
        created_by=account.id,
    )
    db.add(brief)
    conversation.context = {
        **dict(conversation.context),
        "phase": "brief_review",
        "confirmed_brief_version": None,
        "active_job_id": None,
    }
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(brief)
    return _brief_view(brief)


@router.get(
    "/workspaces/{conversation_id}/test-briefs/{version}/download",
    response_class=PlainTextResponse,
)
def download_test_brief(
    conversation_id: UUID,
    version: int,
    account: CurrentAccount,
    db: DbSession,
) -> PlainTextResponse:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    brief = db.scalar(
        select(WorkspaceTestBrief).where(
            WorkspaceTestBrief.conversation_id == conversation.id,
            WorkspaceTestBrief.version == version,
        )
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="test_brief_not_found")
    collection = ensure_collection(db, account, conversation.collection_id)
    safe_name = "".join(
        character
        for character in collection.name
        if character not in '\\/:*?"<>|'
    ).strip() or "CasePilot"
    file_name = f"{safe_name}-结构化测试说明-V{version}.md"
    stored_content = dict(brief.content)
    normalized_content = TestBriefContent.model_validate(stored_content).model_dump(
        mode="json"
    )
    markdown = (
        brief.markdown_content
        if "test_object" in stored_content and brief.markdown_content
        else render_test_brief_markdown(brief.version, normalized_content)
    )
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(file_name)}"
            )
        },
    )


@router.post(
    "/workspaces/{conversation_id}/test-briefs/confirm",
    response_model=ConversationTurnView,
    status_code=202,
)
def confirm_test_brief(
    conversation_id: UUID,
    payload: TestBriefConfirmRequest,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationTurnView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    if not settings.is_agent_model_allowed(payload.model_id):
        raise HTTPException(status_code=422, detail="generation_model_not_configured")
    brief = db.scalar(
        select(WorkspaceTestBrief).where(
            WorkspaceTestBrief.conversation_id == conversation.id,
            WorkspaceTestBrief.version == payload.version,
        )
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="test_brief_not_found")
    latest_version = db.scalar(
        select(func.max(WorkspaceTestBrief.version)).where(
            WorkspaceTestBrief.conversation_id == conversation.id
        )
    )
    if brief.version != latest_version or brief.status not in {"draft", "confirmed"}:
        raise HTTPException(status_code=409, detail="test_brief_version_changed")
    brief_content = dict(brief.content)
    resolved_test_object = str(brief_content.get("test_object") or "").strip()
    if not resolved_test_object:
        resolved_test_object = _test_object_from_memory(
            _agent_conversation_memory(db, conversation.id)
        )
    if resolved_test_object:
        brief_content["test_object"] = resolved_test_object
        brief_content["open_questions"] = []
    brief_content = TestBriefContent.model_validate(brief_content).model_dump(
        mode="json"
    )
    blockers = [
        item
        for item in brief_content.get("open_questions", [])
        if item.get("blocking")
    ]
    if blockers or not str(brief_content.get("test_object") or "").strip():
        raise HTTPException(status_code=409, detail="test_brief_has_blocking_questions")
    active_job_id = dict(conversation.context).get("active_job_id")
    if active_job_id:
        active_job = db.get(GenerationJob, UUID(str(active_job_id)))
        active_status = (
            active_job.status.value
            if active_job is not None and hasattr(active_job.status, "value")
            else str(active_job.status)
            if active_job is not None
            else ""
        )
        if active_status in {"queued", "running", "awaiting_input"}:
            raise HTTPException(status_code=409, detail="workspace_generation_in_progress")

    brief.content = brief_content
    brief.markdown_content = render_test_brief_markdown(
        brief.version,
        brief_content,
    )
    if brief.status == "draft":
        brief.status = "confirmed"
        brief.confirmed_by = account.id
        brief.confirmed_at = datetime.now(UTC)
    system_user = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=f"确认结构化测试说明 V{brief.version} 并开始生成",
        intent="CASE_GENERATE",
        intent_confidence=1.0,
        status="completed",
        target_case_ids=[],
        citations=[],
        message_metadata={
            "brief_version": brief.version,
            "brief_operation": "confirm",
            "confirmation": True,
        },
    )
    db.add(system_user)
    db.flush()
    active_operation = (
        db.scalar(
            select(ConversationOperation)
            .where(
                ConversationOperation.id == brief.source_operation_id,
                ConversationOperation.conversation_id == conversation.id,
                ConversationOperation.intent == "CASE_GENERATE",
            )
            .with_for_update()
        )
        if brief.source_operation_id
        else db.scalar(
            select(ConversationOperation)
            .where(
                ConversationOperation.conversation_id == conversation.id,
                ConversationOperation.intent == "CASE_GENERATE",
                ConversationOperation.status == "awaiting_confirmation",
            )
            .order_by(ConversationOperation.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    )
    prompt = str(brief_content.get("test_objective") or "生成测试用例")
    job = GenerationJob(
        space_id=conversation.space_id,
        account_id=account.id,
        operation="generate",
        collection_id=conversation.collection_id,
        status="queued",
        stage="queued",
        input_payload={
            "prompt": prompt,
            "markdown_content": brief.markdown_content
            or render_test_brief_markdown(brief.version, brief_content),
            "file_names": [],
            "mode": settings.ai_mode,
            "model_id": payload.model_id,
            "document_ids": list(dict(conversation.context).get("document_ids", [])),
            "knowledge_source_ids": list(
                dict(conversation.context).get("knowledge_source_ids", [])
            ),
            "use_space_knowledge": bool(
                dict(conversation.context).get("use_space_knowledge", True)
            ),
            "answers": {
                str(item.get("id")): "已在确认的测试说明中解决"
                for item in brief_content.get("open_questions", [])
                if item.get("id")
            }
            | {
                "Q-TEST-OBJECT": str(brief_content.get("test_object") or "")
            },
            "persist_cases": False,
            "conversation_id": str(conversation.id),
            "conversation_memory": _agent_conversation_memory(db, conversation.id),
            "confirmed_test_brief": brief_content,
            "confirmed_test_brief_version": brief.version,
            "conversation_operation_id": (
                str(active_operation.id) if active_operation else None
            ),
        },
        output_payload={},
    )
    db.add(job)
    db.flush()
    assistant = _new_assistant_message(
        conversation.id,
        content="",
        intent="CASE_GENERATE",
        confidence=1.0,
        status="running",
        target_case_ids=[],
        metadata={
            "workflow": True,
            "brief_version": brief.version,
            "brief_operation": "confirm",
        },
    )
    db.add(assistant)
    db.flush()
    assistant.related_job_id = job.id
    if active_operation is not None:
        active_operation.status = "running"
        active_operation.related_job_id = job.id
    job.input_payload = {
        **dict(job.input_payload),
        "assistant_message_id": str(assistant.id),
    }
    conversation.context = {
        **dict(conversation.context),
        "phase": "generating",
        "confirmed_brief_version": brief.version,
        "active_job_id": str(job.id),
        "model_id": payload.model_id,
    }
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(assistant)
    task_client.send_task(
        "casepilot.agent.generate",
        args=[str(job.id)],
        task_id=str(job.id),
    )
    db.refresh(system_user)
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(system_user),
        assistant_message=_message_view(assistant),
        intent="CASE_GENERATE",
        intent_confidence=1.0,
        action={"type": "generation", "job_id": str(job.id)},
        operation_plan=(
            _operation_plan_view([active_operation]) if active_operation else None
        ),
    )


@router.patch(
    "/workspace-candidates/{candidate_id}",
    response_model=WorkspaceCandidateView,
)
def update_workspace_candidate(
    candidate_id: UUID,
    payload: WorkspaceCandidateUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> WorkspaceCandidateView:
    candidate = db.get(WorkspaceCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="workspace_candidate_not_found")
    _ensure_conversation(db, account.id, candidate.conversation_id)
    if candidate.status != "candidate":
        raise HTTPException(status_code=409, detail="workspace_candidate_not_editable")
    if payload.snapshot is not None:
        candidate.snapshot = dict(payload.snapshot)
        candidate.version += 1
    if payload.included is not None:
        candidate.included = payload.included
    candidate.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(candidate)
    return _candidate_view(candidate)


@router.post(
    "/workspaces/{conversation_id}/candidates/commit",
    response_model=list[TestCaseView],
)
def commit_workspace_candidates(
    conversation_id: UUID,
    payload: WorkspaceCandidateCommitRequest,
    account: CurrentAccount,
    db: DbSession,
) -> list[TestCaseView]:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    query = select(WorkspaceCandidate).where(
        WorkspaceCandidate.conversation_id == conversation.id,
        WorkspaceCandidate.status == "candidate",
        WorkspaceCandidate.included.is_(True),
    )
    if payload.candidate_ids:
        query = query.where(WorkspaceCandidate.id.in_(payload.candidate_ids))
    candidates = list(
        db.scalars(query.order_by(WorkspaceCandidate.position, WorkspaceCandidate.id))
    )
    if not candidates:
        raise HTTPException(status_code=409, detail="no_included_workspace_candidates")
    position = db.scalar(
        select(func.max(CollectionCaseMembership.position)).where(
            CollectionCaseMembership.collection_id == conversation.collection_id
        )
    )
    position = (position if position is not None else -1) + 1
    collection = ensure_collection(db, account, conversation.collection_id)
    created: list[TestCase] = []
    for index, candidate in enumerate(candidates):
        snapshot = dict(candidate.snapshot)
        test_case = create_test_case_record(
            db,
            collection=collection,
            payload=TestCaseCreate.model_validate(
                {
                    "case_key": f"CP-{uuid4().hex[:8].upper()}",
                    "title": snapshot.get("title") or candidate.ref,
                    "module": snapshot.get("module", ""),
                    "priority": snapshot.get("priority", "P1"),
                    "case_type": snapshot.get("case_type", "功能"),
                    "tags": snapshot.get("tags", []),
                    "preconditions": snapshot.get("preconditions", []),
                    "steps": snapshot.get("steps", []),
                    "source": "CasePilot 工作区候选",
                    "source_refs": snapshot.get("source_refs", []),
                }
            ),
            account=account,
            case_key=f"CP-{uuid4().hex[:8].upper()}",
            position=position + index,
        )
        candidate.status = "incorporated"
        created.append(test_case)
    db.execute(
        update(WorkspaceCandidate)
        .where(
            WorkspaceCandidate.conversation_id == conversation.id,
            WorkspaceCandidate.status == "candidate",
            WorkspaceCandidate.included.is_(False),
        )
        .values(status="excluded")
    )
    conversation.context = {
        **dict(conversation.context),
        "phase": "maintenance",
        "active_job_id": None,
    }
    active_operation_id = dict(conversation.context).get("active_operation_id")
    if active_operation_id:
        operation = db.get(ConversationOperation, UUID(str(active_operation_id)))
        if operation is not None:
            operation.status = "completed"
            operation.result = {
                "candidate_ids": [str(item.id) for item in candidates],
                "test_case_ids": [str(item.id) for item in created],
            }
            operation.completed_at = datetime.now(UTC)
    conversation.updated_at = datetime.now(UTC)
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=f"已将 {len(created)} 条候选用例纳入正式集合，并创建可追溯 Revision。",
            intent="CASE_GENERATE",
            intent_confidence=1.0,
            status="completed",
            target_case_ids=[str(item.id) for item in created],
            citations=[],
            message_metadata={"action": "candidates_committed"},
        )
    )
    db.commit()
    for test_case in created:
        db.refresh(test_case)
    return [
        TestCaseView.model_validate(case_to_view(db, test_case))
        for test_case in created
    ]


def _expand_conversation_targets(
    db: Session,
    conversation: Conversation,
    payload: ConversationMessageCreate,
) -> ConversationMessageCreate:
    case_ids = list(payload.target_case_ids)
    candidate_snapshots = list(payload.target_candidate_snapshots)
    candidate_refs = {item.ref for item in candidate_snapshots}
    for target in payload.targets:
        if target.collection_id and target.collection_id != conversation.collection_id:
            raise HTTPException(status_code=422, detail="target_collection_mismatch")
        if target.kind == "case":
            case_ids.extend(target.case_ids)
            for candidate_ref in target.candidate_refs:
                candidate = db.scalar(
                    select(WorkspaceCandidate).where(
                        WorkspaceCandidate.conversation_id == conversation.id,
                        WorkspaceCandidate.ref == candidate_ref,
                        WorkspaceCandidate.status == "candidate",
                    )
                )
                if candidate is not None and candidate.ref not in candidate_refs:
                    candidate_snapshots.append(
                        ConversationTargetSnapshot(
                            ref=candidate.ref,
                            version=candidate.version,
                            snapshot=dict(candidate.snapshot),
                        )
                    )
                    candidate_refs.add(candidate.ref)
            continue
        if target.kind == "previous_result":
            source = (
                db.get(ConversationOperation, target.source_operation_id)
                if target.source_operation_id
                else None
            )
            if source is None or source.conversation_id != conversation.id:
                raise HTTPException(status_code=422, detail="previous_result_not_found")
            result_ids = [
                UUID(str(item)) for item in dict(source.result).get("candidate_ids", [])
            ]
            for candidate in db.scalars(
                select(WorkspaceCandidate).where(
                    WorkspaceCandidate.id.in_(result_ids),
                    WorkspaceCandidate.conversation_id == conversation.id,
                )
            ):
                if candidate.ref in candidate_refs:
                    continue
                candidate_snapshots.append(
                    ConversationTargetSnapshot(
                        ref=candidate.ref,
                        version=candidate.version,
                        snapshot=dict(candidate.snapshot),
                    )
                )
                candidate_refs.add(candidate.ref)
            continue
        if target.kind not in {"module", "condition"}:
            continue
        if conversation.collection_id is None:
            raise HTTPException(status_code=409, detail="conversation_collection_required")
        cases = list(
            db.scalars(
                select(TestCase)
                .join(
                    CollectionCaseMembership,
                    CollectionCaseMembership.test_case_id == TestCase.id,
                )
                .where(
                    CollectionCaseMembership.collection_id == conversation.collection_id,
                    TestCase.deleted_at.is_(None),
                )
            )
        )
        for test_case in cases:
            view = case_to_view(db, test_case)
            if target.kind == "module" and view.module == target.module:
                case_ids.append(test_case.id)
            if (
                target.kind == "condition"
                and target.condition in view.preconditions
                and (not target.module or view.module == target.module)
            ):
                case_ids.append(test_case.id)
    unique_ids = list(dict.fromkeys(case_ids))
    if unique_ids:
        if conversation.collection_id is None:
            raise HTTPException(
                status_code=409,
                detail="conversation_collection_required",
            )
        member_ids = set(
            db.scalars(
                select(CollectionCaseMembership.test_case_id).where(
                    CollectionCaseMembership.collection_id
                    == conversation.collection_id,
                    CollectionCaseMembership.test_case_id.in_(unique_ids),
                )
            )
        )
        if member_ids != set(unique_ids):
            raise HTTPException(status_code=422, detail="target_collection_mismatch")
    return payload.model_copy(
        update={
            "target_case_ids": unique_ids,
            "target_candidate_snapshots": candidate_snapshots,
        }
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationTurnView,
    status_code=202,
)
def send_message(
    conversation_id: UUID,
    payload: ConversationMessageCreate,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationTurnView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    context = dict(conversation.context)
    payload = payload.model_copy(
        update={
            "knowledge_source_ids": list(
                dict.fromkeys(
                    [
                        *payload.knowledge_source_ids,
                        *(UUID(str(item)) for item in context.get("knowledge_source_ids", [])),
                    ]
                )
            ),
            "document_ids": list(
                dict.fromkeys(
                    [
                        *payload.document_ids,
                        *(UUID(str(item)) for item in context.get("document_ids", [])),
                    ]
                )
            ),
        }
    )
    payload = _expand_conversation_targets(db, conversation, payload)
    if not settings.is_agent_model_allowed(payload.model_id):
        raise HTTPException(status_code=422, detail="generation_model_not_configured")
    conversation.context = {
        **dict(conversation.context),
        "model_id": payload.model_id,
    }
    phase = str(dict(conversation.context).get("phase", "idle"))
    if phase == "brief_review" and _looks_like_brief_confirmation(payload.content):
        latest_brief = db.scalar(
            select(WorkspaceTestBrief)
            .where(WorkspaceTestBrief.conversation_id == conversation.id)
            .order_by(WorkspaceTestBrief.version.desc())
        )
        if latest_brief is None:
            raise HTTPException(status_code=409, detail="test_brief_not_found")
        return confirm_test_brief(
            conversation_id,
            TestBriefConfirmRequest(
                version=latest_brief.version,
                model_id=payload.model_id,
            ),
            account,
            db,
        )
    has_targets = bool(
        payload.target_case_ids
        or payload.target_candidate_snapshots
        or payload.targets
    )
    if payload.intent_override:
        operation_drafts = [
            {
                "intent": payload.intent_override,
                "instruction": payload.content,
                "confidence": 1.0,
                "target_kind": "case" if has_targets else "none",
                "requires_confirmation": payload.intent_override == "CASE_DELETE",
            }
        ]
    else:
        active_operation_context = [
            {
                "id": str(item.id),
                "intent": item.intent,
                "status": item.status,
                "target": dict(item.target),
                "result": dict(item.result),
            }
            for item in db.scalars(
                select(ConversationOperation)
                .where(
                    ConversationOperation.conversation_id == conversation.id,
                    ConversationOperation.status.not_in(
                        {"completed", "failed", "cancelled", "skipped"}
                    ),
                )
                .order_by(
                    ConversationOperation.created_at,
                    ConversationOperation.sequence,
                )
            )
        ]
        operation_drafts = [
            item.model_dump(mode="json")
            for item in plan_intents(
                payload.content,
                lambda clause: classify_intent(clause, has_targets, phase),
                has_targets=has_targets,
                phase=phase,
                target_context=[item.model_dump(mode="json") for item in payload.targets],
                conversation_memory=_agent_conversation_memory(db, conversation.id),
                active_operations=active_operation_context,
                provider=settings.agent_provider,
                model_name=settings.agent_model,
                base_url=settings.agent_base_url,
                api_key=settings.agent_api_key,
                timeout_seconds=settings.agent_timeout_seconds,
                tracing_enabled=settings.agent_tracing_enabled,
            ).operations
        ]
    intent = str(operation_drafts[0]["intent"])
    confidence = float(operation_drafts[0]["confidence"])
    if intent not in INTENTS:
        raise HTTPException(status_code=422, detail="invalid_conversation_intent")
    request_metadata = {"request": payload.model_dump(mode="json")}
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=payload.content.strip(),
        intent=intent,
        intent_confidence=confidence,
        status=(
            "awaiting_intent"
            if needs_intent_confirmation(intent, confidence)
            else "completed"
        ),
        target_case_ids=[str(item) for item in payload.target_case_ids],
        citations=[],
        message_metadata=request_metadata,
    )
    db.add(user_message)
    db.flush()
    operations: list[ConversationOperation] = []
    for sequence, draft in enumerate(operation_drafts):
        operation = ConversationOperation(
            conversation_id=conversation.id,
            message_id=user_message.id,
            sequence=sequence,
            intent=str(draft["intent"]),
            confidence=float(draft["confidence"]),
            status=(
                "awaiting_intent"
                if needs_intent_confirmation(
                    str(draft["intent"]), float(draft["confidence"])
                )
                else "queued"
            ),
            target={
                "kind": draft.get("target_kind", "none"),
                "selectors": [
                    item.model_dump(mode="json") for item in payload.targets
                ],
                "case_ids": [str(item) for item in payload.target_case_ids],
                "candidate_refs": [
                    item.ref for item in payload.target_candidate_snapshots
                ],
            },
            payload={
                "instruction": str(draft["instruction"]),
                "action": str(draft.get("action") or ""),
                "reason_codes": list(draft.get("reason_codes") or []),
                "depends_on": draft.get("depends_on"),
            },
            requires_confirmation=bool(draft.get("requires_confirmation")),
        )
        db.add(operation)
        operations.append(operation)
    db.flush()
    if not bool(dict(conversation.context).get("title_initialized")):
        conversation.title = summarize_conversation_title(payload.content)
        conversation.context = {
            **dict(conversation.context),
            "title_initialized": True,
        }
    assistant: ConversationMessage | None = None
    action: dict[str, Any] = {}
    if not needs_intent_confirmation(intent, confidence):
        operations[0].status = "running"
        operation_payload = payload.model_copy(
            update={"content": str(operation_drafts[0]["instruction"])}
        )
        assistant, action, task_name = _start_action(
            db,
            account,
            conversation,
            user_message,
            operation_payload,
            intent,
            confidence,
            operations[0].id,
        )
        _operation_runtime_status(operations[0], assistant, action)
    else:
        task_name = None
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(user_message)
    if assistant is not None:
        db.refresh(assistant)
    if task_name and assistant and assistant.related_job_id:
        task_client.send_task(
            task_name,
            args=[str(assistant.related_job_id)],
            task_id=str(assistant.related_job_id),
        )
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(user_message),
        assistant_message=_message_view(assistant) if assistant else None,
        intent=intent,
        intent_confidence=confidence,
        requires_intent_confirmation=needs_intent_confirmation(intent, confidence),
        action=action,
        operation_plan=_operation_plan_view(operations),
    )


@router.post(
    "/conversation-messages/{message_id}/confirm-intent",
    response_model=ConversationTurnView,
    status_code=202,
)
def confirm_message_intent(
    message_id: UUID,
    payload: IntentConfirmationRequest,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationTurnView:
    user_message = db.get(ConversationMessage, message_id)
    if user_message is None or user_message.role != "user":
        raise HTTPException(status_code=404, detail="conversation_message_not_found")
    conversation = _ensure_conversation(db, account.id, user_message.conversation_id)
    if user_message.status != "awaiting_intent":
        raise HTTPException(status_code=409, detail="message_not_awaiting_intent")
    request_payload = user_message.message_metadata.get("request", {})
    request_payload["intent_override"] = payload.intent
    message_input = ConversationMessageCreate.model_validate(request_payload)
    user_message.intent = payload.intent
    user_message.intent_confidence = 1.0
    user_message.status = "completed"
    operation = db.scalar(
        select(ConversationOperation)
        .where(
            ConversationOperation.message_id == user_message.id,
            ConversationOperation.status == "awaiting_intent",
        )
        .order_by(ConversationOperation.sequence)
    )
    if operation is not None:
        operation.intent = payload.intent
        operation.confidence = 1.0
        operation.status = "running"
    assistant, action, task_name = _start_action(
        db,
        account,
        conversation,
        user_message,
        message_input,
        payload.intent,
        1.0,
        operation.id if operation else None,
    )
    if operation is not None:
        _operation_runtime_status(operation, assistant, action)
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant)
    if task_name and assistant.related_job_id:
        task_client.send_task(
            task_name,
            args=[str(assistant.related_job_id)],
            task_id=str(assistant.related_job_id),
        )
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(user_message),
        assistant_message=_message_view(assistant),
        intent=payload.intent,
        intent_confidence=1.0,
        action=action,
        operation_plan=_operation_plan_view(
            list(
                db.scalars(
                    select(ConversationOperation)
                    .where(ConversationOperation.message_id == user_message.id)
                    .order_by(ConversationOperation.sequence)
                )
            )
        ),
    )


@router.post(
    "/conversation-operations/{operation_id}/confirm-collection",
    response_model=ConversationTurnView,
    status_code=202,
)
def confirm_conversation_operation_collection(
    operation_id: UUID,
    payload: ConversationOperationCollectionConfirmRequest,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationTurnView:
    operation = db.scalar(
        select(ConversationOperation)
        .where(ConversationOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="conversation_operation_not_found")
    conversation = _ensure_conversation(db, account.id, operation.conversation_id)
    if operation.status != "awaiting_collection":
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_not_awaiting_collection",
        )
    predecessors = list(
        db.scalars(
            select(ConversationOperation).where(
                ConversationOperation.message_id == operation.message_id,
                ConversationOperation.sequence < operation.sequence,
            )
        )
    )
    if any(item.status not in {"completed", "skipped"} for item in predecessors):
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_predecessor_pending",
        )
    if payload.collection_id is not None:
        collection = ensure_collection(db, account, payload.collection_id)
        if collection.space_id != conversation.space_id:
            raise HTTPException(status_code=422, detail="collection_space_mismatch")
    else:
        if operation.intent != "CASE_GENERATE":
            raise HTTPException(
                status_code=422,
                detail="collection_create_only_allowed_for_generation",
            )
        collection = CaseCollection(
            space_id=conversation.space_id,
            name=str(payload.create_collection_name).strip(),
            description="由 CasePilot 对话创建",
        )
        db.add(collection)
        db.flush()
        write_audit(
            db,
            space_id=conversation.space_id,
            actor_id=account.id,
            action="collection.created",
            resource_type="case_collection",
            resource_id=collection.id,
        )
    if (
        conversation.collection_id is not None
        and conversation.collection_id != collection.id
    ):
        raise HTTPException(status_code=409, detail="conversation_collection_locked")
    conversation.collection_id = collection.id
    conversation.context = {
        **dict(conversation.context),
        "phase": "maintenance",
        "bound_collection_confirmed": True,
    }
    operation.status = "queued"
    operation.result = {
        **dict(operation.result),
        "confirmed_collection_id": str(collection.id),
    }
    db.flush()
    return resume_conversation_operation(
        operation.id,
        ConversationOperationResumeRequest(),
        account,
        db,
    )


@router.post(
    "/conversation-operations/{operation_id}/continue-in-new-conversation",
    response_model=ConversationView,
    status_code=201,
)
def continue_operation_in_new_conversation(
    operation_id: UUID,
    payload: ConversationOperationContinueRequest,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    operation = db.scalar(
        select(ConversationOperation)
        .where(ConversationOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="conversation_operation_not_found")
    source = _ensure_conversation(db, account.id, operation.conversation_id)
    if operation.status != "awaiting_confirmation":
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_not_awaiting_cross_collection",
        )
    requested_collection_id = dict(operation.result).get("requested_collection_id")
    if requested_collection_id and str(payload.collection_id) != str(requested_collection_id):
        raise HTTPException(status_code=422, detail="requested_collection_mismatch")
    collection = ensure_collection(db, account, payload.collection_id)
    if collection.space_id != source.space_id:
        raise HTTPException(status_code=422, detail="collection_space_mismatch")
    if source.collection_id == collection.id:
        raise HTTPException(status_code=409, detail="collection_already_bound")
    source_message = db.get(ConversationMessage, operation.message_id)
    instruction = str(
        source_message.content
        if source_message is not None
        else operation.payload.get("instruction") or ""
    ).strip()
    conversation = Conversation(
        space_id=source.space_id,
        collection_id=collection.id,
        account_id=account.id,
        title=(instruction[:80] or f"{collection.name} · 新对话"),
        status="active",
        context={
            "knowledge_source_ids": [],
            "document_ids": [],
            "use_space_knowledge": True,
            "phase": "maintenance",
            "draft_text": instruction,
            "active_view": "list",
            "search_query": "",
            "filters": {},
            "chat_width": 360,
            "inspector_width": 360,
            "selected_brief_version": None,
            "title_initialized": bool(instruction),
            "bound_collection_confirmed": True,
        },
    )
    db.add(conversation)
    db.flush()
    operation.status = "skipped"
    operation.completed_at = datetime.now(UTC)
    operation.result = {
        **dict(operation.result),
        "requested_collection_id": str(collection.id),
        "continued_in_conversation_id": str(conversation.id),
    }
    source.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)
    return _conversation_view(db, conversation)


@router.post(
    "/conversation-operations/{operation_id}/cancel",
    response_model=ConversationOperationView,
)
def cancel_conversation_operation(
    operation_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationOperationView:
    operation = db.scalar(
        select(ConversationOperation)
        .where(ConversationOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="conversation_operation_not_found")
    _ensure_conversation(db, account.id, operation.conversation_id)
    if operation.status in {"completed", "skipped", "cancelled"}:
        return _operation_view(operation)
    if not operation.status.startswith("awaiting_"):
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_not_cancellable",
        )
    operation.status = "cancelled"
    operation.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(operation)
    return _operation_view(operation)


@router.post(
    "/conversation-operations/{operation_id}/resume",
    response_model=ConversationTurnView,
    status_code=202,
)
def resume_conversation_operation(
    operation_id: UUID,
    supplement: ConversationOperationResumeRequest,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationTurnView:
    operation = db.scalar(
        select(ConversationOperation)
        .where(ConversationOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="conversation_operation_not_found")
    conversation = _ensure_conversation(db, account.id, operation.conversation_id)
    if operation.status not in {
        "queued",
        "awaiting_intent",
        "awaiting_target",
        "failed",
    }:
        raise HTTPException(status_code=409, detail="conversation_operation_not_resumable")
    if operation.status == "awaiting_intent" and supplement.intent is None:
        raise HTTPException(status_code=422, detail="conversation_operation_intent_required")
    predecessors = list(
        db.scalars(
            select(ConversationOperation).where(
                ConversationOperation.message_id == operation.message_id,
                ConversationOperation.sequence < operation.sequence,
            )
        )
    )
    if any(item.status not in {"completed", "skipped"} for item in predecessors):
        raise HTTPException(status_code=409, detail="conversation_operation_predecessor_pending")
    user_message = db.get(ConversationMessage, operation.message_id)
    if user_message is None:
        raise HTTPException(status_code=404, detail="conversation_message_not_found")
    resume_targets = list(supplement.targets)
    if (
        not resume_targets
        and str(dict(operation.target).get("kind")) == "previous_result"
        and predecessors
    ):
        ordered_predecessors = sorted(
            predecessors,
            key=lambda item: item.sequence,
            reverse=True,
        )
        source = next(
            (
                item
                for item in ordered_predecessors
                if dict(item.result).get("candidate_ids")
            ),
            ordered_predecessors[0],
        )
        resume_targets = [
            ConversationTarget(
                kind="previous_result",
                source_operation_id=source.id,
            )
        ]
    request_data = dict(user_message.message_metadata).get("request", {})
    request_data.update(
        {
            "content": str(operation.payload.get("instruction") or user_message.content),
            "intent_override": operation.intent,
            "targets": [item.model_dump(mode="json") for item in resume_targets],
            "target_case_ids": [str(item) for item in supplement.target_case_ids],
            "target_candidate_snapshots": [
                item.model_dump(mode="json")
                for item in supplement.target_candidate_snapshots
            ],
        }
    )
    message_input = ConversationMessageCreate.model_validate(request_data)
    message_input = _expand_conversation_targets(db, conversation, message_input)
    if supplement.intent is not None:
        operation.intent = supplement.intent
        operation.confidence = 1.0
        user_message.status = "completed"
    operation.status = "running"
    assistant, action, task_name = _start_action(
        db,
        account,
        conversation,
        user_message,
        message_input,
        operation.intent,
        operation.confidence,
        operation.id,
    )
    _operation_runtime_status(operation, assistant, action)
    conversation.context = {
        **dict(conversation.context),
        "active_operation_id": str(operation.id),
    }
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(assistant)
    if task_name and assistant.related_job_id:
        task_client.send_task(
            task_name,
            args=[str(assistant.related_job_id)],
            task_id=str(assistant.related_job_id),
        )
    operations = list(
        db.scalars(
            select(ConversationOperation)
            .where(ConversationOperation.message_id == operation.message_id)
            .order_by(ConversationOperation.sequence)
        )
    )
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(user_message),
        assistant_message=_message_view(assistant),
        intent=operation.intent,
        intent_confidence=operation.confidence,
        action=action,
        operation_plan=_operation_plan_view(operations),
    )


@router.post(
    "/conversation-messages/{message_id}/retry",
    response_model=ConversationTurnView,
    status_code=202,
)
def retry_conversation_message(
    message_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationTurnView:
    failed_message = db.get(ConversationMessage, message_id)
    if (
        failed_message is None
        or failed_message.role != "assistant"
        or failed_message.status != "failed"
        or failed_message.related_job_id is None
    ):
        raise HTTPException(status_code=409, detail="message_not_retryable")
    conversation = _ensure_conversation(
        db,
        account.id,
        failed_message.conversation_id,
    )
    failed_job = db.get(GenerationJob, failed_message.related_job_id)
    if failed_job is None:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
    user_message_id = failed_job.input_payload.get("user_message_id")
    user_message = (
        db.get(ConversationMessage, UUID(str(user_message_id)))
        if user_message_id
        else None
    )
    if user_message is None or not user_message.intent:
        raise HTTPException(status_code=409, detail="retry_context_missing")
    request_payload = user_message.message_metadata.get("request", {})
    request_payload["intent_override"] = user_message.intent
    message_input = ConversationMessageCreate.model_validate(request_payload)
    assistant, action, task_name = _start_action(
        db,
        account,
        conversation,
        user_message,
        message_input,
        user_message.intent,
        1.0,
    )
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant)
    if task_name and assistant.related_job_id:
        task_client.send_task(
            task_name,
            args=[str(assistant.related_job_id)],
            task_id=str(assistant.related_job_id),
        )
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(user_message),
        assistant_message=_message_view(assistant),
        intent=user_message.intent,
        intent_confidence=1.0,
        action=action,
    )


@router.post(
    "/conversations/{conversation_id}/generation-jobs/{job_id}/answers",
    response_model=ConversationView,
    status_code=202,
)
def answer_conversation_generation(
    conversation_id: UUID,
    job_id: UUID,
    payload: GenerationAnswersRequest,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    job = db.get(GenerationJob, job_id)
    if job is None or job.collection_id != conversation.collection_id:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
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
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            content="；".join(item.answer.strip() for item in payload.answers),
            intent="CASE_GENERATE",
            intent_confidence=1.0,
            status="completed",
            target_case_ids=[],
            citations=[],
            message_metadata={
                "answers": [
                    item.model_dump(mode="json")
                    for item in payload.answers
                ]
            },
        )
    )
    assistant = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.related_job_id == job.id,
            ConversationMessage.role == "assistant",
        )
    )
    if assistant is not None:
        assistant.status = "running"
        assistant.content = "已收到澄清信息，正在从需求分析阶段继续原任务。"
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    Redis.from_url(settings.redis_url).delete(f"casepilot:generation:{job.id}:events")
    task_client.send_task(
        "casepilot.agent.generate",
        args=[str(job.id)],
        task_id=str(job.id),
    )
    db.refresh(conversation)
    return _conversation_view(db, conversation)


def _ensure_change_set(
    db: Session,
    account_id: UUID,
    change_set_id: UUID,
) -> CaseChangeSet:
    change_set = db.get(CaseChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="change_set_not_found")
    _ensure_conversation(db, account_id, change_set.conversation_id)
    return change_set


@router.get("/case-change-sets/{change_set_id}", response_model=CaseChangeSetView)
def get_change_set(
    change_set_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> CaseChangeSetView:
    return _change_set_view(_ensure_change_set(db, account.id, change_set_id))


@router.post(
    "/case-change-sets/{change_set_id}/apply",
    response_model=CaseChangeSetApplyView,
)
def apply_change_set(
    change_set_id: UUID,
    payload: ChangeSetApplyRequest,
    account: CurrentAccount,
    db: DbSession,
) -> CaseChangeSetApplyView:
    change_set = _ensure_change_set(db, account.id, change_set_id)
    if change_set.status == "applied":
        return CaseChangeSetApplyView(change_set=_change_set_view(change_set))
    if change_set.status != "ready":
        raise HTTPException(status_code=409, detail="change_set_not_ready")

    formal_items = [item for item in change_set.items if item["target_type"] == "formal"]
    formal_cases: dict[str, TestCase] = {}
    for item in formal_items:
        test_case = db.get(TestCase, UUID(item["test_case_id"]))
        if (
            test_case is None
            or str(test_case.current_revision_id) != item["base_revision_id"]
        ):
            change_set.status = "conflict"
            db.commit()
            raise HTTPException(status_code=409, detail="revision_conflict")
        formal_cases[item["ref"]] = test_case

    created_cases: list[TestCase] = []
    candidate_snapshots: list[dict] = []
    updated_items: list[dict] = []
    for item in change_set.items:
        if item["ref"] in payload.accepted_fields:
            accepted = set(payload.accepted_fields[item["ref"]])
        else:
            accepted = {
                str(diff["field"])
                for diff in item.get("field_diff", [])
                if diff.get("field") in CHANGE_FIELDS
            }
        if item.get("operation") == "delete":
            test_case = formal_cases[item["ref"]]
            confirmed = "delete" in accepted
            if confirmed:
                test_case.deleted_at = datetime.now(UTC)
                write_audit(
                    db,
                    space_id=test_case.space_id,
                    actor_id=account.id,
                    action="test_case.deleted",
                    resource_type="test_case",
                    resource_id=test_case.id,
                    payload={
                        "change_set_id": str(change_set.id),
                        "soft_delete": True,
                    },
                )
            updated_items.append(
                {
                    **item,
                    "status": "applied" if confirmed else "rejected",
                }
            )
            continue
        merged = dict(item["base_snapshot"])
        for field in accepted & CHANGE_FIELDS:
            if field in item["proposed_snapshot"]:
                merged[field] = item["proposed_snapshot"][field]

        if item["target_type"] == "candidate":
            candidate_snapshots.append(
                {
                    "ref": item["ref"],
                    "version": int(item.get("base_version", 1)) + 1,
                    "snapshot": merged,
                }
            )
        else:
            test_case = formal_cases[item["ref"]]
            latest_number = db.scalar(
                select(func.max(TestCaseRevision.revision_number)).where(
                    TestCaseRevision.test_case_id == test_case.id
                )
            ) or 0
            revision = TestCaseRevision(
                test_case_id=test_case.id,
                revision_number=latest_number + 1,
                title=str(merged["title"]).strip(),
                module=str(merged.get("module", "")).strip(),
                priority=str(merged.get("priority", "P1")),
                case_type=str(merged.get("case_type", "功能")).strip(),
                tags=normalize_tags(list(merged.get("tags", []))),
                preconditions=[
                    str(value).strip()
                    for value in merged.get("preconditions", [])
                    if str(value).strip()
                ],
                steps=[
                    {
                        "id": str(step.get("id") or uuid4()),
                        "action": str(step["action"]).strip(),
                        "expected": str(step["expected"]).strip(),
                    }
                    for step in merged.get("steps", [])
                ],
                source_refs=list(merged.get("source_refs", [])),
            )
            db.add(revision)
            db.flush()
            test_case.current_revision_id = revision.id
            candidate_id = item.get("candidate_revision_id")
            if candidate_id:
                candidate = db.get(CandidateRevision, UUID(candidate_id))
                if candidate is not None:
                    candidate.status = "applied"
                    candidate.proposed_snapshot = merged
            write_audit(
                db,
                space_id=test_case.space_id,
                actor_id=account.id,
                action="candidate_revision.applied",
                resource_type="test_case",
                resource_id=test_case.id,
                payload={
                    "change_set_id": str(change_set.id),
                    "revision_id": str(revision.id),
                    "accepted_fields": sorted(accepted),
                },
            )
            created_cases.append(test_case)
        updated_items.append({**item, "status": "applied", "applied_snapshot": merged})

    change_set.items = updated_items
    change_set.status = "applied"
    change_set.applied_at = datetime.now(UTC)
    operation = db.scalar(
        select(ConversationOperation).where(
            ConversationOperation.related_change_set_id == change_set.id
        )
    )
    if operation is not None:
        operation.status = "completed"
        operation.result = {
            "change_set_id": str(change_set.id),
            "updated_refs": [str(item["ref"]) for item in updated_items],
        }
        operation.completed_at = datetime.now(UTC)
    deleted_count = sum(
        item.get("operation") == "delete" and item.get("status") == "applied"
        for item in updated_items
    )
    has_deletions = any(
        item.get("operation") == "delete" for item in updated_items
    )
    result_message = (
        f"已确认软删除 {deleted_count} 条用例，审计记录已保留。"
        if has_deletions
        else (
            f"已应用 {len(updated_items)} 条用例变更。"
            "正式用例已创建新 Revision，候选用例已保留新快照版本。"
        )
    )
    db.add(
        ConversationMessage(
            conversation_id=change_set.conversation_id,
            role="assistant",
            content=result_message,
            intent=operation.intent if operation is not None else "CASE_MODIFY",
            intent_confidence=1.0,
            status="completed",
            target_case_ids=[str(item["ref"]) for item in updated_items],
            citations=[],
            message_metadata={
                "change_set_id": str(change_set.id),
                "action": "applied",
            },
        )
    )
    db.commit()
    for test_case in created_cases:
        db.refresh(test_case)
    return CaseChangeSetApplyView(
        change_set=_change_set_view(change_set),
        test_cases=[
            TestCaseView.model_validate(case_to_view(db, test_case))
            for test_case in created_cases
        ],
        candidate_snapshots=candidate_snapshots,
    )


@router.post("/case-change-sets/{change_set_id}/reject", response_model=CaseChangeSetView)
def reject_change_set(
    change_set_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> CaseChangeSetView:
    change_set = _ensure_change_set(db, account.id, change_set_id)
    if change_set.status in {"generating", "ready"}:
        change_set.status = "rejected"
        operation = db.scalar(
            select(ConversationOperation).where(
                ConversationOperation.related_change_set_id == change_set.id
            )
        )
        if operation is not None:
            operation.status = "cancelled"
            operation.completed_at = datetime.now(UTC)
        for item in change_set.items:
            candidate_id = item.get("candidate_revision_id")
            if candidate_id:
                candidate = db.get(CandidateRevision, UUID(candidate_id))
                if candidate is not None and candidate.status == "pending":
                    candidate.status = "rejected"
        db.add(
            ConversationMessage(
                conversation_id=change_set.conversation_id,
                role="assistant",
                content="已拒绝本次修改，原用例内容保持不变。",
                intent="CASE_MODIFY",
                intent_confidence=1.0,
                status="completed",
                target_case_ids=[
                    str(item["ref"])
                    for item in change_set.items
                ],
                citations=[],
                message_metadata={
                    "change_set_id": str(change_set.id),
                    "action": "rejected",
                },
            )
        )
        db.commit()
        db.refresh(change_set)
    return _change_set_view(change_set)
