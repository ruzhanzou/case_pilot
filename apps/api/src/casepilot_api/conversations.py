import base64
import copy
import json
import logging
from hashlib import sha256
import re
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.encoders import jsonable_encoder

from casepilot_api.planning_links import links_view, link_existing_case, link_committed_candidate, inherit_unchanged_links, reusable_current_case
from casepilot_api.models import ConversationSubmission
from casepilot_api.submissions import SubmissionTransaction, after_commit
from casepilot_api.schemas import PlanningCaseLinkRequest, GenerationAssetConfirmRequest
from casepilot_api.generation_strategy import asset_choice_from_text, generation_strategy_from_text, is_strategy_question
from casepilot_api.reuse_choices import apply_reviewer_choices, confirm_asset_reuse, reviewer_choices
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import func, or_, select, update, text
from sqlalchemy.orm import Session

from casepilot_api.agent_router import (
    draft_needs_confirmation,
    normalize_routing_text,
    plan_intents,
    select_case_scope,
    select_query_case_ids,
)
from casepilot_api.auth import CurrentAccount, require_space_membership
from casepilot_api.case_management import (
    case_to_view,
    create_test_case_record,
    ensure_collection,
    normalize_tags,
    write_audit,
)
from casepilot_api.case_scope import (
    PREVIOUS_QUERY_REFERENCE,
    common_module_path,
    filter_priority,
    has_content_condition,
    module_contains,
    requested_new_module,
    resolve_literal_content,
    resolve_module_priority_union,
    resolve_scope,
    unsupported_mutation_condition,
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
    KnowledgeDocument,
    KnowledgeSource,
    TestCase,
    TestCaseRevision,
    WorkspaceCandidate,
    WorkspaceTestBrief,
)
from casepilot_api.rewrite_dialogue import RewriteReply, interpret_rewrite_reply
from casepilot_api.schemas import (
    SOURCE_REF_EXCERPT_MAX_LENGTH,
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
    TaskReviewDecisionUpdate,
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
from casepilot_api.task_outbox import enqueue_task

router = APIRouter(prefix="/api/v1", tags=["conversations"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db_session)]
STAGE_PROGRESS = {
    "queued": 0,
    "context.prepared": 10,
    "requirement.analyzed": 22,
    "generation.awaiting_input": 25,
    "feature.generated": 38,
    "test_point.generated": 52,
    "test_case.generated": 72,
    "test_case.grounded": 76,
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
    "CASE_REVIEW",
    "CASE_DEDUP",
    "COVERAGE_ANALYZE",
    "KNOWLEDGE_QA",
    "SMALL_TALK",
    "UNRESOLVED",
}
ANALYSIS_INTENTS = {"CASE_REVIEW", "CASE_DEDUP", "COVERAGE_ANALYZE"}
ASSET_INTENTS = {"CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE", "CASE_QUERY"} | ANALYSIS_INTENTS
PENDING_CANDIDATE_SCOPE = re.compile(r"(?:全部|所有|剩余|未纳入)(?:的)?(?:未纳入(?:的)?)?(?:(\d+)\s*条)?候选(?:测试)?用例")
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
ENGLISH_CASE_GENERATION = re.compile(
    r"\b(?:generate|create|write|draft|design)\s+(?:(?:some|new|more|a set of)\s+)?"
    r"test\s+cases?\b|\btest\s+case\s+generation\b",
    re.IGNORECASE,
)
ENGLISH_CASE_MODIFY = re.compile(
    r"\b(?:modify|edit|update|rewrite|revise)\b.{0,50}"
    r"\b(?:test\s+cases?|cases?|steps?|expected\s+results?|preconditions?|"
    r"priorit(?:y|ies)|selected|them)\b",
    re.IGNORECASE,
)
ENGLISH_CASE_DELETE = re.compile(
    r"\b(?:delete|remove|archive)\b.{0,50}"
    r"\b(?:test\s+cases?|cases?|selected|old\s+ones|them)\b",
    re.IGNORECASE,
)
ENGLISH_CASE_QUERY = re.compile(
    r"\b(?:find|list|search|show)\b.{0,50}\b(?:test\s+cases?|cases?)\b",
    re.IGNORECASE,
)
NEGATED_CASE_GENERATION = re.compile(
    r"(?:不要|无需|不用|别|禁止|暂不|先别).{0,12}"
    r"(?:生成|创建|新增|补充|设计|编写).{0,40}(?:用例|场景)"
)
NEGATED_ENGLISH_CASE_ACTION = re.compile(
    r"\b(?:do\s+not|don't|never|without)\s+"
    r"(?:generate|create|write|draft|design|modify|edit|update|rewrite|"
    r"revise|delete|remove|archive)\b",
    re.IGNORECASE,
)
ENGLISH_CASE_QUESTION = re.compile(
    r"^\s*(?:how|why|what|when|whether|should|can\s+you\s+explain|"
    r"could\s+you\s+explain|(?:please\s+)?(?:explain|tell\s+me)\s+"
    r"(?:how|why|what))\b",
    re.IGNORECASE,
)
CURRENT_CASE_REFERENCE = re.compile(
    r"(?:当前用例(?!集)|这条用例|选中(?:的)?用例|"
    r"\b(?:current|selected)\s+(?:test\s+)?case\b)",
    re.IGNORECASE,
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
    r"(?:删除|移除|作废).{0,24}(?:用例|场景|模块)|"
    r"(?:用例|场景|模块).{0,24}(?:删除|移除|作废)"
)
EXPLICIT_ASSET_QUERY = re.compile(
    r"(?:查询|查找|列出|搜索|筛选|检索).{0,40}(?:用例|场景)|"
    r"(?:用例|场景).{0,24}(?:有哪些|列表|清单)"
)
EXPLICIT_ASSET_MODIFY = re.compile(
    r"(?:修改|改写|调整|替换|优化|完善|改得|改成|改为).{0,40}"
    r"(?:用例|场景|步骤|预期结果|前置条件|优先级)|"
    r"(?:用例|场景|步骤|预期结果|前置条件|优先级).{0,40}"
    r"(?:修改|改写|调整|替换|优化|完善|改得|改成|改为)|"
    r"(?:把|将).{0,40}(?:用例|步骤|预期结果|前置条件|标题).{0,24}"
    r"(?:写得|写成|补全|细化|明确)"
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
    normalized = re.sub(r"[^\S\r\n]+", " ", content.strip())
    if not normalized or any(term in normalized for term in UNKNOWN_TEST_OBJECT_TERMS):
        return ""
    module = requested_new_module(normalized)
    if module and module != "空":
        return f"{module}模块"

    candidate = ""
    count_prefix = False
    for pattern_index, pattern in enumerate((
        r"(?:测试对象|被测对象)\s*(?:是|为|：|:|包括|包含)\s*([^。；;\r\n]+)",
        r"(?:测试对象|被测对象)\s+([^。；;\r\n]+)",
        r"(?:为|针对|围绕)\s*(.+?)\s*(?:生成|设计|编写|创建)"
        r"(?:相关|恰好|至少|至多|不少于|不超过|大约|约|总共|共)?\s*"
        r"(?:[0-9一二两三四五六七八九十百]+[+＋]?\s*(?:条|个)?\s*)?"
        r"(?:候选)?(?:测试)?用例",
        r"(?:生成|设计|编写|创建)\s*(.+?)\s*(?:测试)?用例",
    )):
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1)
            count_prefix = pattern_index == 3
            break

    candidate = candidate.strip(" ：:，,。；;“”\"'的")
    # Count and candidate qualifiers describe the output, not the test object.
    if count_prefix:
        candidate = re.sub(
            r"^(?:恰好|至少|至多|不少于|不超过|大约|约|总共|共)?\s*"
            r"[0-9一二两三四五六七八九十百]+\s*"
            r"(?:[+＋]?\s*(?:条|个)\s*(?:候选)?\s*|[+＋]\s*(?:候选)?\s*|候选?$|$)",
            "", candidate,
        )
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
        or re.fullmatch(r"\d+\s*(?:条|个)?", candidate)
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
        r"(?:生成|设计|编写|创建|新增|增加|补充|重新生成|重新设计)",
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
    normalized = " ".join(normalize_routing_text(content).strip().split())
    # Trailing preservation constraints are not additional requested actions.
    # Keep standalone negations intact so their existing QA/clarification path applies.
    normalized = re.sub(
        r"[，,。；;]\s*(?:请)?(?:不要|无需|不用|禁止|暂不|不)"
        r"(?:改写|修改|删除|生成|新增|移除)"
        r"(?:(?:或|和|、)(?:改写|修改|删除|生成|新增|移除))*"
        r"[^，,。；;]*",
        "",
        normalized,
    )
    compact = normalized.casefold().strip("。！？!?，, ")
    asks_about_capabilities = ("casepilot" in compact or "你" in compact) and any(
        term in compact for term in CAPABILITY_TERMS
    )
    if (
        compact in SMALL_TALK_TERMS
        or any(term in compact for term in ("你是谁", "叫什么名字", "谢谢", "辛苦了", "再见"))
        or asks_about_capabilities
    ):
        return "SMALL_TALK", 0.99
    analysis_intent = None
    if re.search(
        r"冗余|查重|重复用例|用例重复|检查.*重复|查找.*重复|\b(?:duplicates?|redundan\w*|dedup\w*)\b",
        normalized,
        re.I,
    ):
        analysis_intent = "CASE_DEDUP"
    elif re.search(r"覆盖(?:率|缺口|不足)|遗漏|漏测|\bcoverage\b", normalized, re.I):
        analysis_intent = "COVERAGE_ANALYZE"
    elif re.search(
        r"评审|审查|检查.*(?:用例|模块)|(?<![a-z])(?:review|audit)(?![a-z])", normalized, re.I
    ):
        analysis_intent = "CASE_REVIEW"
    informational = re.search(
        r"^(?:请问)?(?:如何|怎么|什么|为什么)|^(?:how|what|why)\b", normalized, re.I
    )
    first_action = re.search(
        r"生成|编写|新增|增加|补充|修改|改写|删除|移除|检查|查重|查找|评审|审查|分析|"
        r"(?<![a-z])(?:generate|create|write|modify|rewrite|delete|remove|review|audit|check|find)(?![a-z])",
        normalized,
        re.I,
    )
    write_requested = first_action and first_action.group().casefold() in {
        "生成",
        "编写",
        "新增",
        "增加",
        "补充",
        "修改",
        "改写",
        "删除",
        "移除",
        "generate",
        "create",
        "write",
        "modify",
        "rewrite",
        "delete",
        "remove",
    }
    negated_analysis = re.search(r"(?:不要|别|暂不|无需).{0,8}(?:检查|评审|分析|查重)", normalized)
    if analysis_intent and not informational and not write_requested and not negated_analysis:
        return analysis_intent, 0.96
    if (requested_new_module(normalized) and not informational
        and not NEGATED_ENGLISH_CASE_ACTION.search(normalized) and not re.search(
        r"(?:不要|别|不必|不用|无需).{0,5}(?:新增|增加|添加|创建)", normalized
    )):
        return "CASE_GENERATE", 0.98
    if (re.search(r"补上.{0,12}(?:缺失|遗漏|场景|用例)", normalized) and not informational
        and not re.search(r"(?:不要|别|不必|无需|暂不).{0,5}补上", normalized)):
        return "CASE_GENERATE", 0.96
    if NEGATED_CASE_GENERATION.search(normalized) or NEGATED_ENGLISH_CASE_ACTION.search(normalized):
        return "KNOWLEDGE_QA", 0.96
    if ENGLISH_CASE_QUESTION.search(normalized):
        return "KNOWLEDGE_QA", 0.94
    if ENGLISH_CASE_GENERATION.search(normalized):
        return "CASE_GENERATE", 0.98
    if ENGLISH_CASE_DELETE.search(normalized):
        return "CASE_DELETE", 0.98
    if ENGLISH_CASE_QUERY.search(normalized):
        return "CASE_QUERY", 0.96
    if ENGLISH_CASE_MODIFY.search(normalized):
        return "CASE_MODIFY", 0.96 if has_targets else 0.91
    question_like = any(term in normalized for term in QA_TERMS)
    question_like = question_like or any(
        term in normalized for term in ("什么", "为何", "含义", "指什么")
    )
    generation_request = any(
        term in normalized for term in ("帮我", "请为", "请生成", "给我生成", "替我")
    )
    if NEGATED_ASSET_DELETE.search(normalized):
        return "KNOWLEDGE_QA", 0.96
    if any(term in normalized for term in DELETE_TERMS) or EXPLICIT_ASSET_DELETE.search(normalized):
        explicit_delete_request = any(
            term in normalized
            for term in ("请删除", "帮我删除", "我要删除", "立即删除", "现在删除")
        )
        if question_like and not explicit_delete_request:
            return "KNOWLEDGE_QA", 0.94
        return "CASE_DELETE", 0.98
    if any(term in normalized for term in QUERY_TERMS) or EXPLICIT_ASSET_QUERY.search(normalized):
        return "CASE_QUERY", 0.96
    if phase == "brief_review":
        if question_like and not generation_request:
            return "KNOWLEDGE_QA", 0.94
        if any(term in normalized for term in ("补充", "增加", "覆盖", "修改", "调整")):
            return "CASE_GENERATE", 0.97
        if re.fullmatch(r"(?:继续|照这个|按这个|改一下)[吧。！!]?", normalized):
            return "UNRESOLVED", 0.55
        return "KNOWLEDGE_QA", 0.82
    if "测试说明" in normalized and any(
        term in normalized for term in ("修改", "调整", "补充", "增加", "删除")
    ):
        return "CASE_GENERATE", 0.98
    explicitly_generates_cases = bool(
        re.search(
            r"(?:生成|设计|编写|创建|新增|增加|补充|重新生成|重新设计)"
            r"[^。；;]{0,40}?(?:测试)?用例",
            normalized,
        )
    )
    if question_like and not generation_request:
        return "KNOWLEDGE_QA", 0.94
    if explicitly_generates_cases and not re.search(
        r"(?:修改|改写|调整).{0,8}(?:刚|已|上述|前面)生成", normalized
    ):
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
    if modify_score and has_targets and any(term in normalized for term in MODIFY_OBJECT_TERMS):
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


def small_talk_response(content: str) -> str:
    normalized = " ".join(content.strip().split()).casefold()
    if any(term in normalized for term in ("谢谢", "辛苦了", "thank")):
        return "不客气，有需要时继续告诉我即可。"
    if any(term in normalized for term in ("再见", "晚安", "bye")):
        return "再见，需要继续维护测试用例时随时回来。"
    if any(term in normalized for term in CAPABILITY_TERMS) or any(
        term in normalized for term in ("你是谁", "叫什么")
    ):
        return (
            "我是 CasePilot，可以帮你生成、修改、删除和查询测试用例，"
            "也可以回答测试与工程问题。"
        )
    return "你好！我是 CasePilot。你可以直接告诉我想生成、修改、删除或查询哪些测试用例。"


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
    planning = content.get("planning") or {}
    reuse = planning.get("reuse") or {}
    if reuse:
        labels = {"fresh": "全新生成", "regression": "回归补充", "change": "按变更生成", "new": "新增", "reuse": "复用", "modify": "修改"}
        lines.extend(["", "## 生成与复用策略", "", labels.get(reuse.get("strategy"), "全新生成"), reuse.get("note", "")])
        for item in reuse.get("decisions", []):
            source = item.get("source") or {}
            choice = reuse.get("user_choices", {}).get(item["point_id"])
            choice_label = "不纳入本次" if choice == "exclude" else "重新生成" if choice == "new" else "使用建议"
            lines.append(f"- {item['point_id']}：建议{labels.get(item['action'], item['action'])}；本次{choice_label}；{item.get('reason', '')}；{source.get('label', '')} {source.get('locator', '')}")
    if planning.get("test_points"):
        lines.extend(["", "## 测试规划", ""])
        for feature in planning.get("feature_points", []):
            lines.append(f"- {feature['module']} / {feature['name']}")
            for point in planning["test_points"]:
                if feature["id"] in point["feature_point_ids"]:
                    scenario = point.get("scenario") or feature["name"]
                    lines.append(f"  - {scenario} / {point['title']}（待生成）")
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
        source_message_id=operation.message_id,
        completed_at=operation.completed_at,
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
    assistant.message_metadata = {
        **dict(assistant.message_metadata),
        "operation_id": str(operation.id),
        "source_message_id": str(operation.message_id),
        "source_operation_id": dict(operation.payload).get("source_operation_id"),
    }
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
    # Persist the confirmation receipt in the same transaction as collection
    # binding, the assistant message and job dispatch. A lost response must not
    # require starting another task or recreating the collection.
    confirmation = dict(operation.payload).get("collection_confirmation_request")
    if confirmation and not dict(operation.payload).get("collection_confirmation_receipt"):
        operation.payload = {
            **dict(operation.payload),
            "collection_confirmation_receipt": {
                "assistant_message_id": str(assistant.id),
                "action": jsonable_encoder(action),
            },
        }
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


def _messages_with_attachments(db, conversation, messages, pending=None):
    """Attach uploads to the next sent user message; retain unsent files in the composer."""
    views = [_message_view(message) for message in messages]
    document_ids = dict(conversation.context).get("document_ids", [])
    if not document_ids:
        return views
    documents = db.scalars(
        select(KnowledgeDocument)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
        .where(
            KnowledgeDocument.id.in_([UUID(str(item)) for item in document_ids]),
            KnowledgeDocument.space_id == conversation.space_id,
            KnowledgeSource.deleted_at.is_(None),
        )
    )
    user_views = sorted((view for view in views if view.role == "user"),
                        key=lambda view: (view.created_at, str(view.id)))
    for document in documents:
        expires_at = getattr(document, "expires_at", None)
        expired = expires_at is not None and expires_at <= datetime.now(UTC)
        attachment = {
            "id": str(document.id), "name": document.original_name,
            "size": document.size_bytes, "mime_type": document.mime_type,
            "status": "expired" if expired else document.status,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "error_code": getattr(document, "error_code", None),
        }
        owner = next((view for view in user_views if view.created_at >= document.created_at), None)
        if owner is None:
            if pending is not None:
                pending.append(attachment)
            continue
        # Return a projection; reading a conversation must not mutate persisted metadata.
        attached = [item for item in owner.metadata.get("attachments", [])
                    if item.get("id") != str(document.id)]
        owner.metadata = {**owner.metadata, "attachments": [*attached, attachment]}
    return views



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
    operation_history = list(operations)
    if operations:
        active_operation = next(
            (
                item
                for item in sorted(
                    operations,
                    key=lambda item: (item.status == "running", item.created_at, item.sequence),
                    reverse=True,
                )
                if item.status == "running"
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
                progress=(int((job.output_payload or {})['analysis_progress'].get('progress', 0))
                          if status == 'running' and (job.output_payload or {}).get('analysis_progress')
                          else STAGE_PROGRESS.get(job.stage, 0)),
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
    pending_attachments = []
    message_views = _messages_with_attachments(db, conversation, messages, pending_attachments)
    # Project persisted quality notes without another request or mutating messages.
    quality_by_job = {
        job.id: dict(job.output_payload or {}).get("quality", {}).get("issues", [])
        for job in jobs if job.operation == "generate"
    }
    for view in message_views:
        issues = quality_by_job.get(view.related_job_id)
        if issues:
            view.metadata = {**view.metadata, "generation_quality_issues": issues}
    provenance = {}
    if conversation.collection_id:
        for source_context in db.scalars(select(Conversation.context["selected_asset_provenance"]).where(
            Conversation.collection_id == conversation.collection_id,
            Conversation.context.op("?")("selected_asset_provenance"),
        ).order_by(Conversation.created_at)):
            provenance.update(dict(source_context or {}))
    provenance.update(dict(conversation.context).get("selected_asset_provenance", {}))
    return ConversationView(
        id=conversation.id,
        space_id=conversation.space_id,
        collection_id=conversation.collection_id,
        title=conversation.title,
        status=conversation.status,
        context={**dict(conversation.context), "pending_attachments": pending_attachments,
                 "selected_asset_provenance": provenance},
        planning_case_links=links_view(db, conversation),
        messages=message_views,
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
        operation_history=[_operation_view(item) for item in operation_history],
        candidate_history=[_candidate_view(item) for item in db.scalars(
            select(WorkspaceCandidate)
            .where(WorkspaceCandidate.conversation_id == conversation.id)
            .order_by(WorkspaceCandidate.created_at, WorkspaceCandidate.position)
        )],
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _ensure_conversation(
    db: Session,
    account_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.account_id != account_id:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    require_space_membership(db, account_id, conversation.space_id)
    return conversation


def collection_workspace_context(context: dict[str, Any]) -> dict[str, Any]:
    """Enter formal-case maintenance when opening a collection workspace."""
    normalized = dict(context)
    if str(normalized.get("phase", "idle")) == "idle":
        normalized["phase"] = "maintenance"
    return normalized


def terminal_workspace_context(
    context: dict[str, Any],
    *,
    operation: str,
    has_candidates: bool,
    has_brief: bool,
) -> dict[str, Any]:
    phase = (
        "candidate_review"
        if has_candidates
        else "brief_review"
        if has_brief or operation == "generate"
        else "maintenance"
    )
    return {
        **context,
        "phase": phase,
        "active_job_id": None,
        "active_operation_id": None,
    }


def recover_terminal_workspace_job(db: Session, conversation: Conversation) -> None:
    # A GET may have loaded this object before another request started a new job.
    # Serialize recovery with message sends and re-read the current job pointer.
    if conversation.context.get("phase") not in {"generating", "brief_drafting"}:
        return
    db.refresh(conversation, with_for_update=True)
    context = dict(conversation.context)
    if context.get("phase") not in {"generating", "brief_drafting"}:
        return
    raw_job_id = context.get("active_job_id")
    if not raw_job_id:
        return
    try:
        job = db.get(GenerationJob, UUID(str(raw_job_id)))
    except ValueError:
        job = None
    if job is None:
        return
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status not in {"completed", "failed", "cancelled"}:
        return
    if job.operation not in {"generate", "draft_brief"}:
        return
    has_candidates = db.scalar(
        select(WorkspaceCandidate.id)
        .where(
            WorkspaceCandidate.conversation_id == conversation.id,
            WorkspaceCandidate.status == "candidate",
        )
        .limit(1)
    ) is not None
    has_brief = db.scalar(
        select(WorkspaceTestBrief.id)
        .where(WorkspaceTestBrief.conversation_id == conversation.id)
        .limit(1)
    ) is not None
    conversation.context = terminal_workspace_context(
        context,
        operation=job.operation,
        has_candidates=has_candidates,
        has_brief=has_brief,
    )
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)


def _require_idle_conversation(db: Session, conversation: Conversation) -> None:
    db.refresh(conversation, with_for_update=True)
    active_job = db.scalar(
        select(GenerationJob.id)
        .join(ConversationMessage, ConversationMessage.related_job_id == GenerationJob.id)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            GenerationJob.status.in_(["queued", "running"]),
        )
        .limit(1)
    )
    if active_job is not None:
        raise HTTPException(status_code=409, detail="conversation_task_running")



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


def _explicit_collection_mention(content: str, name: str) -> bool:
    """Only collection references, not words in ordinary case instructions."""
    escaped = re.escape(name.strip())
    if not escaped:
        return False
    # Quoted names or collection-qualified names express a target explicitly.
    patterns = (
        rf'["“「《]\s*{escaped}\s*["”」》]',
        rf"(?<!\w)collection\s+(?:named\s+)?['\"]?{escaped}(?![\w-])",
        rf"(?<![\w-]){escaped}\s+collection(?!\w)",
        rf"(?:用例集(?:合)?|集合)\s*[：:]?\s*['\"]?{escaped}(?![a-zA-Z0-9_-])",
        rf"{escaped}\s*(?:用例集(?:合)?|集合)",
    )
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)


def _collection_candidates(
    db: Session,
    conversation: Conversation,
    content: str,
    *,
    explicit_only: bool = False,
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
        and (not explicit_only or _explicit_collection_mention(content, item.name))
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
        explicit_only=conversation.collection_id is not None,
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
                "require_new_collection": payload.generation_strategy in {"select", "select_and_generate"},
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
    if (mentioned_collection_id and mentioned_collection_id != conversation.collection_id
            and payload.generation_strategy not in {"select", "select_and_generate"}):
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


def _load_scope_snapshots(db: Session, conversation: Conversation) -> list[dict]:
    rows = db.execute(
        select(
            TestCase.id,
            TestCase.case_key,
            TestCaseRevision.title,
            TestCaseRevision.module,
            TestCaseRevision.priority,
            TestCaseRevision.description,
            TestCaseRevision.case_type,
            TestCaseRevision.tags,
            TestCaseRevision.preconditions,
            TestCaseRevision.steps,
        )
        .join(TestCaseRevision, TestCaseRevision.id == TestCase.current_revision_id)
        .join(CollectionCaseMembership, CollectionCaseMembership.test_case_id == TestCase.id)
        .where(
            CollectionCaseMembership.collection_id == conversation.collection_id,
            TestCase.space_id == conversation.space_id,
            TestCase.deleted_at.is_(None),
        )
        .order_by(CollectionCaseMembership.position, TestCase.id)
    ).mappings()
    return [dict(row) for row in rows]


def _open_mutation_operation(db, conversation, exclude_id=None):
    context = dict(conversation.context)
    if "active_mutation_task_id" in context:
        operation_id = context.get("active_mutation_operation_id")
        if not operation_id or str(operation_id) == str(exclude_id):
            return None
        return db.get(ConversationOperation, UUID(str(operation_id)))
    # Restore older conversations that predate explicit task lifecycles.
    pending = list(db.scalars(select(ConversationOperation).where(
        ConversationOperation.conversation_id == conversation.id,
        ConversationOperation.intent.in_({"CASE_MODIFY", "CASE_GENERATE"}),
        ConversationOperation.status == "awaiting_confirmation",
        ConversationOperation.id != exclude_id,
    ).order_by(ConversationOperation.created_at.desc())))
    return pending[0] if pending else None


def _rewrite_proposal_source(db, source):
    """Skip unsuccessful rounds without losing the last reviewable proposal."""
    seen = set()
    while source is not None and source.id not in seen:
        seen.add(source.id)
        change_id = getattr(source, "related_change_set_id", None)
        if change_id:
            change = db.get(CaseChangeSet, change_id)
            if change is not None and change.status == "superseded":
                successor_id = dict(source.result).get("superseded_by")
                if successor_id:
                    successor = db.scalar(select(ConversationOperation).where(
                        ConversationOperation.conversation_id == source.conversation_id,
                        ConversationOperation.related_change_set_id == UUID(successor_id),
                    ))
                    if successor is not None:
                        source = successor
                        continue
            # Applied/discarded/conflicting proposals are boundaries, not drafts
            # to resurrect. Only failed attempts may fall back to their parent.
            if change is not None and change.status != "failed":
                return source
        # Generation/query results are valid target sources without a change set.
        result = dict(getattr(source, "result", {}) or {})
        if any(result.get(key) for key in (
            "candidate_ids", "workspace_candidate_ids", "test_case_ids", "query_cases"
        )):
            return source
        parent_id = dict(source.payload).get("source_operation_id")
        if not parent_id:
            return source
        parent = db.get(ConversationOperation, UUID(str(parent_id)))
        if parent is None or parent.conversation_id != source.conversation_id:
            return source
        source = parent
    return source


def _brief_belongs_to_generation_task(brief, source, operation) -> bool:
    if source is None:
        # Manually authored draft briefs remain editable before generation.
        return brief.source_operation_id is None and brief.status == "draft"
    source_task = str(dict(source.payload).get("task_id") or source.id)
    current_task = str(dict(operation.payload).get("task_id") or operation.id)
    return source_task == current_task


def _link_rewrite_round(db, conversation, operation, payload, original_instruction=None):
    """A mutation task stays open until a review action closes it."""
    if operation is None or operation.intent not in {"CASE_MODIFY", "CASE_GENERATE"}:
        return payload
    if not dict(operation.payload).get("task_id"):
        source = _open_mutation_operation(db, conversation, operation.id)
        operation.payload = {
            **dict(operation.payload),
            "task_id": str(dict(source.payload).get("task_id") or source.id)
            if source
            else str(operation.id),
            "task_intent": dict(source.payload).get("task_intent", source.intent)
            if source
            else operation.intent,
            "task_revision": int(dict(source.payload).get("task_revision", 1)) + 1 if source else 1,
            "source_operation_id": str(source.id) if source else None,
            "asset_reference_sources": dict(operation.payload).get("asset_reference_sources",
                dict(source.payload).get("asset_reference_sources", []) if source else []),
            "asset_reference_target_scope": dict(operation.payload).get("asset_reference_target_scope",
                dict(source.payload).get("asset_reference_target_scope") if source else None),
        }
        if source is None and payload.source_operation_id:
            evidence = db.get(ConversationOperation, payload.source_operation_id)
            if (
                evidence is not None
                and evidence.conversation_id == conversation.id
                and evidence.intent in ANALYSIS_INTENTS | {"CASE_QUERY"}
            ):
                operation.payload = {
                    **dict(operation.payload),
                    "source_operation_id": str(evidence.id),
                }
    conversation.context = {
        **dict(conversation.context),
        "active_mutation_task_id": operation.payload["task_id"],
        "active_mutation_operation_id": str(operation.id),
    }
    source_id = dict(operation.payload).get("source_operation_id")
    if source_id:
        updates = {"source_operation_id": UUID(source_id)}
        if operation.intent == "CASE_MODIFY" and not (
            payload.targets or payload.target_case_ids or payload.target_candidate_snapshots
        ):
            source = _rewrite_proposal_source(db, db.get(ConversationOperation, UUID(source_id)))
            updates["targets"] = [
                ConversationTarget(
                    kind="previous_result",
                    source_operation_id=source.id if source else UUID(source_id),
                )
            ]
        payload = payload.model_copy(update=updates)
    return payload


def _finish_mutation_task(db, operation, *, discard=False):
    payload = getattr(operation, "payload", None)
    if not isinstance(payload, dict) or not payload.get("task_id"):
        return
    conversation = db.get(Conversation, operation.conversation_id)
    if conversation is None:
        return
    operation.result = {**dict(operation.result), "task_closed": True}
    if str(dict(conversation.context).get("active_mutation_task_id")) != payload["task_id"]:
        return
    context = {**dict(conversation.context), "active_mutation_task_id": None, "active_mutation_operation_id": None}
    db.execute(update(ConversationOperation).where(
        ConversationOperation.conversation_id == conversation.id,
        ConversationOperation.payload["task_id"].astext == payload["task_id"],
        ConversationOperation.id != operation.id,
        ConversationOperation.status.like("awaiting_%"),
    ).values(status="cancelled" if discard else "completed", completed_at=datetime.now(UTC)))
    if discard:
        task_messages = select(ConversationOperation.message_id).where(
            ConversationOperation.conversation_id == conversation.id,
            ConversationOperation.payload["task_id"].astext == payload["task_id"],
        )
        db.execute(update(ConversationOperation).where(
            ConversationOperation.conversation_id == conversation.id,
            ConversationOperation.message_id.in_(task_messages),
            ConversationOperation.status == "queued",
        ).values(status="cancelled", completed_at=datetime.now(UTC)))
    if discard and payload.get("task_intent") == "CASE_GENERATE":
        db.execute(update(WorkspaceCandidate).where(
            WorkspaceCandidate.conversation_id == conversation.id,
            WorkspaceCandidate.status == "candidate",
        ).values(status="excluded"))
        context.update(phase="maintenance", active_operation_id=None, active_job_id=None)
    conversation.context = context


def _is_inventory_query(intent: str, content: str) -> bool:
    return (intent == "CASE_QUERY" and bool(re.search(r"多少|数量|统计|汇总", content))
            and (("正式" in content and "候选" in content)
                 or bool(re.search(r"(?:当前)?各模块用例数量", content))))


def _inventory_summary(case_context: list[dict]) -> str:
    lines = []
    for kind, label in (("formal", "正式用例"), ("candidate", "待审阅候选")):
        rows = [item for item in case_context if item["target_type"] == kind]
        modules: dict[str, int] = {}
        for item in rows:
            name = item["snapshot"].get("module") or "未分类"
            modules[name] = modules.get(name, 0) + 1
        lines.append(f"{label} {len(rows)} 条：" + ("、".join(f"{name} {count} 条" for name, count in sorted(modules.items())) or "无"))
    return "\n".join(lines)


def _resolve_model_scope(db, conversation, payload, intent):
    from agents import ModelBehaviorError
    from openai import APIConnectionError, InternalServerError, RateLimitError
    from pydantic import ValidationError

    formal = [{**case, "kind": "formal"} for case in _load_scope_snapshots(db, conversation)]
    candidates = list(db.scalars(select(WorkspaceCandidate).where(
        WorkspaceCandidate.conversation_id == conversation.id,
        WorkspaceCandidate.status == "candidate",
    )))
    catalog = formal + [{**dict(c.snapshot), "id": str(c.id), "case_key": c.ref,
                        "kind": "candidate"} for c in candidates]
    # There are no existing assets to select in a new collection.
    if intent == "CASE_GENERATE" and not catalog:
        return payload.model_copy(update={
            "targets": [], "target_case_ids": [], "target_candidate_snapshots": [],
        }), None
    # Only a complete single-reference command bypasses semantic selection.
    # Compound conditions and additional actions must still be interpreted together.
    exact = re.fullmatch(
        r"(?:查询|查看|删除|丢弃)\s*(?:用例\s*)?([A-Za-z0-9_-]+)\s*[。.!！]?",
        payload.content.strip(),
    ) if intent in {"CASE_QUERY", "CASE_DELETE"} else None
    if exact:
        matches = [case for case in catalog
                   if exact[1] in {str(case["id"]), str(case.get("case_key", ""))}]
        if len(matches) == 1:
            chosen = matches[0]
            return payload.model_copy(update={
                "targets": [],
                "target_case_ids": [UUID(str(chosen["id"]))] if chosen["kind"] == "formal" else [],
                "target_candidate_snapshots": [ConversationTargetSnapshot(
                    ref=c.ref, version=c.version, snapshot=dict(c.snapshot))
                    for c in candidates if str(c.id) == str(chosen["id"])],
            }), None
        return payload, "指定编号不存在或不唯一，请检查完整用例编号。"
    allowed = {str(case["id"]) for case in catalog}
    ref_ids = {str(case.get("case_key", "")): str(case["id"]) for case in catalog}
    # The expansion helper defaults to the collection for legacy callers. That
    # default is not a user selection and must not bias semantic scope routing.
    selected = (_expand_conversation_targets(db, conversation, payload)
                if payload.targets or payload.target_case_ids or payload.target_candidate_snapshots
                else payload)
    selected_order = list(dict.fromkeys(
        [str(ref) for ref in selected.target_case_ids]
        + [ref_ids[item.ref] for item in selected.target_candidate_snapshots if item.ref in ref_ids]
    ))
    selected_ids = set(selected_order)
    latest = db.scalar(select(ConversationOperation).where(
        ConversationOperation.conversation_id == conversation.id,
        ConversationOperation.intent == "CASE_QUERY",
        ConversationOperation.status == "completed",
    ).order_by(ConversationOperation.created_at.desc()).limit(1))
    latest_query = None
    if latest is not None and latest.conversation_id == conversation.id:
        target = dict(latest.target)
        query_ids = {str(ref) for ref in target.get("case_ids", [])}
        query_ids.update(ref_ids[ref] for ref in target.get("candidate_refs", []) if ref in ref_ids)
        latest_query = {"ids": sorted(query_ids & allowed), "operation_id": str(latest.id)}
    source = db.get(ConversationOperation, payload.source_operation_id) if payload.source_operation_id else None
    if source is not None and source.conversation_id != conversation.id:
        return payload, "引用的结果不属于当前对话，请重新选择。"
    source = _rewrite_proposal_source(db, source)
    previous = db.get(CaseChangeSet, source.related_change_set_id) if source and source.related_change_set_id else None
    proposal = None
    if previous is not None:
        pending = [item for item in previous.items if item.get("status") not in {"applied", "rejected"}]
        proposal = {"status": previous.status,
                    "pending_ids": [ref_ids.get(str(item["ref"]), str(item["ref"])) for item in pending],
                    "items": [{"ref": item["ref"], "snapshot": item.get("proposed_snapshot", {})}
                              for item in pending]}
    context = {"phase": dict(conversation.context).get("phase", "maintenance"),
               "selected_ids": [ref for ref in selected_order if ref in allowed],
               "current_case_id": str(dict(conversation.context).get("selected_case_id") or ""),
               "latest_query": latest_query, "proposal": proposal}
    # Proposal refs are stored as asset IDs; both IDs and visible case keys are
    # legitimate references. Neither may resolve outside this catalog.
    known_keys = {key.casefold() for key in ref_ids} | {ref.casefold() for ref in allowed}
    explicit_user_ids = set()
    for case in catalog:
        for key in {str(case["id"]), str(case.get("case_key", ""))}:
            if key and re.search(
                rf"(?<![A-Za-z0-9_-]){re.escape(key)}(?![A-Za-z0-9_-])",
                payload.content,
                re.I,
            ):
                explicit_user_ids.add(str(case["id"]))
    deadline = monotonic() + settings.routing_timeout_seconds
    try:
        # A malformed model reference is not evidence that the user's target is
        # missing. Allow one grounded correction, then apply every safety check
        # below unchanged. Never silently remove unknown references or widen IDs.
        for attempt in range(2):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("scope_routing_budget_exhausted")
            try:
                from casepilot_api.scope_filter import select_large_scope

                selector = select_large_scope if len(catalog) > 2000 else select_case_scope
                decision = selector(payload.content, catalog, context, intent=intent,
                    model_name=settings.routing_model, base_url=settings.agent_base_url,
                    api_key=settings.agent_api_key, timeout_seconds=remaining,
                    tracing_enabled=settings.agent_tracing_enabled)
            except (TimeoutError, APIConnectionError, InternalServerError, RateLimitError,
                    ModelBehaviorError, ValidationError):
                if attempt:
                    raise
                continue
            unknown_keys = [
                key for key in decision.referenced_case_keys if key.casefold() not in known_keys
            ]
            if decision.ambiguous or not unknown_keys or attempt:
                break
            context = {**context, "validation_feedback": {
                "unknown_references": unknown_keys,
                "instruction": (
                    "核对这些值是否真是用户指定的用例编号；赋值不应作为编号。"
                    "真实缺失的编号必须澄清。"
                ),
            }}
    except Exception:
        return payload, "用例范围分析暂时未完成，请重试；本次没有修改或删除用例。"
    if decision.ambiguous:
        return payload, decision.clarification or "请补充需要选择的用例范围。"
    ids = set(decision.ids)
    if not ids.issubset(allowed):
        return payload, "模型返回的范围包含当前集合之外的用例，请重新描述目标。"
    if any(key.casefold() not in known_keys for key in decision.referenced_case_keys):
        return payload, "指定编号中有用例不在当前集合，请检查完整编号。"
    reference_ids = None
    if decision.reference == "previous_query":
        if latest_query is None:
            return payload, "没有可引用的查询结果，请先查询需要处理的用例。"
        reference_ids = set(latest_query["ids"])
    elif decision.reference == "previous_proposal":
        reference_ids = set(proposal["pending_ids"]) if proposal else set()
    elif decision.reference == "selection":
        reference_ids = selected_ids & allowed
        if not reference_ids and context["current_case_id"] in allowed:
            reference_ids = {context["current_case_id"]}
    if (reference_ids is not None and not ids.issubset(reference_ids)
            and not (ids and ids.issubset(explicit_user_ids))):
        return payload, "选择结果超出了引用范围，请确认需要处理的用例。"
    if decision.requested_count is not None and decision.requested_count != len(ids):
        return payload, f"当前匹配 {len(ids)} 条用例，与指定数量不一致，请确认范围。"
    if not ids and intent in {"CASE_MODIFY", "CASE_DELETE"}:
        return payload, "当前范围没有匹配用例，请重新描述目标；本次没有修改或删除用例。"
    return payload.model_copy(update={
        "targets": [],
        "target_case_ids": [UUID(str(case["id"])) for case in formal if str(case["id"]) in ids],
        "target_candidate_snapshots": [ConversationTargetSnapshot(
            ref=c.ref, version=c.version, snapshot=dict(c.snapshot))
            for c in candidates if str(c.id) in ids],
    }), None


def _resolve_action_scope(
    db: Session,
    conversation: Conversation,
    payload: ConversationMessageCreate,
    intent: str,
    scope_text: str | None = None,
    *,
    mutation_scope: bool = False,
) -> tuple[ConversationMessageCreate, str | None]:
    if conversation.collection_id is None:
        return payload, None
    # The polish dialog binds its instruction to an explicit selection. Resolve
    # IDs from storage, but do not ask a model to reinterpret that selection.
    # The normal modification preview/confirmation gate still applies.
    if payload.target_scope == "selected" and intent == "CASE_MODIFY":
        if not payload.targets or any(target.kind != "case" for target in payload.targets):
            return payload, "请选择要润色的具体用例。"
        expanded = _expand_conversation_targets(db, conversation, payload)
        requested_refs = {ref for target in payload.targets for ref in target.candidate_refs}
        resolved_refs = {item.ref for item in expanded.target_candidate_snapshots}
        if (not expanded.target_case_ids and not expanded.target_candidate_snapshots
                or not requested_refs.issubset(resolved_refs)):
            return payload, "选中的用例已不可用，请重新选择。"
        return expanded, None
    if settings.agent_provider != "mock" and intent in ASSET_INTENTS:
        return _resolve_model_scope(db, conversation, payload, intent)
    # The deterministic implementation remains only for offline mock fixtures.
    if intent in {"CASE_MODIFY", "CASE_DELETE"} and any(
        unsupported_mutation_condition(text)
        for text in (payload.content, scope_text or "")
    ):
        if intent == "CASE_MODIFY":
            # Resolve the complete condition read-only; the modification gate
            # still previews and binds these exact assets before dispatch.
            return _resolve_action_scope(
                db, conversation, payload, "CASE_QUERY", scope_text, mutation_scope=True,
            )
        exact_exclusion = resolve_scope(
            payload.content, _load_scope_snapshots(db, conversation),
        ) if re.search(
            r"排除|除了|\b(?:except|excluding)\b", payload.content, re.I,
        ) else None
        if not (exact_exclusion and "exclusion_scope_text" in exact_exclusion
                and not has_content_condition(exact_exclusion["exclusion_scope_text"])):
            return payload, ("无法准确确定这个条件对应的用例，"
                             "请先查询并选择具体用例，再确认修改范围。")
    if (intent in {"CASE_DELETE", "CASE_MODIFY"}
            and PREVIOUS_QUERY_REFERENCE.search(payload.content)
            and not payload.target_case_ids and not payload.target_candidate_snapshots
            and not payload.targets):
        source = db.scalar(select(ConversationOperation).where(
            ConversationOperation.conversation_id == conversation.id,
            ConversationOperation.intent == "CASE_QUERY",
            ConversationOperation.status == "completed",
        ).order_by(ConversationOperation.created_at.desc()).limit(1))
        if source is None or source.conversation_id != conversation.id:
            return payload, "没有可引用的查询结果，请先查询需要处理的用例。"
        linked = payload.model_copy(update={"source_operation_id": source.id,
            "targets": [ConversationTarget(kind="previous_result", source_operation_id=source.id)]})
        expanded = _expand_conversation_targets(db, conversation, linked)
        count = len(expanded.target_case_ids) + len(expanded.target_candidate_snapshots)
        reference_text = PREVIOUS_QUERY_REFERENCE.search(payload.content).group()
        requested = re.search(r"([0-9]+|[一二两三四五六七八九十]+)\s*条", reference_text)
        number = None
        if requested:
            value = requested.group(1)
            digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                      "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
            if value.isdigit():
                number = int(value)
            elif value in digits:
                number = digits[value]
            else:
                tens = re.fullmatch(r"([一二两三四五六七八九])?十([一二三四五六七八九])?", value)
                if tens is None:
                    return payload, "无法确定指定的用例数量，请使用阿拉伯数字确认范围。"
                number = digits.get(tens[1], 1) * 10 + digits.get(tens[2], 0)
        if count == 0 or (number is not None and number != count):
            return payload, f"上次查询可处理的用例有 {count} 条，请确认范围后继续。"
        return expanded, None
    if _is_inventory_query(intent, payload.content):
        formal = _load_scope_snapshots(db, conversation)
        pending = list(db.scalars(select(WorkspaceCandidate).where(
            WorkspaceCandidate.conversation_id == conversation.id,
            WorkspaceCandidate.status == "candidate",
        )))
        snapshots = formal + [{**dict(c.snapshot), "id": str(c.id), "case_key": c.ref} for c in pending]
        scope_text = re.sub(r"(?:当前)?各模块用例数量|(?:分别)?按模块(?:列出来|列出|统计|汇总|分组)", "", payload.content)
        scope_text = re.sub(r"(?:不要|无需|禁止|勿|不)(?:修改|改写|调整|删除|影响)[^，,。；;\n]*", "", scope_text)
        scope = resolve_scope(scope_text, snapshots)
        if scope and scope.get("error"):
            return payload, scope["error"]
        selected = filter_priority(payload.content, snapshots)
        ids = {str(item["id"]) for item in selected if not scope or str(item["id"]) in scope["ids"]}
        return payload.model_copy(update={
            "targets": [],
            "target_case_ids": [UUID(str(item["id"])) for item in formal if str(item["id"]) in ids],
            "target_candidate_snapshots": [ConversationTargetSnapshot(ref=c.ref, version=c.version, snapshot=dict(c.snapshot)) for c in pending if str(c.id) in ids],
        }), None
    candidates = (
        list(
            db.scalars(
                select(WorkspaceCandidate).where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.status == "candidate",
                )
            )
        )
        if dict(conversation.context).get("phase") == "candidate_review"
        and not (intent == "CASE_QUERY" and re.search(r"正式(?:用例|集合)|\bformal\b", payload.content, re.I))
        else []
    )
    pending_review_refs = None
    review_scope_text = re.sub(r"(?:保留|保持)[^，,。；;\n]*", "", payload.content)
    if intent == "CASE_MODIFY" and re.search(r"未采纳(?:建议)?|未审阅|待审阅建议", review_scope_text):
        source = db.get(ConversationOperation, payload.source_operation_id) if payload.source_operation_id else None
        source = _rewrite_proposal_source(db, source)
        previous = db.get(CaseChangeSet, source.related_change_set_id) if source and source.related_change_set_id else None
        if previous is None or previous.status != "ready":
            return payload, "当前没有可继续修改的待审阅建议，请明确用例范围。"
        pending_review_refs = {item["ref"] for item in previous.items if item.get("status") not in {"applied", "rejected"}}
        candidates = [item for item in candidates if item.ref in pending_review_refs]
    pending_scope = PENDING_CANDIDATE_SCOPE.search(payload.content) if candidates else None
    if pending_scope and pending_scope.group(1) and int(pending_scope.group(1)) != len(candidates):
        return payload, f"当前剩余 {len(candidates)} 条未纳入候选，与您指定的 {pending_scope.group(1)} 条不一致，请确认范围。"
    if candidates:
        snapshots = [
            {**dict(item.snapshot), "id": str(item.id), "case_key": item.ref} for item in candidates
        ]
    else:
        snapshots = _load_scope_snapshots(db, conversation)
    if pending_review_refs is not None:
        snapshots = [item for item in snapshots if str(item["id"]) in pending_review_refs or item.get("case_key") in pending_review_refs]
    # A fresh collection has no existing assets to protect or resolve.
    # Business requirements such as “保持未登录” are generation context.
    if intent == "CASE_GENERATE" and not snapshots:
        return payload.model_copy(update={
            "targets": [], "target_case_ids": [], "target_candidate_snapshots": [],
        }), None
    explicit_scope = None
    if intent == "CASE_QUERY" and has_content_condition(payload.content):
        # Model summaries can drop a branch or turn a search keyword into a
        # module. Derive the candidate scope from the complete user predicate.
        scope_text = None
    if scope_text:
        # A shortened semantic target must not bypass explicit names/guards in
        # the operation instruction (e.g. a missing module ending in a known name).
        explicit_scope = resolve_scope(payload.content, snapshots)
        # Preserve explicit exclusions even when the model extracts a shorter target phrase.
        guards = re.findall(
            r"(?:不要|无需|禁止|勿|不)(?:修改|改写|调整|删除|影响)[^，,。；;\n]*",
            payload.content,
        )
        scope_text = "，".join([scope_text, *guards])
    scope = explicit_scope if explicit_scope and (
        explicit_scope.get("error")
        or re.search(r"排除|除外|除了|\b(?:except|excluding)\b", payload.content, re.I)
    ) else resolve_scope(
        scope_text if scope_text is not None else payload.content, snapshots
    )
    if scope is None and explicit_scope and explicit_scope.get("ids"):
        scope = explicit_scope
    if intent == "CASE_DELETE" and re.search(
        r"冗余|重复|相似|无效|过时|\b(?:duplicate|redundant|obsolete|invalid)",
        payload.content,
        re.I,
    ):
        explicit_cases = (
            scope
            and scope.get("ids")
            and not scope.get("modules")
            and not re.search(r"全部|所有|\ball\b", payload.content, re.I)
        )
        selected_cases = scope is None and re.search(
            r"选中|当前用例|selected|current case", payload.content, re.I
        )
        if not explicit_cases and not selected_cases:
            return payload, "请先检查并选择需要删除的具体用例；不会把整个模块当作重复用例删除。"
    if scope and scope.get("error"):
        if intent == "CASE_GENERATE" and "未找到指定模块" in scope["error"]:
            # A generation request may intentionally create a new module.
            return payload.model_copy(
                update={"targets": [], "target_case_ids": [], "target_candidate_snapshots": []}
            ), None
        return payload, scope["error"]
    if scope is None and pending_scope:
        scope = {"ids": [str(candidate.id) for candidate in candidates]}
    if scope is None:
        expanded = _expand_conversation_targets(db, conversation, payload)
        if expanded.targets or expanded.target_case_ids or expanded.target_candidate_snapshots:
            if intent in ANALYSIS_INTENTS | {"CASE_QUERY"} and not (
                intent == "CASE_QUERY" and has_content_condition(payload.content)
            ):
                allowed_ids = {
                    str(item["id"]) for item in filter_priority(payload.content, snapshots)
                }
                expanded = expanded.model_copy(
                    update={
                        "target_case_ids": [
                            item for item in expanded.target_case_ids if str(item) in allowed_ids
                        ],
                        "target_candidate_snapshots": [
                            item
                            for item in expanded.target_candidate_snapshots
                            if filter_priority(payload.content, [item.snapshot])
                        ],
                    }
                )
            if intent != "CASE_QUERY" or not has_content_condition(payload.content):
                return expanded, None
            # Explicit UI/previous-result selections still need content filtering.
            refs = {str(item) for item in expanded.target_case_ids}
            refs.update(item.ref for item in expanded.target_candidate_snapshots)
            scope = {"ids": [str(item["id"]) for item in snapshots
                             if str(item["id"]) in refs or item.get("case_key") in refs]}
        if intent not in ANALYSIS_INTENTS | {"CASE_QUERY"}:
            return expanded, None
        if scope is None:
            scope = {"ids": [str(item["id"]) for item in snapshots]}
    scope_ids = set(scope["ids"])
    selected = [item for item in snapshots if str(item["id"]) in scope_ids]
    # Exact exclusions have already been resolved against collection identities.
    # Reasking a model about removed IDs makes an unambiguous scope look missing.
    condition_text = scope.get("exclusion_scope_text", payload.content)
    if intent != "CASE_GENERATE" and not (
        intent == "CASE_QUERY" and has_content_condition(condition_text)
    ):
        selected = filter_priority(
            condition_text, selected,
            mutation=mutation_scope or intent in {"CASE_MODIFY", "CASE_DELETE"},
        )
    topic_condition = intent == "CASE_QUERY" and has_content_condition(condition_text)
    priority_union = (
        resolve_module_priority_union(condition_text, selected) if topic_condition else None
    )
    literal = resolve_literal_content(condition_text, selected) if topic_condition else None
    if priority_union is not None:
        selected = priority_union
    elif literal is not None:
        selected = filter_priority(literal[1], literal[0], mutation=mutation_scope)
    elif topic_condition and selected:
        try:
            matched_ids = set(select_query_case_ids(condition_text, selected,
                model_name=settings.resolve_agent_model(payload.model_id), base_url=settings.agent_base_url,
                api_key=settings.agent_api_key, timeout_seconds=settings.agent_timeout_seconds,
                tracing_enabled=settings.agent_tracing_enabled))
        except Exception:
            return payload, "暂时无法准确匹配这些场景，请补充用例标题或编号后再查询。"
        allowed_ids = {str(item["id"]) for item in selected}
        if not matched_ids.issubset(allowed_ids):
            return payload, "查询范围未能确认，请补充用例标题或编号。"
        selected = [item for item in selected if str(item["id"]) in matched_ids]
    ids = {str(item["id"]) for item in selected}
    remaining_count = re.search(r"(\d+)\s*条未采纳", payload.content) if pending_review_refs is not None else None
    if remaining_count and int(remaining_count.group(1)) != len(selected):
        return payload, f"当前范围有 {len(selected)} 条待审阅建议，与指定数量不一致，请确认范围。"
    return payload.model_copy(
        update={
            "targets": [],
            "target_case_ids": [] if candidates else [UUID(str(item["id"])) for item in selected],
            "target_candidate_snapshots": [
                ConversationTargetSnapshot(
                    ref=item.ref, version=item.version, snapshot=dict(item.snapshot)
                )
                for item in candidates
                if str(item.id) in ids
            ],
        }
    ), None


def _start_action(
    db: Session,
    account: Any,
    conversation: Conversation,
    user_message: ConversationMessage,
    payload: ConversationMessageCreate,
    intent: str,
    confidence: float,
    operation_id: UUID | None = None,
    confirmed_targets: bool = False,
    confirm_modification: bool = False,
) -> tuple[ConversationMessage, dict[str, Any], str | None]:
    instruction = user_message.content if user_message is not None else payload.content
    if intent == "CASE_GENERATE":
        # The instruction is authoritative for each turn. A strategy carried by
        # the workspace can describe an earlier asset-reuse task and must not
        # turn a fresh generation request into a rewrite of existing cases.
        strategy = generation_strategy_from_text(instruction)
        payload = payload.model_copy(update={"generation_strategy": strategy})
    rewrite_instruction = re.sub(
        r"(?:不要|无需|禁止|勿|不(?:得)?)(?:修改|改写|重写)[^，,。；;\n]*",
        "",
        instruction,
    )
    asset_rewrite = (
        intent == "CASE_GENERATE" and payload.generation_strategy == "select_and_generate"
        and bool(re.search(r"改写|修改|重写", rewrite_instruction))
        and not re.search(r"测试点|重新规划", instruction)
        and bool(payload.targets or payload.target_case_ids or payload.target_candidate_snapshots
            or (conversation.collection_id and db.scalar(select(CollectionCaseMembership.test_case_id).where(
                CollectionCaseMembership.collection_id == conversation.collection_id).limit(1)))
            or db.scalar(select(WorkspaceCandidate.id).where(WorkspaceCandidate.conversation_id == conversation.id,
                WorkspaceCandidate.status == "candidate").limit(1)))
    )
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
    if (intent == "CASE_GENERATE" and payload.generation_strategy in {"select", "select_and_generate"}
            and not asset_rewrite
            and not dict(conversation.context).get("generation_output_collection_created")
            and not (payload.generation_strategy == "select_and_generate" and db.scalar(
                select(GenerationJob.id).where(
                    GenerationJob.input_payload["conversation_id"].astext == str(conversation.id),
                    GenerationJob.operation.in_(["draft_brief", "generate"]),
                ).limit(1)))
            and not db.scalar(select(WorkspaceTestBrief.id).where(WorkspaceTestBrief.conversation_id == conversation.id).limit(1))):
        raise HTTPException(422, "generation_new_collection_required")
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
    if intent == "SMALL_TALK":
        assistant = _new_assistant_message(
            conversation.id,
            content=small_talk_response(payload.content),
            intent=intent,
            confidence=confidence,
            status="completed",
            target_case_ids=[],
            metadata={"instant_response": True},
        )
        db.add(assistant)
        conversation.context = {
            **dict(conversation.context),
            "last_intent": intent,
        }
        conversation.updated_at = datetime.now(UTC)
        db.flush()
        return assistant, {"type": "small_talk"}, None
    new_module = requested_new_module(payload.content)
    if new_module and re.search(
        r"空模块|(?:只|仅)(?:需|要)?(?:创建|新增|增加|添加).{0,20}模块|不生成.{0,8}用例",
        payload.content,
    ):
        if new_module == "空":
            assistant = _new_assistant_message(
                conversation.id, content="请提供新模块名称。", intent=intent,
                confidence=confidence, status="awaiting_clarification", target_case_ids=[],
            )
            db.add(assistant)
            db.flush()
            return assistant, {"type": "clarification"}, None
        collection = ensure_collection(db, account, conversation.collection_id)
        db.refresh(collection, with_for_update=True)
        notes = list(collection.mind_map_notes or [])
        if not any(
            item.get("kind") == "module" and item.get("module") == new_module for item in notes
        ):
            collection.mind_map_notes = [*notes, {
                "id": f"note-{uuid4().hex}", "kind": "module",
                "parent_id": "collection-root", "text": new_module, "module": new_module,
            }]
        if operation_id:
            operation = db.get(ConversationOperation, operation_id)
            operation.payload = {**dict(operation.payload), "action": "MODULE_CREATE"}
            operation.result = {"module_path": new_module}
        assistant = _new_assistant_message(
            conversation.id, content=f"已创建模块「{new_module}」，可继续为该模块生成用例。",
            intent=intent, confidence=confidence, status="completed", target_case_ids=[],
            metadata={"action": "module_created", "module_path": new_module},
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "module_created", "module_path": new_module}, None
    operation = db.get(ConversationOperation, operation_id) if operation_id else None
    payload = _link_rewrite_round(db, conversation, operation, payload)
    plan = dict(operation.payload).get("plan", {}) if operation else {}
    questions = plan.get("clarification_questions", [])
    if intent == "CASE_MODIFY" and re.fullmatch(
        r"\s*(?:请|帮我)?(?:重写|改写|优化|修改)(?:一下)?[^，,。；;：:\n]{0,100}(?:用例|一下)[。！!]?\s*",
        payload.content,
    ) and not re.search(r"标题|步骤|优先级|预期|前置|补充|增加|删除|改为|改成|覆盖", payload.content) and not (
        operation and dict(operation.payload).get("rewrite_draft", {}).get("requirements_ready")
    ):
        questions = [
            "希望修改哪些内容或达到什么效果？请补充重写方向，以及需要保留的内容。"
        ]
    if _is_inventory_query(intent, payload.content) and "TARGET_EVIDENCE_NOT_IN_REQUEST" in plan.get("reason_codes", []):
        questions = []
    if (questions and (intent == "CASE_QUERY" or (plan.get("changes") and intent == "CASE_MODIFY"))
            and dict(conversation.context).get("phase") == "candidate_review"
            and PENDING_CANDIDATE_SCOPE.search(payload.content)
            and all(re.search(r"指定|指明|具体|哪|范围|编号|名称", question) for question in questions)):
        # Candidate membership is authoritative; the model need not ask the user
        # to repeat identities for an explicitly named remaining-candidate set.
        questions = []
    target_questions = all(
        re.search(r"指定|指明|哪.*用例|范围|编号|模块名称", question)
        for question in questions
    )
    needs_clarification = questions and not confirm_modification and not (
        target_questions and (
            # Scope selection has the full catalog; routing only knows intent.
            # Let the selector resolve scope questions instead of blocking it.
            (settings.agent_provider != "mock" and intent in ASSET_INTENTS)
            or confirmed_targets or (
                payload.source_operation_id and payload.targets
                and plan.get("target_kind") == "none"
            )
        )
    )
    if needs_clarification and intent != "CASE_MODIFY":
        assistant = _new_assistant_message(
            conversation.id, content="\n".join(questions), intent=intent,
            confidence=confidence, status="awaiting_clarification", target_case_ids=[],
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None
    scope_text = plan.get("target_text") if plan.get("routing_source") == "semantic" else None
    if confirmed_targets:
        payload, scope_error = _expand_conversation_targets(db, conversation, payload), None
    else:
        # Semantic selection needs the original scope as well as the latest change.
        payload, scope_error = _resolve_action_scope(
            db, conversation,
            payload.model_copy(update={"content": payload.content.rsplit("\n补充说明：", 1)[-1]})
            if settings.agent_provider == "mock" and "\n补充说明：" in payload.content else payload,
            # Asset discovery is transported as generation, but its eventual
            # rewrite must bind a mutation scope before the asset review.
            "CASE_MODIFY" if asset_rewrite else intent, scope_text or None
        )
        if operation:
            payload = payload.model_copy(update={
                "content": str(operation.payload.get("instruction") or payload.content),
            })
    if scope_error:
        if operation is not None and intent == "CASE_MODIFY":
            operation.target = {**dict(operation.target), "resolved": False}
            operation.payload = {**dict(operation.payload), "modification_confirmation": None}
        assistant = _new_assistant_message(
            conversation.id,
            content=scope_error,
            intent=intent,
            confidence=confidence,
            status="awaiting_clarification",
            target_case_ids=[],
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None
    if operation_id:
        operation = db.get(ConversationOperation, operation_id)
        if operation is not None:
            operation.target = {
                **dict(operation.target),
                "case_ids": [str(item) for item in payload.target_case_ids],
                "candidate_refs": [item.ref for item in payload.target_candidate_snapshots],
                "resolved": intent != "CASE_MODIFY" or bool(
                    payload.target_case_ids or payload.target_candidate_snapshots
                ),
            }
            if intent in ASSET_INTENTS:
                refs = [("case_ids", str(item)) for item in payload.target_case_ids]
                refs += [
                    ("candidate_refs", item.ref) for item in payload.target_candidate_snapshots
                ]
                selections = []
                for offset in range(0, len(refs), 100):
                    group = refs[offset : offset + 100]
                    selections.append(
                        {
                            "label": f"{len(group)} cases",
                            "target": {
                                "kind": "case",
                                "case_ids": [ref for kind, ref in group if kind == "case_ids"],
                                "candidate_refs": [
                                    ref for kind, ref in group if kind == "candidate_refs"
                                ],
                            },
                        }
                    )
                conversation.context = {
                    **dict(conversation.context),
                    "selected_targets": selections,
                }
    if needs_clarification and intent == "CASE_MODIFY":
        # Scope and requirements are independent: retain resolved identities even
        # while asking for direction, so a short reply can resume this same draft.
        if operation is not None:
            operation.payload = {**dict(operation.payload), "modification_confirmation": None,
                "rewrite_draft": {
                    **dict(operation.payload).get("rewrite_draft", {}),
                    "version": 1,
                    "scope_instruction": str(plan.get("target_text") or payload.content),
                    "requirements": payload.content,
                    "requirements_ready": False,
                    "scope_resolved": bool(payload.target_case_ids or payload.target_candidate_snapshots),
                }}
        assistant = _new_assistant_message(
            conversation.id, content="\n".join(questions), intent=intent,
            confidence=confidence, status="awaiting_clarification",
            target_case_ids=[str(item) for item in payload.target_case_ids],
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None
    if intent == "CASE_MODIFY":
        payload = _link_rewrite_round(db, conversation, operation, payload, user_message.content)
    target_ids = [str(item) for item in payload.target_case_ids]
    case_context: list[dict[str, Any]] = [
        {
            "ref": item.ref,
            "target_type": "candidate",
            "snapshot": item.snapshot,
        }
        for item in payload.target_candidate_snapshots
    ]
    if payload.target_case_ids:
        rows = db.execute(
            select(TestCase, TestCaseRevision)
            .join(TestCaseRevision, TestCaseRevision.id == TestCase.current_revision_id)
            .where(
                TestCase.id.in_(payload.target_case_ids),
                TestCase.space_id == conversation.space_id,
                TestCase.deleted_at.is_(None),
            )
        ).all()
        indexed = {item.id: (item, revision) for item, revision in rows}
        if set(indexed) != set(payload.target_case_ids):
            raise HTTPException(status_code=404, detail="test_case_not_found")
        for case_id in payload.target_case_ids:
            test_case, revision = indexed[case_id]
            case_context.append(
                {
                    "ref": str(test_case.id),
                    "target_type": "formal",
                    "snapshot": case_to_view(
                        db,
                        test_case,
                        prepared=(
                            revision,
                            [conversation.collection_id],
                            [],
                            None,
                        ),
                    ).model_dump(mode="json"),
                }
            )

    if operation_id:
        operation = db.get(ConversationOperation, operation_id)
        if operation is not None:
            operation.result = {
                **dict(operation.result),
                "scope_versions": {
                    item["ref"]: item["snapshot"].get("current_revision_id")
                    for item in case_context
                    if item["target_type"] == "formal"
                },
                "scope_modules": sorted(
                    {str(item["snapshot"].get("module") or "") for item in case_context}
                ),
                "scope_count": len(case_context),
                **(
                    {"query_cases": [item["snapshot"] for item in case_context]}
                    if intent == "CASE_QUERY"
                    else {}
                ),
            }

    if (
        intent == "KNOWLEDGE_QA"
        and CURRENT_CASE_REFERENCE.search(payload.content)
        and not case_context
    ):
        assistant = _new_assistant_message(
            conversation.id,
            content="请先在当前集合中选中一条用例，再询问它的问题；我会依据该用例的步骤和预期结果回答。",
            intent=intent,
            confidence=confidence,
            status="awaiting_clarification",
            target_case_ids=[],
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None

    if intent == "CASE_QUERY":
        items = [item["snapshot"] for item in case_context]
        summary = (
            "当前范围没有匹配用例。"
            if not items
            else f"匹配 {len(items)} 条用例：\n"
            + "\n".join(
                f"- {item.get('case_key', item.get('title', '候选'))}｜"
                f"{item.get('title', '')}｜{item.get('module') or '未分类'}"
                for item in items
            )
        )
        if _is_inventory_query(intent, payload.content):
            summary = _inventory_summary(case_context)
            if re.search(r"本次.*(?:新增|改写|删除).*结果", payload.content):
                incorporated = list(db.scalars(select(WorkspaceCandidate).where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.status == "incorporated",
                )))
                changes = list(db.scalars(select(CaseChangeSet).where(
                    CaseChangeSet.conversation_id == conversation.id,
                )))
                modified, deleted = set(), set()
                for change in changes:
                    for item in change.items:
                        if item.get("status") != "applied":
                            continue
                        if item.get("operation", "modify") == "modify":
                            modified.add(item["ref"])
                        elif item.get("operation") == "delete":
                            deleted.add(item["ref"])
                summary += (f"\n本次会话累计纳入 {len(incorporated)} 条；已采纳改写涉及 {len(modified)} 条用例（多轮去重）；"
                            f"已确认删除 {len(deleted)} 条。改写数量包含候选阶段的修改。")
        assistant = _new_assistant_message(
            conversation.id,
            content=summary,
            intent=intent,
            confidence=confidence,
            status="completed",
            target_case_ids=[item["ref"] for item in case_context],
            metadata={"result_count": len(items), "retrieval_performed": False},
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "case_query", "count": len(items)}, None

    if intent == "CASE_DELETE":
        if not case_context:
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
                "target_type": item["target_type"],
                **({"test_case_id": item["ref"],
                    "base_revision_id": item["snapshot"]["current_revision_id"]}
                   if item["target_type"] == "formal" else
                   {"base_version": next(target.version for target in payload.target_candidate_snapshots
                                         if target.ref == item["ref"])}),
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
                f"将软删除 {sum(item['target_type'] == 'formal' for item in items)} 条正式用例，"
                f"丢弃 {sum(item['target_type'] == 'candidate' for item in items)} 条候选。请审阅清单并确认；取消不会改变任何资产。"
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

    if intent in ANALYSIS_INTENTS and not case_context:
        assistant = _new_assistant_message(
            conversation.id,
            content="当前范围没有可检查的用例，请选择模块或用例。",
            intent=intent,
            confidence=confidence,
            status="awaiting_clarification",
            target_case_ids=[],
        )
        db.add(assistant)
        db.flush()
        return assistant, {"type": "clarification"}, None
    if intent == "CASE_MODIFY" and operation is not None:
        if operation.payload.get("asset_reference_sources"):
            for source in operation.payload["asset_reference_sources"]:
                _validate_reuse_source(db, conversation, account, source)
            scope = sorted(item["ref"] for item in case_context)
            confirmed_scope = operation.payload.get("asset_reference_target_scope")
            if confirmed_scope is not None and scope != confirmed_scope:
                raise HTTPException(409, "asset_target_scope_changed")
            operation.payload = {**dict(operation.payload), "asset_reference_target_scope": scope or None}
        operation.requires_confirmation = True
        # Confirmation is bound to exact resolved assets and their current contents.
        # A supplement or a changed asset always needs a fresh preview.
        confirmation = {
            "instruction": payload.content,
            "cases": case_context,
        }
        pending = dict(operation.payload).get("modification_confirmation")
        if not confirm_modification or pending != confirmation:
            operation.payload = {
                **dict(operation.payload), "modification_confirmation": confirmation,
            }
            if not case_context:
                content = "请指定要修改的模块、用例编号或选中用例。"
            else:
                labels = [
                    str(item["snapshot"].get("case_key") or item["ref"])
                    + "：" + str(item["snapshot"].get("title") or "")
                    for item in case_context[:10]
                ]
                content = (
                    f"请确认本轮修改：共 {len(case_context)} 条用例。\n"
                    + "\n".join(f"- {label}" for label in labels)
                    + ("\n其余用例包含在本次已解析范围内。" if len(case_context) > 10 else "")
                    + "\n\n修改要求：\n" + payload.content
                    + "\n\n确认后生成修改建议，审阅采纳后才会保存。"
                    + "也可以补充范围、修改要求或保留约束。"
                )
            assistant = _new_assistant_message(
                conversation.id, content=content, intent=intent, confidence=confidence,
                status="awaiting_clarification", target_case_ids=target_ids,
                metadata={"modification_confirmation": bool(case_context)},
            )
            db.add(assistant)
            db.flush()
            return assistant, {"type": "clarification"}, None
        operation.payload = {
            **dict(operation.payload), "modification_confirmation": None,
            "last_confirmed_modification": confirmation,
        }
    asset_references = dict(operation.payload).get("asset_reference_sources", []) if operation else []
    if intent == "CASE_MODIFY":
        for source in asset_references:
            _validate_reuse_source(db, conversation, account, source)
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
        "asset_reference_sources": asset_references if intent == "CASE_MODIFY" else [],
        "analysis_kind": intent if intent in ANALYSIS_INTENTS else None,
        "conversation_memory": conversation_memory,
        "conversation_operation_id": str(operation_id) if operation_id else None,
        "task_revision": dict(operation.payload).get("task_revision", 1) if operation else 1,
    }
    previous_items = {}
    if intent == "CASE_MODIFY" and payload.source_operation_id:
        source = _rewrite_proposal_source(
            db, db.get(ConversationOperation, payload.source_operation_id)
        )
        previous = db.get(CaseChangeSet, source.related_change_set_id) if (
            source and source.related_change_set_id
        ) else None
        if previous and previous.status == "ready":
            previous_items = {item["ref"]: item for item in previous.items}
            if operation is not None:
                operation.target = {**dict(operation.target),
                    "case_ids": list(dict.fromkeys([*dict(operation.target).get("case_ids", []),
                        *[item["ref"] for item in previous.items if item["target_type"] == "formal"]])),
                    "candidate_refs": list(dict.fromkeys([*dict(operation.target).get("candidate_refs", []),
                        *[item["ref"] for item in previous.items if item["target_type"] == "candidate"]]))}
            for current in case_context:
                earlier = previous_items.get(current["ref"])
                if earlier is None or earlier.get("status") in {"applied", "rejected"}:
                    continue
                if current["target_type"] == "formal" and (
                    current["snapshot"].get("current_revision_id")
                    != earlier.get("base_revision_id")
                ):
                    raise HTTPException(status_code=409, detail="revision_conflict")
                if current["target_type"] == "candidate":
                    actual = next(item for item in payload.target_candidate_snapshots
                                  if item.ref == current["ref"])
                    if actual.version != earlier.get("base_version"):
                        raise HTTPException(status_code=409, detail="candidate_changed")
            input_payload["previous_change_set_id"] = str(previous.id)
            input_payload["previous_proposals"] = previous_items
    if intent == "CASE_GENERATE":
        input_payload["generation_strategy"] = payload.generation_strategy
        input_payload["predecessor_job_id"] = dict(conversation.context).get("pending_predecessor_job_id")
        if asset_rewrite:
            input_payload["asset_followup_intent"] = "CASE_MODIFY"
            input_payload["asset_target_request"] = payload.model_dump(mode="json")
            input_payload["case_context"] = []
        if payload.generation_strategy in {"generate", "select_and_generate"}:
            input_payload["case_context"] = []
        if payload.source_collection_ids and payload.generation_strategy != "generate":
            source_ids = set(payload.source_collection_ids)
            for source_id in source_ids:
                source_collection = ensure_collection(db, account, source_id)
                if source_collection.space_id != conversation.space_id:
                    raise HTTPException(422, "collection_space_mismatch")
            rows = db.execute(select(TestCase, TestCaseRevision)
                .join(TestCaseRevision, TestCaseRevision.id == TestCase.current_revision_id)
                .join(CollectionCaseMembership, CollectionCaseMembership.test_case_id == TestCase.id)
                .where(CollectionCaseMembership.collection_id.in_(source_ids),
                       TestCase.space_id == conversation.space_id, TestCase.deleted_at.is_(None))
                .distinct().limit(501)).all()
            if len(rows) > 500:
                raise HTTPException(422, "source_cases_limit_exceeded")
            input_payload["case_context"] = [{"ref": str(case.id), "target_type": "formal",
                "snapshot": {"id": case.case_key, "case_key": case.case_key,
                    "current_revision_id": str(revision.id),
                    **{key: getattr(revision, key) for key in (
                        "title", "module", "priority", "case_type", "tags", "preconditions", "steps", "source_refs")}}}
                for case, revision in rows]
            input_payload["source_collection_ids"] = [str(value) for value in source_ids]
        explicit_new_module = requested_new_module(
            payload.content
        ) or requested_new_module(instruction)
        input_payload["target_module_path"] = explicit_new_module or common_module_path(
            [str(item["snapshot"].get("module") or "") for item in case_context]
        )
        input_payload["target_module_exact"] = bool(explicit_new_module)

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
    if intent == "CASE_GENERATE" and latest_brief is not None and operation is not None:
        # Merge only revisions of this task. A completed generation is context,
        # not an instruction to regenerate its already accepted test points.
        brief_source = db.get(ConversationOperation, latest_brief.source_operation_id) if latest_brief.source_operation_id else None
        if not _brief_belongs_to_generation_task(latest_brief, brief_source, operation):
            latest_brief = None
    if latest_brief is not None:
        current_test_brief = dict(latest_brief.content)
        if provided_test_object and not str(current_test_brief.get("test_object") or "").strip():
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
            "CASE_REVIEW": "knowledge_qa",
            "CASE_DEDUP": "knowledge_qa",
            "COVERAGE_ANALYZE": "knowledge_qa",
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
        previous_generations = db.scalars(
            select(ConversationOperation).where(
                ConversationOperation.conversation_id == conversation.id,
                ConversationOperation.intent == "CASE_GENERATE",
                ConversationOperation.status == "awaiting_confirmation",
                ConversationOperation.id != operation_id,
            )
        ).all()
        for previous in previous_generations:
            previous.status = "cancelled"
            previous.completed_at = datetime.now(UTC)
            previous.result = {
                **dict(previous.result),
                "discarded": True,
                "superseded_by": str(operation_id) if operation_id else None,
            }
            db.execute(update(ConversationOperation).where(
                ConversationOperation.message_id == previous.message_id,
                ConversationOperation.sequence > previous.sequence,
                ConversationOperation.status == "queued",
            ).values(status="cancelled", completed_at=datetime.now(UTC)))
        if payload.generation_strategy == "generate":
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
    elif intent in {"KNOWLEDGE_QA", "SMALL_TALK"} | ANALYSIS_INTENTS:
        assistant = _new_assistant_message(
            conversation.id,
            content=(
                f"本次检查 {len(case_context)} 条用例。\n"
                "执行步骤：读取用例与需求依据 → 检查问题并记录用例引用 → 汇总建议。\n"
                "检查过程不会修改用例。"
                if intent in ANALYSIS_INTENTS else ""
            ),
            intent=intent,
            confidence=confidence,
            status="running",
            target_case_ids=target_ids,
            metadata={
                "hidden_progress": intent not in ANALYSIS_INTENTS,
                "analysis_kind": intent,
                "target_count": len(case_context),
            },
        )
        task_name = "casepilot.agent.answer_question"
        action = {
            "type": "small_talk" if intent == "SMALL_TALK" else "knowledge_qa",
            "job_id": str(job.id),
        }
    else:
        formal_targets = [
            {"case_id": item["ref"], "base_revision_id": item["snapshot"]["current_revision_id"]}
            for item in case_context
            if item["target_type"] == "formal"
        ]
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
                    item.model_dump(mode="json") for item in payload.target_candidate_snapshots
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
            metadata={"change_set_id": str(change_set.id),
                "task_revision": input_payload.get("task_revision", 1),
                "task_case_count": len(set(previous_items) | {item["ref"] for item in case_context})},
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
        "phase": "brief_drafting"
        if intent == "CASE_GENERATE"
        else dict(conversation.context).get("phase", "maintenance"),
    }
    if intent in {"CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE"}:
        context_update["active_operation_id"] = str(operation_id) if operation_id else None
    if intent == "CASE_GENERATE":
        context_update["generation_target_module_path"] = input_payload["target_module_path"]
        context_update["generation_target_module_exact"] = input_payload["target_module_exact"]
        context_update.pop("pending_predecessor_job_id", None)
        context_update["generation_strategy"] = payload.generation_strategy
        context_update["generation_source_collection_ids"] = [str(value) for value in payload.source_collection_ids]
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
            "active_view": "plan",
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
    db.refresh(collection, with_for_update=True)
    existing = db.scalar(
        select(Conversation)
        .where(
            Conversation.collection_id == collection.id,
            Conversation.account_id == account.id,
            Conversation.status == "active",
        )
        .order_by(Conversation.updated_at.desc())
    )
    if existing is None:
        created = create_conversation(
            ConversationCreate(
                space_id=collection.space_id,
                collection_id=collection_id,
                title="集合工作区",
            ),
            account,
            db,
        )
        existing = _ensure_conversation(db, account.id, created.id)

    # Message handlers lock the conversation before touching its collection.
    # Release the creation lock before recovery acquires a conversation lock.
    db.commit()
    recover_terminal_workspace_job(db, existing)
    db.refresh(existing, with_for_update=True)
    normalized_context = collection_workspace_context(dict(existing.context))
    if normalized_context != dict(existing.context):
        existing.context = normalized_context
        existing.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(existing)
    return _conversation_view(db, existing)


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
        ".png": {"image/png"},
        ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"},
        ".pdf": {"application/pdf"},
        ".txt": {"text/plain"},
        ".xlsx": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
            "",
        },
        ".xls": {"application/vnd.ms-excel", "application/excel", "application/octet-stream", ""},
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
    # Storage commits independently; its pre-upload ORM snapshot is now stale.
    # Merge attachment references under the same lock used by message sends.
    db.refresh(conversation, with_for_update=True)
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
            Conversation.account_id == account.id,
            Conversation.status == "active",
        )
        .order_by(Conversation.updated_at.desc())
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    recover_terminal_workspace_job(db, conversation)
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
    conversation = _ensure_conversation(db, account.id, conversation_id)
    recover_terminal_workspace_job(db, conversation)
    return _conversation_view(
        db,
        conversation,
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
    # UI autosaves may have loaded an older snapshot while a model request held
    # the conversation lock. Merge in SQL so they cannot rewind task pointers.
    db.execute(update(Conversation).where(Conversation.id == conversation.id).values(
        context=Conversation.context.op("||")(updates),
        updated_at=datetime.now(UTC),
    ).execution_options(synchronize_session=False))
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
    db.scalar(select(Conversation).where(Conversation.id == conversation.id).with_for_update())
    active_job_id = dict(conversation.context).get("active_job_id")
    if active_job_id:
        active_job = db.get(GenerationJob, UUID(str(active_job_id)))
        active_status = (
            str(getattr(active_job.status, "value", active_job.status)) if active_job else ""
        )
        if active_status in {"queued", "running", "awaiting_input"}:
            raise HTTPException(status_code=409, detail="workspace_generation_in_progress")
    latest_version = db.scalar(
        select(func.max(WorkspaceTestBrief.version)).where(
            WorkspaceTestBrief.conversation_id == conversation.id
        )
    ) or 0
    if payload.base_version is not None and payload.base_version != latest_version:
        raise HTTPException(status_code=409, detail="test_brief_version_changed")
    db.execute(
        update(WorkspaceTestBrief)
        .where(
            WorkspaceTestBrief.conversation_id == conversation.id,
            WorkspaceTestBrief.status.in_(("draft", "confirmed")),
        )
        .values(status="superseded")
    )
    reviewer_choices(payload.content.planning)
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
    previous = db.scalar(select(WorkspaceTestBrief).where(
        WorkspaceTestBrief.conversation_id == conversation.id, WorkspaceTestBrief.version == latest_version))
    db.add(brief)
    db.flush()
    inherit_unchanged_links(db, previous, brief)
    conversation.context = {
        **dict(conversation.context),
        "phase": "brief_review",
        "confirmed_brief_version": None,
        "selected_brief_version": brief.version,
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


def validate_reuse_confirmation(content, planning):
    reuse = planning.get("reuse") or {}
    if reuse.get("strategy") not in {"regression", "change"}:
        return
    choices = reviewer_choices(planning)
    inherited_points = [p for p in planning.get("test_points", [])
                        if choices.get(p["id"]) != "new"]
    if not inherited_points:
        return
    snapshots = reuse.get("brief_snapshot", {})
    features = {f["id"]: f for f in reuse.get("feature_snapshots", [])}
    decisions = {d["point_id"]: d for d in reuse.get("decisions", [])}
    if (any(content.get(k) != v for k, v in snapshots.items())
            or any(features.get(f["id"]) != f for f in planning.get("feature_points", []))
            or any(decisions.get(p["id"], {}).get("point_snapshot") != p
                   for p in inherited_points)):
        raise HTTPException(status_code=409, detail="reuse_plan_changed_reanalyze_required")


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
    _require_idle_conversation(db, conversation)
    db.scalar(select(Conversation).where(Conversation.id == conversation.id).with_for_update())
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
    if brief_content.get("asset_selection", {}).get("status") == "awaiting_confirmation":
        raise HTTPException(409, "generation_asset_confirmation_required")
    planning = dict(brief_content.get("planning") or {})
    if planning:
        points = planning.get("test_points", [])
        choices = reviewer_choices(planning)
        selected = set(payload.selected_test_point_ids)
        allowed = {str(point["id"]) for point in points}
        if selected - allowed:
            raise HTTPException(status_code=422, detail="planning_selection_invalid")
        points = [point for point in points if (not selected or point["id"] in selected)
                  and choices.get(point["id"]) != "exclude"]
        if not points:
            raise HTTPException(status_code=409, detail="planning_has_no_test_points")
        feature_ids = {ref for point in points for ref in point["feature_point_ids"]}
        planning = {
            **planning,
            "test_points": points,
            "feature_points": [
                feature for feature in planning.get("feature_points", [])
                if feature["id"] in feature_ids
            ],
            "coverage_matrix": [],
            "brief_version": brief.version,
            **({"reuse": {**planning["reuse"], "user_choices": {
                key: value for key, value in choices.items() if key in {p["id"] for p in points}
            }, "decisions": [
                item for item in planning["reuse"].get("decisions", [])
                if item["point_id"] in {point["id"] for point in points}
            ]}} if planning.get("reuse") else {}),
        }
    elif payload.selected_test_point_ids:
        raise HTTPException(status_code=422, detail="planning_selection_invalid")
    planning = apply_reviewer_choices(planning)
    planning = confirm_asset_reuse(planning, payload.reuse_confirmation,
        confirmed_keys=(dict(conversation.context).get("confirmed_asset_keys", [])
            if brief_content.get("test_object") == dict(conversation.context).get("confirmed_asset_test_object") else []))
    validate_reuse_confirmation(brief_content, planning)
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
    # Preserve explicit quantities and scope that a brief summary may omit.
    if active_operation:
        original_request = db.get(ConversationMessage, active_operation.message_id)
        if original_request:
            prompt = original_request.content[:8000]
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
            "confirmed_plan": planning,
            "output_contract": "case_batch_v2",
            "confirmed_test_brief": brief_content,
            "confirmed_test_brief_version": brief.version,
            "target_module_path": str(
                dict(conversation.context).get("generation_target_module_path") or ""
            ),
            "target_module_exact": bool(
                dict(conversation.context).get("generation_target_module_exact", False)
            ),
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
    enqueue_task(db, "casepilot.agent.generate", [str(job.id)], task_id=job.id)
    db.commit()
    db.refresh(assistant)
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


def _candidate_source_refs(snapshot: dict) -> Any:
    """Bound excerpt previews without changing the stored candidate evidence."""
    refs = snapshot.get("source_refs", [])
    if not isinstance(refs, list):
        return refs  # Let the case schema reject malformed references.
    return [
        {**ref, "excerpt": ref["excerpt"][:SOURCE_REF_EXCERPT_MAX_LENGTH]}
        if isinstance(ref, dict) and isinstance(ref.get("excerpt"), str)
        else ref
        for ref in refs
    ]


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
    candidate = db.scalar(
        select(WorkspaceCandidate)
        .where(WorkspaceCandidate.id == candidate_id)
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="workspace_candidate_not_found")
    _ensure_conversation(db, account.id, candidate.conversation_id)
    if candidate.status != "candidate":
        raise HTTPException(status_code=409, detail="workspace_candidate_not_editable")
    if candidate.version != payload.base_version:
        raise HTTPException(status_code=409, detail="candidate_changed")
    if payload.snapshot is not None:
        snapshot = dict(payload.snapshot)
        try:
            validated = TestCaseCreate.model_validate(
                {
                    "title": snapshot.get("title", ""),
                    "module": snapshot.get("module", ""),
                    "priority": snapshot.get("priority", "P1"),
                    "case_type": snapshot.get("case_type", "功能"),
                    "tags": snapshot.get("tags", []),
                    "preconditions": snapshot.get("preconditions", []),
                    "steps": snapshot.get("steps", []),
                    "source": snapshot.get("source", "CasePilot 工作区候选"),
                    "source_refs": _candidate_source_refs(snapshot),
                }
            )
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="invalid_workspace_candidate",
            ) from error
        normalized = validated.model_dump(mode="json")
        candidate.snapshot = {
            **snapshot,
            "title": normalized["title"],
            "module": normalized["module"],
            "priority": normalized["priority"],
            "case_type": normalized["case_type"],
            "tags": normalized["tags"],
            "preconditions": normalized["preconditions"],
            "steps": normalized["steps"],
            "source_refs": normalized["source_refs"],
        }
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
    _require_idle_conversation(db, conversation)
    if conversation.collection_id is None:
        raise HTTPException(status_code=409, detail="conversation_collection_required")
    query = select(WorkspaceCandidate).where(
        WorkspaceCandidate.conversation_id == conversation.id,
        WorkspaceCandidate.status == "candidate",
        WorkspaceCandidate.included.is_(True),
    )
    if payload.candidate_ids:
        query = query.where(WorkspaceCandidate.id.in_(payload.candidate_ids))
    candidates = list(
        db.scalars(
            query.order_by(WorkspaceCandidate.position, WorkspaceCandidate.id)
            .with_for_update()
        )
    )
    if not candidates:
        raise HTTPException(status_code=409, detail="no_included_workspace_candidates")
    selected_refs = {candidate.ref for candidate in candidates}
    pending_changes = db.scalars(select(CaseChangeSet).where(
        CaseChangeSet.conversation_id == conversation.id,
        CaseChangeSet.status == "ready",
    ))
    if any(item.get("target_type") == "candidate"
           and item.get("ref") in selected_refs
           and item.get("status") not in {"applied", "rejected"}
           for change in pending_changes for item in change.items):
        raise HTTPException(status_code=409, detail="candidate_changes_need_review")
    position = db.scalar(
        select(func.max(CollectionCaseMembership.position)).where(
            CollectionCaseMembership.collection_id == conversation.collection_id
        )
    )
    position = (position if position is not None else -1) + 1
    collection = ensure_collection(db, account, conversation.collection_id)
    # Validate the entire selection before creating records or changing statuses.
    validated_candidates: list[TestCaseCreate] = []
    for candidate in candidates:
        snapshot = dict(candidate.snapshot)
        try:
            validated = TestCaseCreate.model_validate(
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
                    "source_refs": _candidate_source_refs(snapshot),
                }
            )
        except ValidationError as error:
            raise HTTPException(
                status_code=422, detail="invalid_workspace_candidate",
            ) from error
        validated_candidates.append(validated)
    created: list[TestCase] = []
    link_context: dict = {}
    reuse_context: dict = {}
    linked_count = 0
    for index, (candidate, validated) in enumerate(zip(candidates, validated_candidates, strict=True)):
        test_case = reusable_current_case(db, conversation, candidate, reuse_context)
        if test_case is not None:
            linked_count += 1
        else:
            test_case = create_test_case_record(
                db, collection=collection, payload=validated, account=account,
                case_key=f"CP-{uuid4().hex[:8].upper()}", position=position + index,
            )
        link_committed_candidate(db, conversation, candidate, test_case, link_context)
        candidate.status = "incorporated"
        created.append(test_case)
    db.flush()
    remaining = list(db.scalars(select(WorkspaceCandidate).where(
        WorkspaceCandidate.conversation_id == conversation.id,
        WorkspaceCandidate.status == "candidate",
    )))
    generation_job_ids = {item.generation_job_id for item in candidates}
    source_generation = db.scalar(select(ConversationOperation).where(
        ConversationOperation.conversation_id == conversation.id,
        ConversationOperation.intent == "CASE_GENERATE",
        ConversationOperation.related_job_id.in_(generation_job_ids),
    ).order_by(ConversationOperation.created_at.desc()))
    active_operation_id = str(source_generation.id) if source_generation else None
    conversation.context = {
        **dict(conversation.context),
        "phase": "candidate_review" if remaining else "maintenance",
        "active_job_id": None,
        "active_operation_id": None,
    }
    if active_operation_id:
        operation = db.get(ConversationOperation, UUID(str(active_operation_id)))
        if operation is not None:
            operation.status = "awaiting_confirmation" if remaining else "completed"
            operation.result = {
                **dict(operation.result),
                "candidate_ids": [str(item.id) for item in candidates],
                "test_case_ids": [*dict(operation.result).get("test_case_ids", []), *[str(item.id) for item in created]],
            }
            operation.completed_at = None if remaining else datetime.now(UTC)
            if not remaining:
                active = _open_mutation_operation(db, conversation)
                _finish_mutation_task(db, active or operation)
    conversation.updated_at = datetime.now(UTC)
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=f"已采纳 {len(created)} 条候选用例（关联已有 {linked_count} 条，新建 {len(created) - linked_count} 条），剩余 {len(remaining)} 条待审阅。" + ("当前任务继续，您可以继续修改或放弃剩余建议。" if remaining else "当前任务已结束，可以发起新任务。"),
            intent="CASE_GENERATE",
            intent_confidence=1.0,
            status="completed",
            target_case_ids=[str(item.id) for item in created],
            citations=[],
            message_metadata={
                "action": "candidates_committed",
                "operation_id": str(active_operation_id) if active_operation_id else None,
            },
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
    if (
        not case_ids
        and not candidate_snapshots
        and not payload.targets
        and CURRENT_CASE_REFERENCE.search(payload.content)
    ):
        selected_id = dict(conversation.context).get("selected_case_id")
        try:
            selected_uuid = UUID(str(selected_id)) if selected_id else None
        except ValueError:
            selected_uuid = None
        if selected_uuid is not None:
            candidate = db.scalar(
                select(WorkspaceCandidate).where(
                    WorkspaceCandidate.id == selected_uuid,
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.status == "candidate",
                )
            )
            if candidate is not None:
                candidate_snapshots.append(
                    ConversationTargetSnapshot(
                        ref=candidate.ref,
                        version=candidate.version,
                        snapshot=dict(candidate.snapshot),
                    )
                )
                candidate_refs.add(candidate.ref)
            elif conversation.collection_id is not None:
                member_id = db.scalar(
                    select(CollectionCaseMembership.test_case_id).where(
                        CollectionCaseMembership.collection_id == conversation.collection_id,
                        CollectionCaseMembership.test_case_id == selected_uuid,
                    )
                )
                if member_id is not None:
                    case_ids.append(selected_uuid)
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
            # Once candidates are incorporated, dependent operations must target
            # the current formal revisions, not detached candidate snapshots.
            if dict(conversation.context).get("phase") == "candidate_review" and dict(source.payload).get("task_intent", source.intent) == "CASE_GENERATE":
                pending = list(db.scalars(select(WorkspaceCandidate).where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.status == "candidate",
                )))
                if pending:
                    for candidate in pending:
                        if candidate.ref not in candidate_refs:
                            candidate_snapshots.append(ConversationTargetSnapshot(ref=candidate.ref, version=candidate.version, snapshot=dict(candidate.snapshot)))
                            candidate_refs.add(candidate.ref)
                    continue
            committed_ids = dict(source.result).get("test_case_ids", [])
            if committed_ids:
                case_ids.extend(UUID(str(item)) for item in committed_ids)
                continue
            if source.intent in ANALYSIS_INTENTS | {"CASE_QUERY", "CASE_MODIFY"}:
                case_ids.extend(UUID(str(item)) for item in dict(source.target).get("case_ids", []))
            if source.intent in ANALYSIS_INTENTS | {"CASE_QUERY", "CASE_MODIFY"}:
                for ref in dict(source.target).get("candidate_refs", []):
                    candidate = db.scalar(select(WorkspaceCandidate).where(
                        WorkspaceCandidate.conversation_id == conversation.id,
                        WorkspaceCandidate.ref == ref,
                        WorkspaceCandidate.status == "candidate",
                    ))
                    if candidate is not None and candidate.ref not in candidate_refs:
                        candidate_snapshots.append(ConversationTargetSnapshot(
                            ref=candidate.ref, version=candidate.version,
                            snapshot=dict(candidate.snapshot),
                        ))
                        candidate_refs.add(candidate.ref)
            result_ids = [
                UUID(str(item)) for item in dict(source.result).get("candidate_ids", [])
            ]
            for candidate in db.scalars(
                select(WorkspaceCandidate).where(
                    WorkspaceCandidate.id.in_(result_ids),
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.status == "candidate",
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
        if str(dict(conversation.context).get("phase")) == "candidate_review":
            for candidate in db.scalars(
                select(WorkspaceCandidate).where(
                    WorkspaceCandidate.conversation_id == conversation.id,
                    WorkspaceCandidate.status == "candidate",
                )
            ):
                snapshot = dict(candidate.snapshot)
                matches_module = target.kind == "module" and module_contains(
                    target.module, str(snapshot.get("module", ""))
                )
                matches_condition = (
                    target.kind == "condition"
                    and target.condition in snapshot.get("preconditions", [])
                    and (
                        not target.module
                        or module_contains(target.module, str(snapshot.get("module", "")))
                    )
                )
                if (matches_module or matches_condition) and candidate.ref not in candidate_refs:
                    candidate_snapshots.append(
                        ConversationTargetSnapshot(
                            ref=candidate.ref,
                            version=candidate.version,
                            snapshot=snapshot,
                        )
                    )
                    candidate_refs.add(candidate.ref)
            continue
        if conversation.collection_id is None:
            raise HTTPException(
                status_code=409,
                detail="conversation_collection_required",
            )
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
            if target.kind == "module" and module_contains(target.module, view.module):
                case_ids.append(test_case.id)
            if (
                target.kind == "condition"
                and target.condition in view.preconditions
                and (not target.module or module_contains(target.module, view.module))
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


def _resolve_turn_attachments(db, conversation, payload, *, resuming=False):
    """Only ready historical files are inherited; explicit unavailable files fail early."""
    stored_context = dict(conversation.context)
    if resuming:
        # Removal also applies to a paused task's saved request, without editing history.
        payload = payload.model_copy(update={
            "document_ids": [v for v in payload.document_ids if str(v) not in stored_context.get("excluded_document_ids", [])],
            "knowledge_source_ids": [v for v in payload.knowledge_source_ids if str(v) not in stored_context.get("excluded_source_ids", [])],
        })
    context = stored_context if payload.inherit_attachments else {}
    explicit_docs, explicit_sources = set(payload.document_ids), set(payload.knowledge_source_ids)
    doc_ids = explicit_docs | {UUID(str(v)) for v in context.get("document_ids", [])}
    source_ids = explicit_sources | {UUID(str(v)) for v in context.get("knowledge_source_ids", [])}
    documents = (
        list(
            db.scalars(
                select(KnowledgeDocument)
                .join(KnowledgeSource)
                .where(
                    KnowledgeDocument.space_id == conversation.space_id,
                    KnowledgeDocument.id.in_(doc_ids),
                    KnowledgeSource.deleted_at.is_(None),
                    KnowledgeDocument.status == "ready",
                    or_(
                        KnowledgeDocument.expires_at.is_(None),
                        KnowledgeDocument.expires_at > datetime.now(UTC),
                    ),
                )
            )
        )
        if doc_ids
        else []
    )
    image_documents = [
        doc for doc in documents if getattr(doc, "mime_type", "").startswith("image/")
    ]
    if image_documents:
        image_models = {v.strip() for v in settings.image_models.split(",") if v.strip()}
        if (settings.ai_mode == "mock" or settings.agent_provider == "mock"
                or settings.resolve_agent_model(payload.model_id) not in image_models):
            raise HTTPException(status_code=422, detail="当前模型不支持图片，请切换支持图片的模型或移除图片附件后发送。")
        if sum(int(getattr(doc, "size_bytes", 0)) for doc in image_documents) > settings.image_max_total_bytes:
            raise HTTPException(status_code=422, detail="图片附件总大小超过单次发送限制，请移除部分图片后重试。")
    ready_docs = {doc.id for doc in documents}
    sources = (
        list(
            db.scalars(
                select(KnowledgeSource).where(
                    KnowledgeSource.space_id == conversation.space_id,
                    KnowledgeSource.id.in_(source_ids),
                    KnowledgeSource.deleted_at.is_(None),
                    KnowledgeSource.status == "ready",
                )
            )
        )
        if source_ids
        else []
    )
    ready_sources = {source.id for source in sources}
    if explicit_docs - ready_docs or explicit_sources - ready_sources:
        raise HTTPException(status_code=422, detail="attachment_not_ready_or_expired")
    # Sources associated only with stale historical documents must not sneak back
    # into retrieval after their document was filtered out.
    inherited_doc_sources = (
        set(
            db.scalars(
                select(KnowledgeDocument.source_id).where(
                    KnowledgeDocument.id.in_(doc_ids - explicit_docs),
                    KnowledgeDocument.space_id == conversation.space_id,
                )
            )
        )
        if doc_ids - explicit_docs
        else set()
    )
    ready_sources -= inherited_doc_sources - {doc.source_id for doc in documents} - explicit_sources
    return payload.model_copy(
        update={
            "document_ids": sorted(ready_docs, key=str),
            "knowledge_source_ids": sorted(ready_sources, key=str),
        }
    )


@router.delete(
    "/conversations/{conversation_id}/attachments/{document_id}", response_model=ConversationView
)
def detach_conversation_attachment(
    conversation_id: UUID, document_id: UUID, account: CurrentAccount, db: DbSession
):
    conversation = _ensure_conversation(db, account.id, conversation_id)
    _require_idle_conversation(db, conversation)
    context = dict(conversation.context)
    if str(document_id) not in {str(v) for v in context.get("document_ids", [])}:
        return _conversation_view(db, conversation)
    remaining = [v for v in context.get("document_ids", []) if str(v) != str(document_id)]
    removed = db.get(KnowledgeDocument, document_id)
    sources = list(context.get("knowledge_source_ids", []))
    excluded_sources = list(context.get("excluded_source_ids", []))
    if removed and removed.space_id == conversation.space_id:
        # Keep other files selected by document ID; retaining the whole upload
        # source would retrieve the removed file again through its sibling.
        sources = [v for v in sources if str(v) != str(removed.source_id)]
        excluded_sources.append(str(removed.source_id))
    conversation.context = {**context, "document_ids": remaining, "knowledge_source_ids": sources,
                            "excluded_document_ids": list(dict.fromkeys([*context.get("excluded_document_ids", []), str(document_id)])),
                            "excluded_source_ids": list(dict.fromkeys(excluded_sources))}
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    return _conversation_view(db, conversation)


def _is_generation_retry(content: str) -> bool:
    # Full commands only: requests to design retry test cases are ordinary input.
    return bool(re.fullmatch(
        r"(?:请|帮我)?(?:确认)?(?:重试|重新执行|再试一次)"
        r"(?:(?:一下|一次)|(?:(?:刚才|上次|本次|这个|当前|失败的|未完成的|中断的|的)*)"
        r"(?:(?:生成|修改|删除|查询|评审)(?:任务|请求)?|任务|请求))?[。！!？?\s]*"
        r"|(?:please\s+)?(?:retry|try again)(?:\s+(?:the\s+)?(?:failed\s+)?"
        r"(?:generation|request|task))?[.!?\s]*",
        content.strip(), re.I,
    ))


def _retry_generation_from_text(
    db: Session, account: CurrentAccount, conversation: Conversation,
    payload: ConversationMessageCreate,
) -> ConversationTurnView | None:
    if payload.intent_override or payload.source_operation_id:
        return None
    explicit = _is_generation_retry(payload.content)
    if not explicit:
        if payload.content.strip().strip("。！! ").casefold() not in {
            "确认", "是", "是的", "好的", "好", "确认重试", "yes", "ok", "confirm",
        }:
            return None
        recent = list(db.scalars(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id,
        ).order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc()).limit(2)))
        # Support an outstanding retry question from older conversation turns.
        # A bare confirmation must never retry an unrelated failure.
        if (len(recent) != 2 or recent[0].role != "assistant" or recent[1].role != "user"
            or not _is_generation_retry(recent[1].content)
            or not re.search(r"(?:是否|要不要|确认|要).*重试|retry.*\?", recent[0].content, re.I)):
            return None
    latest_operation = db.scalar(select(ConversationOperation).where(
        ConversationOperation.conversation_id == conversation.id,
    ).order_by(ConversationOperation.created_at.desc(),
               ConversationOperation.sequence.desc()).limit(1))
    # A compound request may end in queued steps blocked by an earlier failure.
    # Retry that failed predecessor, never skip ahead to the queued mutation.
    if latest_operation is not None and latest_operation.status == "queued":
        failed_predecessor = db.scalar(select(ConversationOperation).where(
            ConversationOperation.message_id == latest_operation.message_id,
            ConversationOperation.conversation_id == conversation.id,
            ConversationOperation.sequence < latest_operation.sequence,
            ConversationOperation.status == "failed",
        ).order_by(ConversationOperation.sequence).limit(1))
        if failed_predecessor is not None:
            latest_operation = failed_predecessor
    requested_kind = next((intent for label, intent in {
        "生成": "CASE_GENERATE", "修改": "CASE_MODIFY", "删除": "CASE_DELETE",
        "查询": "CASE_QUERY", "评审": "CASE_REVIEW",
    }.items() if label in payload.content), None)
    if (requested_kind and latest_operation is not None
            and latest_operation.intent != requested_kind):
        raise HTTPException(status_code=409, detail="retry_context_mismatch")
    if (latest_operation is None or latest_operation.intent == "CASE_GENERATE") and (
        payload.document_ids or payload.knowledge_source_ids
    ):
        # New generation evidence needs normal planning, not replay of an old brief.
        return None
    if latest_operation is not None and latest_operation.intent != "CASE_GENERATE":
        if latest_operation.status != "failed":
            raise HTTPException(status_code=409, detail="message_not_retryable")
        retry_message = ConversationMessage(
            conversation_id=conversation.id, role="user", content=payload.content.strip(),
            intent=latest_operation.intent, intent_confidence=1.0, status="completed",
            target_case_ids=[], citations=[],
            message_metadata={"retry_operation_id": str(latest_operation.id)},
        )
        db.add(retry_message)
        turn = resume_conversation_operation(
            latest_operation.id, ConversationOperationResumeRequest(
                document_ids=payload.document_ids, knowledge_source_ids=payload.knowledge_source_ids), account, db,
        )
        db.refresh(retry_message)
        return turn.model_copy(update={"user_message": _message_view(retry_message)})
    job = db.scalar(select(GenerationJob).where(
        GenerationJob.input_payload["conversation_id"].astext == str(conversation.id),
    ).order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc()).limit(1))
    # A completed compact job can still have explicitly reported missing slots.
    # Reconfirm just those slots under the same current brief; persisted successful
    # candidates are outside that selected scope and must remain unchanged.
    if (job is not None and job.status == "completed" and job.operation == "generate"
            and job.input_payload.get("output_contract") == "case_batch_v2"):
        missing = {str(issue.get("object_id")) for issue in
                   dict(job.output_payload or {}).get("quality", {}).get("issues", [])
                   if issue.get("code") == "uncovered_test_point" and issue.get("object_id")}
        planned = {str(point["id"]) for point in
                   dict(job.input_payload.get("confirmed_plan") or {}).get("test_points", [])}
        if missing and missing <= planned:
            brief = db.scalar(select(WorkspaceTestBrief).where(
                WorkspaceTestBrief.conversation_id == conversation.id,
            ).order_by(WorkspaceTestBrief.version.desc()).limit(1))
            if (latest_operation is None or latest_operation.related_job_id != job.id
                    or brief is None or brief.source_operation_id != latest_operation.id
                    or brief.version != job.input_payload.get("confirmed_test_brief_version")):
                raise HTTPException(status_code=409, detail="retry_context_mismatch")
            retry_message = ConversationMessage(
                conversation_id=conversation.id, role="user", content=payload.content.strip(),
                intent="CASE_GENERATE", intent_confidence=1.0, status="completed",
                target_case_ids=[], citations=[],
                message_metadata={"retry_job_id": str(job.id), "missing_test_point_ids": sorted(missing)},
            )
            db.add(retry_message)
            turn = confirm_test_brief(conversation.id, TestBriefConfirmRequest(
                version=brief.version, selected_test_point_ids=sorted(missing),
                model_id=str(job.input_payload.get("model_id") or "auto"),
            ), account, db)
            db.refresh(retry_message)
            return turn.model_copy(update={"user_message": _message_view(retry_message)})
    # Do not revive an older failure after a newer generation succeeded.
    if job is None or job.status != "failed" or job.operation not in {"generate", "draft_brief"}:
        raise HTTPException(status_code=409, detail="message_not_retryable")
    assistant = db.scalar(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.related_job_id == job.id,
        ConversationMessage.role == "assistant",
    ).order_by(ConversationMessage.created_at.desc()).limit(1))
    if assistant is None:
        raise HTTPException(status_code=409, detail="retry_context_missing")
    from casepilot_api.generation import retry_generation

    retry_message = ConversationMessage(
        conversation_id=conversation.id, role="user", content=payload.content.strip(),
        intent="CASE_GENERATE", intent_confidence=1.0, status="completed",
        target_case_ids=[], citations=[], message_metadata={"retry_job_id": str(job.id)},
    )
    db.add(retry_message)
    retry_generation(job.id, account, db)
    db.refresh(assistant)
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(retry_message),
        assistant_message=_message_view(assistant),
        intent="CASE_GENERATE", intent_confidence=1.0,
        action={"type": "generation", "job_id": str(job.id)},
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
    if payload.client_request_id is None:
        return _send_message(conversation_id, payload, account, db)
    conversation = _ensure_conversation(db, account.id, conversation_id)
    fingerprint = sha256(json.dumps(payload.model_dump(mode="json", exclude={"client_request_id"}),
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    lock_key = int.from_bytes(sha256(str(conversation_id).encode()).digest()[:8],
                              "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    db.refresh(conversation)
    receipt = db.get(ConversationSubmission, (conversation_id, payload.client_request_id))
    if receipt is not None:
        if receipt.request_hash != fingerprint:
            raise HTTPException(409, "submission_request_mismatch")
        return ConversationTurnView.model_validate(receipt.response)
    transaction = SubmissionTransaction(db)
    try:
        turn = _send_message(conversation_id, payload, account, transaction)
        user_message = db.get(ConversationMessage, turn.user_message.id)
        if user_message is None:
            raise RuntimeError("submission_user_message_missing")
        user_message.message_metadata = {
            **dict(user_message.message_metadata),
            "submission_request_id": str(payload.client_request_id),
        }
        turn.user_message.metadata = dict(user_message.message_metadata)
        db.add(ConversationSubmission(
            conversation_id=conversation_id, request_id=payload.client_request_id,
            request_hash=fingerprint, response=turn.model_dump(mode="json"),
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    transaction.publish_committed_effects()
    return turn


def _send_message(conversation_id, payload, account, db) -> ConversationTurnView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    # Explicit asset redirection stops the prior job before accepting a new scope.
    if generation_strategy_from_text(payload.content) != "generate":
        active_id = dict(conversation.context).get("active_job_id")
        if active_id:
            from casepilot_api.generation import cancel_generation
            active = db.get(GenerationJob, UUID(str(active_id)))
            if active and active.status in {"queued", "running", "awaiting_input"}:
                cancel_generation(active.id, account, db)
                db.refresh(conversation)
                conversation.context = {**dict(conversation.context), "pending_predecessor_job_id": str(active.id)}
                db.flush()
    _require_idle_conversation(db, conversation)
    retry_turn = _retry_generation_from_text(db, account, conversation, payload)
    if retry_turn is not None:
        return retry_turn
    if payload.source_operation_id:
        source_operation = db.get(ConversationOperation, payload.source_operation_id)
        if source_operation is None or source_operation.conversation_id != conversation.id:
            raise HTTPException(status_code=422, detail="previous_result_not_found")
        if source_operation.status not in {"completed", "awaiting_confirmation"}:
            raise HTTPException(status_code=409, detail="source_task_not_ready")
    strategy = generation_strategy_from_text(payload.content)
    strategy_update = {"generation_strategy": strategy}
    if not payload.intent_override:
        strategy_update.update(
            {"intent_override": "CASE_GENERATE"}
            if strategy != "generate"
            else {"intent_override": "KNOWLEDGE_QA"}
            if is_strategy_question(payload.content)
            else {}
        )
    payload = payload.model_copy(update=strategy_update)
    payload = _resolve_turn_attachments(db, conversation, payload)
    if not settings.is_agent_model_allowed(payload.model_id):
        raise HTTPException(status_code=422, detail="generation_model_not_configured")
    conversation.context = {
        **dict(conversation.context),
        "model_id": payload.model_id,
    }
    phase = str(dict(conversation.context).get("phase", "idle"))
    if phase == "brief_review":
        pending_brief = db.scalar(select(WorkspaceTestBrief).where(
            WorkspaceTestBrief.conversation_id == conversation.id).order_by(WorkspaceTestBrief.version.desc()))
        pending_selection = (pending_brief.content.get("asset_selection") or {}) if pending_brief else {}
        if pending_selection.get("status") == "awaiting_confirmation" and not pending_selection.get("target_points"):
            chosen = asset_choice_from_text(payload.content, [source["case_id"] for source in pending_selection.get("sources", [])])
            if chosen is not None:
                return confirm_generation_assets(conversation_id,
                    GenerationAssetConfirmRequest(version=pending_brief.version, case_ids=chosen), account, db)
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
    elif (_open_mutation_operation(db, conversation)
          and classify_intent(payload.content, has_targets, phase)[0] == "CASE_DELETE"):
        # A review gate never executes a write. Keep explicit deletion requests
        # out of model-failure fallbacks while a mutation is awaiting review.
        operation_drafts = [{"intent": "CASE_DELETE", "instruction": payload.content,
                             "confidence": 1.0, "target_kind": "none",
                             "requires_confirmation": False}]
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
                attachment_context={"document_ids": list(map(str, payload.document_ids)),
                                    "knowledge_source_ids": list(map(str, payload.knowledge_source_ids))},
                provider=settings.agent_provider,
                model_name=settings.routing_model,
                base_url=settings.agent_base_url,
                api_key=settings.agent_api_key,
                timeout_seconds=settings.routing_timeout_seconds,
                tracing_enabled=settings.agent_tracing_enabled,
            ).operations
        ]
    # A single action must retain the user's exact identifiers and constraints.
    if len(operation_drafts) == 1:
        operation_drafts[0]["instruction"] = payload.content
    open_task = _open_mutation_operation(db, conversation)
    if open_task and str(dict(open_task.payload).get("task_intent", open_task.intent)) == "CASE_GENERATE" and phase == "brief_review":
        for draft in operation_drafts:
            if draft["intent"] == "CASE_MODIFY":
                draft.update(intent="CASE_GENERATE", clarification_questions=[])
    # Reviewing generated candidates includes discarding individual candidates.
    # A separate deletion proposal must not force users to adopt them first.
    can_review_candidate_deletion = bool(open_task and open_task.intent == "CASE_GENERATE"
                                         and phase == "candidate_review")
    blocked_new_task = bool(open_task and any(
        (draft["intent"] == "CASE_DELETE" and not can_review_candidate_deletion) or (
            draft["intent"] == "CASE_GENERATE" and dict(open_task.payload).get("task_intent", open_task.intent) == "CASE_MODIFY"
        ) for draft in operation_drafts))
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
            if draft_needs_confirmation(operation_drafts[0])
            else "completed"
        ),
        target_case_ids=[str(item) for item in payload.target_case_ids],
        citations=[],
        message_metadata=request_metadata,
    )
    db.add(user_message)
    db.flush()
    if blocked_new_task:
        assistant = _new_assistant_message(conversation.id,
            content="当前任务尚未采纳或放弃。请先前往工作区处理当前结果，再开始新的生成或删除任务；继续修改会保留在当前任务中。",
            intent="SMALL_TALK", confidence=1.0, status="completed", target_case_ids=[],
            metadata={"workstation_task_id": dict(open_task.payload).get("task_id", str(open_task.id))})
        db.add(assistant)
        db.commit()
        return ConversationTurnView(conversation_id=conversation.id, user_message=_message_view(user_message),
            assistant_message=_message_view(assistant), intent=intent, intent_confidence=confidence,
            requires_intent_confirmation=False, action={"type": "task_review_required"}, operation_plan=None)
    operations: list[ConversationOperation] = []
    for sequence, draft in enumerate(operation_drafts):
        use_input_targets = (draft.get("routing_source") != "semantic"
                             or draft.get("target_kind") == "previous_result") or bool(re.search(
            r"选中|所选|当前用例|这些用例|这条用例|selected|current case|these cases",
            str(draft.get("target_text", "")), re.I,
        ))
        operation = ConversationOperation(
            conversation_id=conversation.id,
            message_id=user_message.id,
            sequence=sequence,
            intent=str(draft["intent"]),
            confidence=float(draft["confidence"]),
            status=(
                "awaiting_intent"
                if draft_needs_confirmation(draft)
                else "queued"
            ),
            target={
                "kind": draft.get("target_kind", "none"),
                "selectors": [item.model_dump(mode="json") for item in payload.targets]
                if use_input_targets else [],
                "case_ids": [str(item) for item in payload.target_case_ids]
                if use_input_targets else [],
                "candidate_refs": [item.ref for item in payload.target_candidate_snapshots]
                if use_input_targets else [],
            },
            payload={
                "plan": {"version": 2, **draft},
                "instruction": str(draft["instruction"]),
                "action": str(draft.get("action") or ""),
                "reason_codes": list(draft.get("reason_codes") or []),
                "depends_on": draft.get("depends_on"),
                "predecessor_job_id": dict(conversation.context).get("pending_predecessor_job_id"),
                "source_operation_id": str(payload.source_operation_id)
                if payload.source_operation_id
                else None,
            },
            requires_confirmation=bool(draft.get("requires_confirmation")),
        )
        db.add(operation)
        operations.append(operation)
    db.flush()
    if operations and operations[0].intent in {"CASE_MODIFY", "CASE_GENERATE"}:
        payload = _link_rewrite_round(db, conversation, operations[0], payload)
    if not bool(dict(conversation.context).get("title_initialized")):
        conversation.title = summarize_conversation_title(payload.content)
        conversation.context = {
            **dict(conversation.context),
            "title_initialized": True,
        }
    assistant: ConversationMessage | None = None
    action: dict[str, Any] = {}
    if not draft_needs_confirmation(operation_drafts[0]):
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
    if task_name and assistant and assistant.related_job_id:
        enqueue_task(
            db,
            task_name,
            [str(assistant.related_job_id)],
            task_id=assistant.related_job_id,
        )
    db.commit()
    db.refresh(user_message)
    if assistant is not None:
        db.refresh(assistant)
    return ConversationTurnView(
        conversation_id=conversation.id,
        user_message=_message_view(user_message),
        assistant_message=_message_view(assistant) if assistant else None,
        intent=intent,
        intent_confidence=confidence,
        requires_intent_confirmation=draft_needs_confirmation(operation_drafts[0]),
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
    _require_idle_conversation(db, conversation)
    if user_message.status != "awaiting_intent":
        raise HTTPException(status_code=409, detail="message_not_awaiting_intent")
    request_payload = dict(user_message.message_metadata.get("request", {}))
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
    if task_name and assistant.related_job_id:
        enqueue_task(
            db,
            task_name,
            [str(assistant.related_job_id)],
            task_id=assistant.related_job_id,
        )
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant)
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
    choice = payload.model_dump(mode="json")
    receipt = dict(operation.payload).get("collection_confirmation_receipt")
    if receipt:
        if dict(operation.payload).get("collection_confirmation_request") != choice:
            raise HTTPException(409, "collection_confirmation_choice_mismatch")
        user_message = db.get(ConversationMessage, operation.message_id)
        assistant = db.get(ConversationMessage, UUID(receipt["assistant_message_id"]))
        if user_message is None or assistant is None:
            raise HTTPException(409, "collection_confirmation_result_unavailable")
        operations = list(db.scalars(select(ConversationOperation).where(
            ConversationOperation.message_id == operation.message_id,
        ).order_by(ConversationOperation.sequence)))
        return ConversationTurnView(
            conversation_id=conversation.id,
            user_message=_message_view(user_message),
            assistant_message=_message_view(assistant),
            intent=operation.intent,
            intent_confidence=operation.confidence,
            action=receipt["action"],
            operation_plan=_operation_plan_view(operations),
        )
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
    original_message = db.get(ConversationMessage, operation.message_id)
    request = dict(original_message.message_metadata).get("request", {}) if original_message else {}
    if payload.collection_id is not None and request.get("generation_strategy") in {"select", "select_and_generate"}:
        raise HTTPException(422, "generation_new_collection_required")
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
        "generation_output_collection_created": payload.collection_id is None,
    }
    operation.payload = {
        **dict(operation.payload), "collection_confirmation_request": choice,
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
            "active_view": "plan",
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


@router.patch(
    "/conversation-operations/{operation_id}/review", response_model=ConversationOperationView
)
def update_task_review(
    operation_id: UUID,
    payload: TaskReviewDecisionUpdate,
    account: CurrentAccount,
    db: DbSession,
) -> ConversationOperationView:
    operation = db.scalar(select(ConversationOperation).where(
        ConversationOperation.id == operation_id,
    ).with_for_update())
    if operation is None:
        raise HTTPException(status_code=404, detail="conversation_operation_not_found")
    _ensure_conversation(db, account.id, operation.conversation_id)
    if operation.status != "completed" or operation.intent not in ANALYSIS_INTENTS:
        raise HTTPException(status_code=409, detail="source_task_not_ready")
    findings = dict(operation.result).get("analysis_report", {}).get("findings", [])
    indexes = {*payload.selected, *payload.ignored, *payload.keep_by_finding}
    if any(index < 0 or index >= len(findings) for index in indexes):
        raise HTTPException(status_code=422, detail="invalid_finding_selection")
    for index, ref in payload.keep_by_finding.items():
        if ref not in findings[index].get("case_refs", []):
            raise HTTPException(status_code=422, detail="invalid_finding_selection")
    operation.result = {
        **dict(operation.result),
        "review_decisions": payload.model_dump(mode="json"),
    }
    db.commit()
    return _operation_view(operation)


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
    conversation = _ensure_conversation(db, account.id, operation.conversation_id)
    is_open_task = str(dict(conversation.context).get("active_mutation_task_id")) == str(dict(operation.payload).get("task_id", operation.id))
    if operation.status in {"completed", "skipped", "cancelled"} and not is_open_task:
        return _operation_view(operation)
    if not operation.status.startswith("awaiting_") and not (is_open_task and operation.status in {"completed", "failed"}):
        raise HTTPException(
            status_code=409,
            detail="conversation_operation_not_cancellable",
        )
    if operation.related_change_set_id:
        change_set = db.get(CaseChangeSet, operation.related_change_set_id)
        if change_set is not None and change_set.status == "ready":
            reject_change_set(change_set.id, account, db)
            _finish_mutation_task(db, operation, discard=True)
            db.commit()
            db.refresh(operation)
            return _operation_view(operation)
    if operation.intent == "CASE_GENERATE" and operation.status == "awaiting_confirmation":
        db.execute(update(WorkspaceCandidate).where(
            WorkspaceCandidate.conversation_id == operation.conversation_id,
            WorkspaceCandidate.generation_job_id == operation.related_job_id,
            WorkspaceCandidate.status == "candidate",
        ).values(status="excluded"))
        db.execute(update(WorkspaceTestBrief).where(
            WorkspaceTestBrief.source_operation_id == operation.id,
            WorkspaceTestBrief.status.in_(["draft", "confirmed"]),
        ).values(status="superseded"))
        operation.result = {**dict(operation.result), "discarded": True}
        conversation = db.get(Conversation, operation.conversation_id)
        if conversation and str(dict(conversation.context).get("active_operation_id")) == str(
            operation.id
        ):
            conversation.context = {**dict(conversation.context), "active_operation_id": None,
                                    "active_job_id": None, "phase": "maintenance"}
        db.add(_new_assistant_message(
            operation.conversation_id, content="已放弃本次生成方案，候选结果保留在任务历史中。",
            intent=operation.intent, confidence=1.0, status="completed", target_case_ids=[],
            metadata={"operation_id": str(operation.id), "action": "rejected"},
        ))
    else:
        db.add(_new_assistant_message(
            operation.conversation_id, content="任务已结束，可继续对话或发起新任务。",
            intent=operation.intent, confidence=1.0, status="completed", target_case_ids=[],
            metadata={"operation_id": str(operation.id), "action": "cancelled"},
        ))
    db.execute(update(ConversationOperation).where(
        ConversationOperation.message_id == operation.message_id,
        ConversationOperation.sequence > operation.sequence,
        ConversationOperation.status == "queued",
    ).values(status="cancelled", completed_at=datetime.now(UTC)))
    _finish_mutation_task(db, operation, discard=True)
    operation.status = "cancelled"
    operation.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(operation)
    return _operation_view(operation)


def _rewrite_reply_turn(db, conversation, operation, user_message, assistant, action, task_name=None):
    if action.get("type") != "cancelled":
        _operation_runtime_status(operation, assistant, action)
    conversation.context = {**dict(conversation.context), "active_operation_id": str(operation.id)}
    conversation.updated_at = datetime.now(UTC)
    if task_name and assistant.related_job_id:
        enqueue_task(db, task_name, [str(assistant.related_job_id)], task_id=assistant.related_job_id)
    db.commit()
    db.refresh(assistant)
    operations = list(db.scalars(select(ConversationOperation).where(
        ConversationOperation.message_id == operation.message_id,
    ).order_by(ConversationOperation.sequence)))
    return ConversationTurnView(
        conversation_id=conversation.id, user_message=_message_view(user_message),
        assistant_message=_message_view(assistant), intent=operation.intent,
        intent_confidence=operation.confidence, action=action,
        operation_plan=_operation_plan_view(operations),
    )


def _resume_rewrite_draft(db, account, conversation, operation, user_message, supplement):
    legacy_draft = not dict(operation.payload).get("rewrite_draft")
    pending = dict(operation.payload).get("modification_confirmation")
    if supplement.confirm_modification and (not pending or supplement.content or supplement.intent
            or supplement.targets or supplement.target_case_ids or supplement.target_candidate_snapshots):
        raise HTTPException(status_code=422, detail="modification_confirmation_invalid")
    original = _without_confirmation_supplements(
        str(operation.payload.get("instruction") or user_message.content))
    state = copy.deepcopy(dict(operation.payload).get("rewrite_draft") or {
        "version": 1,
        "scope_instruction": str(dict(operation.payload).get("plan", {}).get("target_text") or original),
        "requirements": original,
        "requirements_ready": bool(pending or dict(operation.payload).get("plan", {}).get("changes")),
        "scope_resolved": bool(dict(operation.target).get("resolved")),
    })
    if pending:
        state.update(requirements=_without_confirmation_supplements(pending["instruction"]),
                     requirements_ready=True, scope_resolved=True)
    # Auto-echoed UI selections are context; actual changed membership is a draft update.
    selection_changed = not _same_confirmation_targets(operation, supplement)
    if not state["scope_resolved"] and (supplement.target_case_ids or supplement.target_candidate_snapshots):
        selection_changed = True
    text = supplement.content or ""
    if supplement.confirm_modification or _MODIFICATION_ACKNOWLEDGEMENT.fullmatch(text):
        reply = RewriteReply(action="confirm")
    elif not text:
        reply = RewriteReply(action="update", requirements_ready=state["requirements_ready"])
    else:
        try:
            reply = interpret_rewrite_reply(text, {
                **state, "has_confirmation": bool(pending),
                "available_attachments": dict(operation.payload).get("attachment_context") or {
                    key: dict(user_message.message_metadata).get("request", {}).get(key, [])
                    for key in ("document_ids", "knowledge_source_ids")},
                "scope_cases": (pending or {}).get("cases", []) or dict(operation.target),
            }, provider=settings.agent_provider, model_name=settings.resolve_agent_model(
                dict(user_message.message_metadata).get("request", {}).get("model_id", "auto")),
                base_url=settings.agent_base_url, api_key=settings.agent_api_key,
                timeout_seconds=settings.agent_timeout_seconds,
                tracing_enabled=settings.agent_tracing_enabled)
        except Exception as exc:
            logging.getLogger(__name__).warning("rewrite_reply_failed error_type=%s", type(exc).__name__)
            reply = RewriteReply(action="clarify", clarification="暂时无法准确理解这次补充，请重试；当前用例没有改动。")
    if text:
        db.add(ConversationMessage(conversation_id=conversation.id, role="user", content=text,
            intent=operation.intent, intent_confidence=1.0, status="completed",
            target_case_ids=[], citations=[],
            message_metadata={"operation_id": str(operation.id), "rewrite_reply": reply.action}))
    if reply.action == "cancel" and reply.confidence >= 0.85:
        cancel_conversation_operation(operation.id, account, db)
        assistant = db.scalar(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.role == "assistant",
        ).order_by(ConversationMessage.created_at.desc()).limit(1))
        return _rewrite_reply_turn(db, conversation, operation, user_message, assistant, {"type": "cancelled"})
    clarification = reply.clarification if reply.action == "clarify" else ""
    if reply.confidence < 0.85:
        clarification = clarification or "这次回复是调整范围、修改要求，还是确认当前方案？请补充说明。"
    if reply.action == "confirm" and (not pending or state.get("clarification")):
        clarification = state.get("clarification") or "当前方案还未确定，请先补充用例范围和修改要求。"
    if clarification or reply.action == "clarify":
        state["clarification"] = clarification or "请说明需要调整的范围或修改要求。"
        operation.payload = {**dict(operation.payload), "rewrite_draft": state,
                             "modification_confirmation": None}
        assistant = _new_assistant_message(conversation.id, content=state["clarification"],
            intent=operation.intent, confidence=operation.confidence,
            status="awaiting_clarification", target_case_ids=[])
        db.add(assistant)
        db.flush()
        return _rewrite_reply_turn(db, conversation, operation, user_message, assistant, {"type": "clarification"})
    scope_changed = reply.scope_action == "replace" or selection_changed
    if reply.scope_action == "replace":
        state["scope_instruction"] = reply.scope_instruction
    if reply.requirements:
        state["requirements"] = reply.requirements
    state["requirements_ready"] = reply.requirements_ready
    state.pop("clarification", None)
    if scope_changed:
        state["scope_resolved"] = False
    confirm = reply.action == "confirm" and not scope_changed
    if not confirm:
        pending = None
    elif pending:
        pending = {**pending, "instruction": _without_confirmation_supplements(pending["instruction"])}
    operation.payload = {**dict(operation.payload), "rewrite_draft": state,
        "instruction": state["requirements"], "modification_confirmation": pending,
        "plan": {**dict(operation.payload).get("plan", {}), "clarification_questions": []}}
    if not state["requirements_ready"]:
        # Resolve/save a changed selection even when direction is still missing.
        operation.payload = {**dict(operation.payload), "plan": {
            **dict(operation.payload).get("plan", {}), "clarification_questions": [
                "希望这些用例达到什么修改效果？例如步骤更清晰，或只调整标题。"
            ],
        }}
    prior_targets = [{"kind": "case", "case_ids": dict(operation.target).get("case_ids", [])[i:i+100],
                      "candidate_refs": dict(operation.target).get("candidate_refs", [])[i:i+100]}
                     for i in range(0, max(len(dict(operation.target).get("case_ids", [])),
                                          len(dict(operation.target).get("candidate_refs", []))), 100)]
    fixed_scope = state["scope_resolved"] or (selection_changed and reply.scope_action != "replace")
    data = {**dict(user_message.message_metadata).get("request", {}),
        **dict(operation.payload).get("attachment_context", {}),
        "content": state["requirements"] if fixed_scope else state["scope_instruction"],
        "intent_override": "CASE_MODIFY", "target_scope": "inferred",
        "targets": prior_targets, "target_case_ids": [], "target_candidate_snapshots": []}
    if legacy_draft and not prior_targets and reply.scope_action != "replace" and not selection_changed:
        # Older pending tasks may predate scope persistence. Recover only their
        # original explicit selectors, never an unrelated current UI selection.
        request = dict(user_message.message_metadata).get("request", {})
        data.update(targets=request.get("targets") or dict(operation.target).get("selectors", []),
                    target_case_ids=request.get("target_case_ids", []),
                    target_candidate_snapshots=request.get("target_candidate_snapshots", []))
    if selection_changed and reply.scope_action != "replace":
        data.update(targets=[item.model_dump(mode="json") for item in supplement.targets],
                    target_case_ids=[str(item) for item in supplement.target_case_ids],
                    target_candidate_snapshots=[item.model_dump(mode="json") for item in supplement.target_candidate_snapshots])
    if operation.payload.get("source_operation_id"):
        data["source_operation_id"] = operation.payload["source_operation_id"]
    payload = _resolve_turn_attachments(db, conversation, ConversationMessageCreate.model_validate(data), resuming=True)
    operation.status = "running"
    assistant, action, task_name = _start_action(db, account, conversation, user_message, payload,
        "CASE_MODIFY", operation.confidence, operation.id,
        confirmed_targets=fixed_scope, confirm_modification=confirm)
    # Scope failures must never leave an executable stale preview.
    state = {**state, "scope_resolved": bool(dict(operation.target).get("resolved"))}
    operation.payload = {**dict(operation.payload), "rewrite_draft": state}
    return _rewrite_reply_turn(db, conversation, operation, user_message, assistant, action, task_name)


_MODIFICATION_ACKNOWLEDGEMENT = re.compile(
    r"\s*(?:确认|确认修改|确认并继续|确认修改并生成建议|可以|好的|confirm|yes|ok)[。！!.]?\s*",
    re.IGNORECASE,
)


def _same_confirmation_targets(operation, supplement):
    """UI selectors can differ from routing selectors while naming the same assets."""
    if not (supplement.targets or supplement.target_case_ids
            or supplement.target_candidate_snapshots):
        return True
    if any(target.kind != "case" for target in supplement.targets):
        return (not supplement.target_case_ids and not supplement.target_candidate_snapshots
                and [item.model_dump(mode="json") for item in supplement.targets]
                == dict(operation.target).get("selectors", []))
    confirmation = dict(operation.payload).get("modification_confirmation")
    expected = confirmation.get("cases", []) if confirmation else [
        *[{"ref": ref, "target_type": "formal"} for ref in dict(operation.target).get("case_ids", [])],
        *[{"ref": ref, "target_type": "candidate"} for ref in dict(operation.target).get("candidate_refs", [])],
    ]
    expected_cases = {str(item["ref"]) for item in expected if item["target_type"] == "formal"}
    expected_candidates = {str(item["ref"]) for item in expected if item["target_type"] == "candidate"}
    case_ids = {str(item) for item in supplement.target_case_ids}
    candidate_refs = {item.ref for item in supplement.target_candidate_snapshots}
    for target in supplement.targets:
        # A collection override is a changed scope, even if IDs happen to match.
        if target.collection_id is not None:
            return False
        case_ids.update(str(item) for item in target.case_ids)
        candidate_refs.update(target.candidate_refs)
    return case_ids == expected_cases and candidate_refs == expected_candidates


def _without_confirmation_supplements(instruction):
    # Recover old pending requests polluted by this bug, retaining real additions.
    return "\n".join(
        line for line in instruction.split("\n")
        if not (line.startswith("补充说明：")
                and _MODIFICATION_ACKNOWLEDGEMENT.fullmatch(line[5:]))
    )


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
    _require_idle_conversation(db, conversation)
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
    if supplement.document_ids or supplement.knowledge_source_ids:
        previous = {**dict(user_message.message_metadata).get("request", {}),
                    **dict(operation.payload).get("attachment_context", {})}
        for field in ("document_ids", "knowledge_source_ids"):
            previous[field] = list(dict.fromkeys([
                *previous.get(field, []), *map(str, getattr(supplement, field)),
            ]))
        previous.setdefault("content", user_message.content)
        attachments = _resolve_turn_attachments(
            db, conversation, ConversationMessageCreate.model_validate(previous), resuming=True)
        attachment_context = {"document_ids": list(map(str, attachments.document_ids)),
                              "knowledge_source_ids": list(map(str, attachments.knowledge_source_ids))}
        changed = any(set(previous_ids) != set(attachment_context[field]) for field, previous_ids in (
            ("document_ids", dict(operation.payload).get("attachment_context", {}).get(
                "document_ids", dict(user_message.message_metadata).get("request", {}).get("document_ids", []))),
            ("knowledge_source_ids", dict(operation.payload).get("attachment_context", {}).get(
                "knowledge_source_ids", dict(user_message.message_metadata).get("request", {}).get("knowledge_source_ids", []))),
        ))
        operation.payload = {**dict(operation.payload), "attachment_context": attachment_context,
                             **({"modification_confirmation": None, "last_confirmed_modification": None}
                                if changed else {})}
    if (operation.status == "failed" and operation.intent == "CASE_MODIFY"
            and not any((supplement.intent, supplement.content, supplement.confirm_modification,
                         supplement.targets, supplement.target_case_ids, supplement.target_candidate_snapshots))):
        approved = dict(operation.payload).get("last_confirmed_modification")
        if approved:
            operation.payload = {**dict(operation.payload), "modification_confirmation": copy.deepcopy(approved)}
            supplement = supplement.model_copy(update={"confirm_modification": True})
    if operation.intent == "CASE_MODIFY" and supplement.intent is None and (
        supplement.content or supplement.confirm_modification
        or dict(operation.payload).get("rewrite_draft")
        or supplement.targets or supplement.target_case_ids or supplement.target_candidate_snapshots
    ):
        return _resume_rewrite_draft(db, account, conversation, operation, user_message, supplement)
    if supplement.confirm_modification and (
        operation.intent != "CASE_MODIFY"
        or not dict(operation.payload).get("modification_confirmation")
        or supplement.content or supplement.intent or supplement.targets
        or supplement.target_case_ids or supplement.target_candidate_snapshots
    ):
        raise HTTPException(status_code=422, detail="modification_confirmation_invalid")
    resume_targets = list(supplement.targets)
    if (
        not resume_targets
        and not supplement.target_case_ids
        and not supplement.target_candidate_snapshots
    ):
        resume_targets = [
            ConversationTarget.model_validate(item)
            for item in dict(operation.target).get("selectors", [])
        ]
    if not resume_targets and dict(operation.target).get("resolved"):
        case_ids = list(dict(operation.target).get("case_ids", []))
        refs = list(dict(operation.target).get("candidate_refs", []))
        for offset in range(0, max(len(case_ids), len(refs)), 100):
            resume_targets.append(
                ConversationTarget(
                    kind="case",
                    case_ids=case_ids[offset : offset + 100],
                    candidate_refs=refs[offset : offset + 100],
                )
            )
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
        dependency = dict(operation.payload).get("depends_on")
        source = next(
            (item for item in ordered_predecessors if item.sequence == dependency),
            ordered_predecessors[0],
        )
        resume_targets = [
            ConversationTarget(
                kind="previous_result",
                source_operation_id=source.id,
            )
        ]
    predecessor_context = ""
    if predecessors:
        preferred = [item for item in predecessors if item.intent == (
            "COVERAGE_ANALYZE" if operation.intent == "CASE_GENERATE" else "CASE_REVIEW"
        )]
        previous = max(preferred or predecessors, key=lambda item: item.sequence)
        report = dict(previous.result).get("analysis_report")
        if report and operation.intent in {"CASE_GENERATE", "CASE_MODIFY"}:
            predecessor_context = (
                "\n依据前置检查结果处理以下建议（保持需求依据，不编造业务规则）：\n"
                + json.dumps(report, ensure_ascii=False)
            )
            operation.payload = {**dict(operation.payload), "source_operation_id": str(previous.id)}
            if not resume_targets:
                resume_targets = [
                    ConversationTarget(kind="previous_result", source_operation_id=previous.id)
                ]
    request_data = {**dict(user_message.message_metadata).get("request", {}),
                    **dict(operation.payload).get("attachment_context", {})}
    request_data.update(
        {
            "content": str(operation.payload.get("instruction") or user_message.content)
            + ("\n补充说明：" + supplement.content if supplement.content else "")
            + predecessor_context[:5000],
            "intent_override": operation.intent,
            "target_scope": "inferred",
            "targets": [item.model_dump(mode="json") for item in resume_targets],
            "target_case_ids": [str(item) for item in supplement.target_case_ids]
            or (dict(operation.target).get("case_ids", []) if not resume_targets else []),
            "target_candidate_snapshots": [
                item.model_dump(mode="json") for item in supplement.target_candidate_snapshots
            ],
        }
    )
    request_data["content"] = request_data["content"][:8000]
    if supplement.content:
        db.add(ConversationMessage(
            conversation_id=conversation.id, role="user", content=supplement.content,
            intent=operation.intent, intent_confidence=1.0, status="completed",
            target_case_ids=[], citations=[],
            message_metadata={"operation_id": str(operation.id), "clarification": True},
        ))
        operation.payload = {
            **dict(operation.payload), "instruction": request_data["content"],
            "modification_confirmation": None,
        }
    message_input = _resolve_turn_attachments(db, conversation, ConversationMessageCreate.model_validate(request_data), resuming=True)
    semantic_plan = dict(operation.payload).get("plan", {}).get("routing_source") == "semantic"
    if supplement.content and semantic_plan:
        # A complete correction replaces the old scope. Short answers still need
        # the original request to explain what is being changed.
        planning_content = request_data["content"]
        if classify_intent(supplement.content, bool(resume_targets))[0] == operation.intent:
            planning_content = supplement.content
        phase = str(dict(conversation.context).get("phase", "idle"))
        replanned = plan_intents(
            planning_content,
            lambda clause: classify_intent(clause, bool(resume_targets), phase),
            has_targets=bool(
                resume_targets
                or supplement.target_case_ids
                or supplement.target_candidate_snapshots
            ),
            phase=str(dict(conversation.context).get("phase", "idle")),
            target_context=[item.model_dump(mode="json") for item in resume_targets],
            attachment_context={"document_ids": list(map(str, message_input.document_ids)),
                                "knowledge_source_ids": list(map(str, message_input.knowledge_source_ids))},
            provider=settings.agent_provider, model_name=settings.resolve_agent_model(
                request_data.get("model_id", "auto")),
            base_url=settings.agent_base_url, api_key=settings.agent_api_key,
            timeout_seconds=settings.agent_timeout_seconds,
            tracing_enabled=settings.agent_tracing_enabled,
        )
        if len(replanned.operations) == 1 and replanned.operations[0].intent == operation.intent:
            draft = replanned.operations[0].model_dump(mode="json")
            draft["instruction"] = request_data["content"]
            operation.payload = {
                **dict(operation.payload), "instruction": draft["instruction"],
                "plan": {"version": 2, **draft},
            }
            operation.target = {**dict(operation.target), "kind": draft["target_kind"]}
        else:
            existing_plan = dict(operation.payload).get("plan", {})
            operation.payload = {**dict(operation.payload), "plan": {
                **existing_plan, "clarification_questions": [
                    "请补充当前任务的目标和修改要求；新的任务请另行发送。"
                ],
            }}
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
        confirm_modification=supplement.confirm_modification,
        # Live textual corrections must be reselected, even when the UI sends
        # its previous selection. Keep deterministic offline fixtures unchanged.
        confirmed_targets=bool(
            (not supplement.content or settings.agent_provider == "mock") and (
                supplement.targets or supplement.target_case_ids
                or supplement.target_candidate_snapshots
            )
            or (not supplement.content and resume_targets)
        ),
    )
    _operation_runtime_status(operation, assistant, action)
    conversation.context = {
        **dict(conversation.context),
        "active_operation_id": str(operation.id),
    }
    conversation.updated_at = datetime.now(UTC)
    if task_name and assistant.related_job_id:
        enqueue_task(
            db,
            task_name,
            [str(assistant.related_job_id)],
            task_id=assistant.related_job_id,
        )
    db.commit()
    db.refresh(assistant)
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
    _require_idle_conversation(db, conversation)
    failed_job = db.get(GenerationJob, failed_message.related_job_id)
    if failed_job is None:
        raise HTTPException(status_code=404, detail="generation_job_not_found")
    operation_id = failed_job.input_payload.get("conversation_operation_id")
    operation = db.get(ConversationOperation, UUID(str(operation_id))) if operation_id else None
    if operation is not None:
        if (operation.conversation_id != conversation.id
                or operation.related_job_id != failed_job.id
                or operation.status != "failed"):
            raise HTTPException(status_code=409, detail="retry_context_mismatch")
        if failed_job.operation not in {"generate", "draft_brief"}:
            return resume_conversation_operation(
                operation.id, ConversationOperationResumeRequest(), account, db,
            )
    if failed_job.status != "failed":
        raise HTTPException(status_code=409, detail="message_not_retryable")
    user_message_id = failed_job.input_payload.get("user_message_id")
    user_message = (
        db.get(ConversationMessage, UUID(str(user_message_id)))
        if user_message_id
        else None
    )
    if user_message is None or not user_message.intent:
        raise HTTPException(status_code=409, detail="retry_context_missing")
    if failed_job.operation in {"generate", "draft_brief"}:
        from casepilot_api.generation import retry_generation

        retry_generation(failed_job.id, account, db)
        db.refresh(failed_message)
        return ConversationTurnView(
            conversation_id=conversation.id,
            user_message=_message_view(user_message),
            assistant_message=_message_view(failed_message),
            intent="CASE_GENERATE", intent_confidence=1.0,
            action={"type": "generation", "job_id": str(failed_job.id)},
        )
    request_payload = dict(user_message.message_metadata.get("request", {}))
    request_payload["intent_override"] = user_message.intent
    message_input = _resolve_turn_attachments(
        db, conversation, ConversationMessageCreate.model_validate(request_payload), resuming=True,
    )
    operation_id = failed_job.input_payload.get("conversation_operation_id")
    operation = db.get(ConversationOperation, UUID(str(operation_id))) if operation_id else None
    if operation is not None and operation.conversation_id != conversation.id:
        raise HTTPException(status_code=409, detail="retry_context_mismatch")
    assistant, action, task_name = _start_action(
        db,
        account,
        conversation,
        user_message,
        message_input,
        user_message.intent,
        1.0,
        operation.id if operation else None,
    )
    if operation is not None:
        operation.status = "running"
        operation.error_code = None
        operation.completed_at = None
        _operation_runtime_status(operation, assistant, action)
    if task_name and assistant.related_job_id:
        enqueue_task(
            db,
            task_name,
            [str(assistant.related_job_id)],
            task_id=assistant.related_job_id,
        )
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant)
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
    enqueue_task(db, "casepilot.agent.generate", [str(job.id)], task_id=job.id)
    db.commit()
    after_commit(db, lambda: Redis.from_url(settings.redis_url).delete(
        f"casepilot:generation:{job.id}:events"))
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


def _merge_change_fields(item: dict, accepted: set[str]) -> dict:
    merged = copy.deepcopy(item["base_snapshot"])
    proposed = item["proposed_snapshot"]
    for field in accepted:
        if field in CHANGE_FIELDS and field in proposed:
            merged[field] = copy.deepcopy(proposed[field])
            continue
        step_match = re.fullmatch(r"steps\[(\d+)\]\.(action|expected)", field)
        if step_match:
            index = int(step_match.group(1))
            part = step_match.group(2)
            if index < len(merged.get("steps", [])) and index < len(proposed.get("steps", [])):
                merged["steps"][index][part] = proposed["steps"][index][part]
            continue
        setup_match = re.fullmatch(r"preconditions\[(\d+)\]", field)
        if setup_match:
            index = int(setup_match.group(1))
            if (
                index < len(merged.get("preconditions", []))
                and index < len(proposed.get("preconditions", []))
            ):
                merged["preconditions"][index] = proposed["preconditions"][index]
    return merged


@router.get("/case-change-sets/{change_set_id}", response_model=CaseChangeSetView)
def get_change_set(
    change_set_id: UUID,
    account: CurrentAccount,
    db: DbSession,
) -> CaseChangeSetView:
    return _change_set_view(_ensure_change_set(db, account.id, change_set_id))


def _mark_change_set_conflict(db: DbSession, change_set: CaseChangeSet) -> None:
    change_set.status = "conflict"
    operation = db.scalar(select(ConversationOperation).where(
        ConversationOperation.related_change_set_id == change_set.id
    ))
    if operation is not None:
        operation.status = "failed"
        operation.completed_at = datetime.now(UTC)
        operation.result = {**dict(operation.result), "change_set_status": "conflict"}
    db.commit()


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
    db.refresh(change_set, with_for_update=True)
    if change_set.status in {"applied", "rejected"}:
        return CaseChangeSetApplyView(change_set=_change_set_view(change_set))
    pending_incomplete = [
        item
        for item in change_set.items
        if item.get("status") not in {"applied", "rejected"}
        and item.get("quality", {}).get("passed") is False
    ]
    if change_set.status == "no_changes":
        if pending_incomplete:
            raise HTTPException(status_code=409, detail="change_item_needs_completion")
        operation = db.scalar(select(ConversationOperation).where(ConversationOperation.related_change_set_id == change_set.id))
        change_set.status = "applied"
        change_set.applied_at = datetime.now(UTC)
        generation_task = operation is not None and dict(operation.payload).get("task_intent") == "CASE_GENERATE"
        if operation is not None:
            operation.status = "completed"
            if not generation_task:
                _finish_mutation_task(db, operation)
        summary = "已采纳当前结果，无需修改用例。" + ("请继续在工作区审阅并纳入候选用例。" if generation_task else "当前任务已结束。")
        db.add(_new_assistant_message(change_set.conversation_id, content=summary,
            intent="CASE_MODIFY", confidence=1.0, status="completed", target_case_ids=[],
            metadata={"change_set_id": str(change_set.id), "operation_id": str(operation.id) if operation else None, "action": "applied"}))
        db.commit()
        return CaseChangeSetApplyView(change_set=_change_set_view(change_set))
    if change_set.status != "ready":
        raise HTTPException(status_code=409, detail="change_set_not_ready")

    if payload.review_refs is not None and (not payload.review_refs or
        not set(payload.review_refs) <= {item["ref"] for item in change_set.items}):
        raise HTTPException(status_code=422, detail="invalid_review_refs")
    review_items = [item for item in change_set.items
                    if item.get("status") not in {"applied", "rejected"}
                    and (payload.review_refs is None or item["ref"] in payload.review_refs)]
    if not review_items:
        return CaseChangeSetApplyView(change_set=_change_set_view(change_set))
    incomplete_accepts = [
        item["ref"]
        for item in review_items
        if item.get("quality", {}).get("passed") is False
        and (
            item["ref"] not in payload.accepted_fields
            or bool(
                set(payload.accepted_fields[item["ref"]])
                & {diff["field"] for diff in item.get("field_diff", [])}
            )
        )
    ]
    if incomplete_accepts:
        raise HTTPException(status_code=409, detail="change_item_needs_completion")
    reviewing = {item["ref"] for item in review_items}
    write_items = [
        item for item in review_items
        if set(payload.accepted_fields.get(
            item["ref"], [diff["field"] for diff in item.get("field_diff", [])]
        )) & {diff["field"] for diff in item.get("field_diff", [])}
    ]
    formal_items = [item for item in write_items if item["target_type"] == "formal"]
    formal_cases: dict[str, TestCase] = {}
    for item in formal_items:
        test_case = db.scalar(
            select(TestCase)
            .where(TestCase.id == UUID(item["test_case_id"]))
            .with_for_update()
        )
        if (
            test_case is None
            or test_case.deleted_at is not None
            or str(test_case.current_revision_id) != item["base_revision_id"]
        ):
            _mark_change_set_conflict(db, change_set)
            raise HTTPException(status_code=409, detail="revision_conflict")
        formal_cases[item["ref"]] = test_case

    candidate_cases: dict[str, WorkspaceCandidate] = {}
    for item in write_items:
        if item["target_type"] != "candidate":
            continue
        candidate = db.scalar(
            select(WorkspaceCandidate)
            .where(
                WorkspaceCandidate.conversation_id == change_set.conversation_id,
                WorkspaceCandidate.ref == item["ref"],
                WorkspaceCandidate.status == "candidate",
            )
            .with_for_update()
        )
        if candidate is None or candidate.version != int(item.get("base_version", 1)):
            _mark_change_set_conflict(db, change_set)
            raise HTTPException(status_code=409, detail="candidate_changed")
        candidate_cases[item["ref"]] = candidate

    created_cases: list[TestCase] = []
    candidate_snapshots: list[dict] = []
    updated_items: list[dict] = []
    for item in change_set.items:
        if item["ref"] not in reviewing:
            updated_items.append(item)
            continue
        if item["ref"] in payload.accepted_fields:
            accepted = set(payload.accepted_fields[item["ref"]])
        else:
            accepted = {str(diff["field"]) for diff in item.get("field_diff", [])}
        accepted &= {str(diff["field"]) for diff in item.get("field_diff", [])}
        if not accepted:
            updated_items.append({**item, "status": "rejected"})
            if item.get("candidate_revision_id"):
                candidate_revision = db.get(CandidateRevision, UUID(item["candidate_revision_id"]))
                if candidate_revision is not None and candidate_revision.status == "pending":
                    candidate_revision.status = "rejected"
            continue
        if item.get("operation") == "delete" and item["target_type"] == "candidate":
            candidate = candidate_cases[item["ref"]]
            candidate.status = "discarded"
            candidate.version += 1
            candidate.updated_at = datetime.now(UTC)
            updated_items.append({**item, "status": "applied", "accepted_fields": ["delete"]})
            continue
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
        merged = _merge_change_fields(item, accepted)

        if item["target_type"] == "candidate":
            candidate = candidate_cases[item["ref"]]
            candidate.snapshot = merged
            candidate.version += 1
            candidate.updated_at = datetime.now(UTC)
            candidate_snapshots.append(
                {
                    "ref": item["ref"],
                    "version": candidate.version,
                    "snapshot": merged,
                }
            )
        else:
            test_case = formal_cases[item["ref"]]
            current_revision = db.get(TestCaseRevision, test_case.current_revision_id)
            if current_revision is None:
                raise HTTPException(status_code=409, detail="test_case_revision_not_found")
            latest_number = db.scalar(
                select(func.max(TestCaseRevision.revision_number)).where(
                    TestCaseRevision.test_case_id == test_case.id
                )
            ) or 0
            revision = TestCaseRevision(
                test_case_id=test_case.id,
                revision_number=latest_number + 1,
                title=str(merged["title"]).strip(),
                description=current_revision.description or "",
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
                execution_level=current_revision.execution_level,
                test_domains=list(current_revision.test_domains),
                automation_type=current_revision.automation_type,
                automation_cases=list(current_revision.automation_cases),
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
        updated_items.append(
            {
                **item,
                "status": "applied",
                "applied_snapshot": merged,
                "accepted_fields": sorted(accepted),
            }
        )

    change_set.items = updated_items
    pending_count = sum(item.get("status") not in {"applied", "rejected"} for item in updated_items)
    has_applied = any(item.get("status") == "applied" for item in updated_items)
    change_set.status = "ready" if pending_count else "applied" if has_applied else "rejected"
    change_set.applied_at = datetime.now(UTC) if not pending_count and has_applied else None
    operation = db.scalar(
        select(ConversationOperation).where(
            ConversationOperation.related_change_set_id == change_set.id
        )
    )
    if operation is not None:
        operation.status = "awaiting_confirmation" if pending_count else "completed"
        operation.result = {
            **dict(operation.result),
            "change_set_id": str(change_set.id),
            "scope_versions": {
                **dict(operation.result.get("scope_versions", {})),
                **{str(case.id): str(case.current_revision_id) for case in created_cases},
            },
            "updated_refs": [
                str(item["ref"]) for item in updated_items if item.get("status") == "applied"
            ],
        }
        operation.completed_at = None if pending_count else datetime.now(UTC)
        if not pending_count and dict(getattr(operation, "payload", {}) or {}).get("task_intent") != "CASE_GENERATE":
            _finish_mutation_task(db, operation)
    deleted_count = sum(
        item.get("operation") == "delete" and item.get("status") == "applied"
        and item["target_type"] == "formal" for item in updated_items
    )
    discarded_refs = {item["ref"] for item in updated_items
                      if item.get("operation") == "delete" and item.get("status") == "applied"
                      and item["target_type"] == "candidate"}
    deleted_ids = {
        str(item["test_case_id"]) for item in updated_items
        if item.get("operation") == "delete" and item.get("status") == "applied"
        and item["target_type"] == "formal"
    }
    if deleted_ids or discarded_refs:
        conversation = db.get(Conversation, change_set.conversation_id)
        if conversation is not None:
            context = dict(conversation.context)
            kept_targets = []
            for selection in context.get("selected_targets", []):
                target = dict(selection.get("target", {}))
                target["case_ids"] = [
                    value for value in target.get("case_ids", []) if value not in deleted_ids
                ]
                target["candidate_refs"] = [
                    value for value in target.get("candidate_refs", []) if value not in discarded_refs
                ]
                if (
                    target.get("kind") != "case"
                    or target["case_ids"]
                    or target.get("candidate_refs")
                ):
                    kept_targets.append({**selection, "target": target})
            context["selected_targets"] = kept_targets
            if context.get("selected_case_id") in deleted_ids | discarded_refs:
                context["selected_case_id"] = ""
            conversation.context = context
            if discarded_refs:
                db.flush()
                generation_task = _open_mutation_operation(db, conversation)
                if generation_task is not None and generation_task.intent == "CASE_GENERATE":
                    remaining_candidates = db.scalar(select(WorkspaceCandidate.id).where(
                        WorkspaceCandidate.conversation_id == conversation.id,
                        WorkspaceCandidate.status.in_({"candidate", "generating"}),
                    ).limit(1))
                    if remaining_candidates is None:
                        _finish_mutation_task(db, generation_task)
                        conversation.context = {**dict(conversation.context), "phase": "maintenance"}
    has_deletions = any(
        item.get("operation") == "delete" for item in updated_items
    )
    result_message = (
        f"已确认软删除 {deleted_count} 条正式用例，丢弃 {len(discarded_refs)} 条候选，剩余 {pending_count} 条待审阅。"
        if has_deletions
        else (
            f"已采纳 {sum(item.get('status') == 'applied' for item in updated_items)} 条用例变更，"
            f"已丢弃 {sum(item.get('status') == 'rejected' for item in updated_items)} 条建议，"
            f"剩余 {pending_count} 条待审阅。"
        )
    )
    db.add(
        ConversationMessage(
            conversation_id=change_set.conversation_id,
            role="assistant",
            content=result_message,
            intent=operation.intent if operation is not None else "CASE_MODIFY",
            intent_confidence=1.0,
            status="awaiting_confirmation" if pending_count else "completed",
            target_case_ids=[str(item["ref"]) for item in updated_items],
            citations=[],
            message_metadata={
                "change_set_id": str(change_set.id),
                "action": "partially_reviewed" if pending_count else change_set.status,
                "operation_id": str(operation.id) if operation else None,
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
    db.refresh(change_set, with_for_update=True)
    if change_set.status == "ready" and any(item.get("status") == "applied" for item in change_set.items):
        refs = [item["ref"] for item in change_set.items if item.get("status") not in {"applied", "rejected"}]
        return apply_change_set(change_set_id, ChangeSetApplyRequest(
            accepted_fields={ref: [] for ref in refs}, review_refs=refs,
        ), account, db).change_set
    if change_set.status in {"generating", "ready", "no_changes"}:
        change_set.status = "rejected"
        operation = db.scalar(
            select(ConversationOperation).where(
                ConversationOperation.related_change_set_id == change_set.id
            )
        )
        stopped_followers = 0
        if operation is not None:
            operation.status = "cancelled"
            operation.completed_at = datetime.now(UTC)
            _finish_mutation_task(db, operation, discard=True)
            stopped_followers = db.execute(update(ConversationOperation).where(
                ConversationOperation.message_id == operation.message_id,
                ConversationOperation.sequence > operation.sequence,
                ConversationOperation.status == "queued",
            ).values(status="cancelled", completed_at=datetime.now(UTC))).rowcount
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
                content="已拒绝本次修改，原用例内容保持不变。" + (
                    "同一请求中尚未执行的后续任务已停止，如需继续请重新发起。"
                    if stopped_followers else ""
                ),
                intent=operation.intent if operation is not None else "CASE_MODIFY",
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
                    "operation_id": str(operation.id) if operation else None,
                },
            )
        )
        db.commit()
        db.refresh(change_set)
    return _change_set_view(change_set)


@router.put("/workspaces/{conversation_id}/test-point-links")
def save_planning_case_link(conversation_id: UUID, payload: PlanningCaseLinkRequest,
                            account: CurrentAccount, db: DbSession):
    conversation = _ensure_conversation(db, account.id, conversation_id)
    db.refresh(conversation, with_for_update=True)
    _require_idle_conversation(db, conversation)
    brief = db.scalar(select(WorkspaceTestBrief).where(
        WorkspaceTestBrief.conversation_id == conversation.id,
        WorkspaceTestBrief.version == payload.brief_version))
    latest = db.scalar(select(func.max(WorkspaceTestBrief.version)).where(
        WorkspaceTestBrief.conversation_id == conversation.id))
    if brief is None or brief.version != latest:
        raise HTTPException(409, "test_brief_version_changed")
    link_existing_case(db, conversation, brief, payload.test_point_id,
                       payload.test_case_id, payload.revision_id, payload.remove)
    db.commit()
    return links_view(db, conversation)


def _validate_reuse_source(db, conversation, account, source):
    if source.get("test_object_match") != "same":
        raise HTTPException(409, "generation_asset_changed")
    if source.get("kind") == "excel":
        try:
            document_id = UUID(str(source.get("document_id", "")))
        except ValueError as exc:
            raise HTTPException(409, "generation_asset_changed") from exc
        row = db.execute(select(KnowledgeDocument, KnowledgeSource)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
            .where(KnowledgeDocument.id == document_id,
                   KnowledgeDocument.space_id == conversation.space_id,
                   KnowledgeSource.space_id == conversation.space_id,
                   KnowledgeSource.deleted_at.is_(None)).with_for_update()).first()
        if row is None:
            raise HTTPException(409, "generation_asset_changed")
        document, origin = row
        if (document.status != "ready" or origin.status != "ready"
                or document.version != source.get("document_version")
                or document.checksum != source.get("document_checksum")
                or (document.expires_at and document.expires_at <= datetime.now(UTC))
                or (origin.persistence == "temporary" and origin.account_id != account.id)):
            raise HTTPException(409, "generation_asset_changed")
        return
    try:
        case_id = UUID(str(source.get("case_id", "")))
    except ValueError as exc:
        raise HTTPException(409, "generation_asset_changed") from exc
    case = db.scalar(select(TestCase).where(TestCase.id == case_id).with_for_update())
    if (case is None or case.deleted_at is not None or case.space_id != conversation.space_id
            or str(case.current_revision_id) != str(source["snapshot"].get("current_revision_id"))):
        raise HTTPException(409, "generation_asset_changed")


@router.post("/workspaces/{conversation_id}/generation-assets/confirm", response_model=ConversationTurnView)
def confirm_generation_assets(
    conversation_id: UUID, payload: GenerationAssetConfirmRequest,
    account: CurrentAccount, db: DbSession,
) -> ConversationTurnView:
    conversation = _ensure_conversation(db, account.id, conversation_id)
    db.scalar(select(Conversation).where(Conversation.id == conversation.id).with_for_update())
    _require_idle_conversation(db, conversation)
    brief = db.scalar(select(WorkspaceTestBrief).where(
        WorkspaceTestBrief.conversation_id == conversation.id
    ).order_by(WorkspaceTestBrief.version.desc()).limit(1))
    if brief is None or brief.version != payload.version or brief.status != "draft":
        raise HTTPException(409, "test_brief_version_changed")
    selection = dict(brief.content).get("asset_selection") or {}
    if selection.get("status") != "awaiting_confirmation":
        raise HTTPException(409, "generation_asset_selection_not_pending")
    try:
        source_job_id = UUID(str(selection.get("job_id", "")))
    except ValueError as exc:
        raise HTTPException(422, "generation_asset_selection_invalid") from exc
    original = db.get(GenerationJob, source_job_id)
    if (original is None or original.account_id != account.id
            or str(original.input_payload.get("conversation_id")) != str(conversation.id)
            or original.output_payload.get("test_brief", {}).get("asset_selection") != selection
            or brief.content.get("test_object") != selection.get("test_object")
            or (brief.content.get("asset_base_planning") or {}) != (original.output_payload.get("test_brief", {}).get("asset_base_planning") or {})):
        raise HTTPException(409, "reuse_plan_changed_reanalyze_required")
    allowed = {source["case_id"]: source for source in selection["sources"]}
    chosen = list(dict.fromkeys(str(value) for value in payload.case_ids))
    if set(chosen) - allowed.keys():
        raise HTTPException(422, "generation_asset_selection_invalid")
    if selection["strategy"] == "select" and not chosen:
        raise HTTPException(422, "generation_assets_required")
    sources = [allowed[key] for key in chosen]
    formal_sources = [source for source in sources if source.get("kind") != "excel"]
    formal_ids = [source["case_id"] for source in formal_sources]
    if selection["strategy"] == "select" and len(formal_sources) != len(sources):
        raise HTTPException(422, "generation_asset_selection_invalid")
    base_plan = dict(brief.content.get("asset_base_planning") or {})
    allowed_points = {p["id"] for p in base_plan.get("test_points", [])}
    if original.input_payload.get("asset_followup_intent") == "CASE_MODIFY":
        allowed_points = set()
        base_plan = {}
    if allowed_points and (not payload.test_point_ids or set(payload.test_point_ids) - allowed_points):
        raise HTTPException(422, "asset_target_scope_required")
    if payload.test_point_ids and not allowed_points:
        raise HTTPException(422, "asset_target_scope_invalid")
    if allowed_points:
        base_plan = {**base_plan, "test_points": [p for p in base_plan["test_points"] if p["id"] in payload.test_point_ids]}
        feature_ids = {key for point in base_plan["test_points"] for key in point["feature_point_ids"]}
        base_plan["feature_points"] = [f for f in base_plan["feature_points"] if f["id"] in feature_ids]
        base_plan.pop("reuse", None)
    for source in sources:
        _validate_reuse_source(db, conversation, account, source)
    operation = db.get(ConversationOperation, brief.source_operation_id) if brief.source_operation_id else None
    user_message = ConversationMessage(conversation_id=conversation.id, role="user",
        content=f"确认选用 {len(sources)} 条现有用例资产。", intent="CASE_GENERATE",
        intent_confidence=1.0, status="completed", target_case_ids=formal_ids, citations=[],
        message_metadata={"generation_asset_confirmation": True, "brief_version": brief.version})
    db.add(user_message)
    brief.status = "confirmed"
    brief.confirmed_by = account.id
    brief.confirmed_at = datetime.now(UTC)
    collection = ensure_collection(db, account, conversation.collection_id)
    existing = set(db.scalars(select(CollectionCaseMembership.test_case_id).where(
        CollectionCaseMembership.collection_id == collection.id)))
    for index, source in enumerate(sources if selection["strategy"] == "select" else []):
        case_id = UUID(source["case_id"])
        if case_id not in existing:
            db.add(CollectionCaseMembership(collection_id=collection.id,
                test_case_id=case_id, position=len(existing) + index))
    write_audit(db, space_id=conversation.space_id, actor_id=account.id,
        action="collection.assets_selected", resource_type="case_collection", resource_id=collection.id)
    conversation.context = {**dict(conversation.context),
        "confirmed_asset_keys": [source["key"] for source in sources],
        "confirmed_asset_test_object": selection["test_object"],
        "selected_asset_provenance": {**dict(conversation.context).get("selected_asset_provenance", {}),
            **{source["case_id"]: {"case_key": source["snapshot"].get("case_key", ""),
                "revision": source["snapshot"].get("current_revision_id", ""),
                "collections": source.get("collections", []), "kind": "selected"}
               for source in formal_sources}}}
    if original.input_payload.get("asset_followup_intent") == "CASE_MODIFY":
        if operation is None:
            raise HTTPException(409, "asset_target_operation_missing")
        operation.intent = "CASE_MODIFY"
        operation.payload = {**dict(operation.payload), "task_intent": "CASE_MODIFY",
            "asset_reference_sources": sources,
            "instruction": original.input_payload["asset_target_request"]["content"]}
        request_data = {**original.input_payload["asset_target_request"], "generation_strategy": "generate"}
        user_message.message_metadata = {**dict(user_message.message_metadata), "request": request_data}
        request = ConversationMessageCreate.model_validate(request_data)
        assistant, action, task_name = _start_action(db, account, conversation, user_message,
            request, "CASE_MODIFY", 1.0, operation.id)
        _operation_runtime_status(operation, assistant, action)
        conversation.context = {**dict(conversation.context), "phase": "maintenance",
            "active_job_id": None, "active_operation_id": str(operation.id)}
        db.add(assistant)
        db.commit()
        return ConversationTurnView(conversation_id=conversation.id,
            user_message=_message_view(user_message), assistant_message=_message_view(assistant),
            intent="CASE_MODIFY", intent_confidence=1.0, action=action)
    if selection["strategy"] == "select":
        assistant = _new_assistant_message(conversation.id,
            content=f"已将 {len(sources)} 条现有用例选入新集合，可在工作区查看。未生成新用例。",
            intent="CASE_GENERATE", confidence=1.0, status="completed", target_case_ids=chosen,
            metadata={"action": "assets_selected", "case_count": len(sources),
                **({"operation_id": str(operation.id)} if operation else {})})
        conversation.context = {
            **dict(conversation.context), "phase": "maintenance",
            "active_job_id": None, "active_view": "list",
        }
        if operation:
            operation.status = "completed"
            operation.result = {**dict(operation.result), "task_closed": True,
                "selected_case_ids": chosen}
            task_id = str(operation.payload.get("task_id") or operation.id)
            if str(conversation.context.get("active_mutation_task_id", "")) == task_id:
                conversation.context = {**dict(conversation.context), "active_mutation_task_id": None}
        action = {"type": "assets_selected", "case_count": len(sources)}
    else:
        job = GenerationJob(space_id=conversation.space_id, account_id=account.id,
            collection_id=conversation.collection_id, operation="draft_brief", status="queued",
            stage="queued", input_payload={**dict(original.input_payload),
                "asset_selection_confirmed": True, "confirmed_asset_sources": sources,
                "provided_test_object": selection["test_object"],
                "case_context": [{"ref": source["case_id"], "target_type": "formal", "snapshot": source["snapshot"]} for source in formal_sources],
                "current_test_brief": {**dict(brief.content), "asset_selection": {}, "planning": base_plan},
                "current_test_brief_version": brief.version,
            }, output_payload={})
        db.add(job)
        db.flush()
        assistant = _new_assistant_message(conversation.id,
            content="已确认复用范围，正在规划测试点并识别剩余覆盖缺口。",
            intent="CASE_GENERATE", confidence=1.0, status="running", target_case_ids=formal_ids,
            metadata={"workflow": True})
        db.add(assistant)
        db.flush()
        assistant.related_job_id = job.id
        job.input_payload = {**dict(job.input_payload), "assistant_message_id": str(assistant.id)}
        conversation.context = {**dict(conversation.context), "phase": "brief_drafting", "active_job_id": str(job.id)}
        if operation:
            operation.status = "running"
            operation.related_job_id = job.id
        enqueue_task(db, "casepilot.agent.draft_brief", [str(job.id)], task_id=job.id)
        action = {"type": "test_brief", "job_id": str(job.id)}
    db.add(assistant)
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant)
    return ConversationTurnView(conversation_id=conversation.id,
        user_message=_message_view(user_message), assistant_message=_message_view(assistant),
        intent="CASE_GENERATE", intent_confidence=1.0, action=action)
