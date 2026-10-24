"""Asset search requires an explicit user request, including natural language."""

import re
import json
from contextvars import ContextVar

choice_request_cache = ContextVar("choice_request_cache", default=None)

STRATEGY = r"(?:select_and_generate|select|generate)"
QUESTION = re.compile(
    r"(?:是什么|什么意思|区别|解释|介绍|是否支持|怎么用|如何使用|what\s+is|explain|difference|会怎样|能否|吗[？?]?$)",
    re.I,
)
DIRECTIVE = re.compile(
    rf"(?:^|[\n。；;])\s*(?:请\s*)?(?:策略\s*[:：=]?\s*)?`?(?P<start>{STRATEGY})`?(?![a-zA-Z0-9_])"
    rf"|(?:使用|采用|指定|选择|执行|按|use)\s*`?(?P<action>{STRATEGY})`?(?![a-zA-Z0-9_])"
    rf"|(?:策略|strategy)\s*[:：=]\s*`?(?P<assignment>{STRATEGY})`?(?![a-zA-Z0-9_])",
    re.I,
)


def _authorization_text(content: str) -> str:
    """Respect clause-local negation and later explicit corrections.

    Search authorization is independent from applying a found case. A refusal
    followed by a search request must still reach the asset confirmation step.
    """
    unquoted = re.sub(r"```[\s\S]*?```|[\"“「][^\"”」]*[\"”」]", "", content)
    clauses = re.split(r"[。；;，,\n]", unquoted)
    retained = []
    for clause in clauses:
        clause = clause.strip()
        negative = re.search(
            r"(?:不是让你|不是要|不要|不用|不再|禁止|取消|别|不)(?:需要|再|主动|自动|使用)?\s*"
            r"(?:搜索|查找|检索|找|搜|复用|参考|选用|历史|已有|select)", clause, re.I)
        postponed = re.search(r"(?:搜索|查找|检索|复用|参考).*(?:先不做|先别做|暂不执行|以后再做|取消)$", clause)
        if negative or postponed:
            if negative and _has_search_command("，".join(retained)) and (
                re.search(r"(?:先|暂时)?(?:不要|别)(?:直接)?复用", clause)
                or re.search(r"(?:不要|别)(?:参考|沿用|使用)(?:旧|原有|原来的)?规则", clause)
            ):
                continue
            retained = []
            continue
        # These constraints describe how to use assets, not permission to search.
        clause = re.sub(
            r"(?:不要|无需|禁止|勿|不(?:得)?)(?:重新)?(?:生成|改写|修改)(?:新的|新用例)?",
            "",
            clause,
        )
        retained.append(clause)
    return "，".join(retained)


def _has_search_command(text: str) -> bool:
    return bool(re.search(
        r"(?:^|[。；;，,\n？?])\s*(?:(?:但|另外|然后|现在|先|再|请|帮我|麻烦|能否|能不能|可以|帮忙)\s*)*"
        r"(?:查找|检索|搜索|搜搜|搜|找找|找)(?!索?(?:功能|接口|按钮|页面|框)).{0,60}(?:用例|测试案例|资产)", text))


def generation_strategy_from_text(content: str) -> str:
    # Questions, quoted text and fenced examples do not authorize asset reuse.
    if is_strategy_question(content) or re.search(r"^\s*select\s+.+\s+from\s+", content, re.I):
        return "generate"
    text = _authorization_text(content)
    matches = list(DIRECTIVE.finditer(text))
    strategy = "generate"
    for match in matches:
        before = text[max(0, match.start() - 12) : match.start()]
        if re.search(r"(?:不|不要|不用|禁止|取消|别|do\s+not|don['’]t)\s*$", before, re.I):
            strategy = "generate"
        else:
            strategy = next(value for value in match.groups() if value).lower()
    # Explicit refusal wins over an earlier directive, including mixed instructions.
    conditional_operation = bool(re.search(r"(?:如果|若).*(?:就|则).*(?:找|搜|参考|复用).*(?:确认|改写|补齐|生成)", text))
    if not (_has_search_command(text) or conditional_operation) and re.search(
        r"(?:不要|不再|禁止|取消|不用)\s*(?:复用|参考|搜索|选用|select)(?:\b|用例|资产|已有|现有|[，。；\s]|$)",
        text,
        re.I,
    ):
        return "generate"
    if matches:
        return strategy
    # Quoted examples, capability questions and conditional plans are not commands.
    if not (_has_search_command(text) or conditional_operation) and re.search(
        r"(?:如果|假如|假设|若是|将来|以后再|支持|如何|怎么|是什么|什么意思|区别|解释|介绍)", text
    ):
        return "generate"
    if re.search(
        r"(?:不要|不用|不再|禁止|取消|别|不)(?:需要|再|主动|使用)?\s*(?:搜索|查找|检索|找|搜|复用|参考|选用|历史|已有)",
        text,
    ):
        return "generate"
    if re.search(r"(?:复用|沿用)(?:已有|现有|原有)(?:的)?(?:会话|账号(?!系统)|token|连接|缓存)", text, re.I):
        return "generate"
    asset = r"(?:已有|现有|历史|原有|原来|以前|之前|过去|现成|旧(?:版|的)?用例|资产|用例库)"
    # “候选用例” contains the characters “选用”, but does not authorize
    # selecting or reusing an existing asset.
    action = r"(?:找|搜|查找|检索|参考|参照|借鉴|复用|(?<!候)选用|挑选|选择|只选|沿用)"
    explicit_search = _has_search_command(text)
    if not (
        explicit_search or re.search(action + r".{0,24}" + asset, text) or re.search(asset + r".{0,24}" + action, text)
    ):
        return "generate"
    if re.search(r"改写|重写|修改|补齐|补充|缺少|不足|重新生成|参考|参照|借鉴", text):
        return "select_and_generate"
    if re.search(r"组成|组建|直接用|直接复用|只选|仅选|不生成", text):
        return "select"
    return "select_and_generate"


def is_strategy_question(content: str) -> bool:
    if _has_search_command(_authorization_text(content)):
        return False
    english_strategy = re.search(
        r"(?<![a-zA-Z0-9_])select(?:_and_generate)?(?![a-zA-Z0-9_])", content, re.I
    )
    capability = re.search(r"系统.*支持|是否支持|如何|怎么|是什么|什么意思|区别|解释|介绍", content)
    asset_term = re.search(r"复用|搜索|用例资产|参考", content)
    return bool((english_strategy and QUESTION.search(content)) or (asset_term and capability))


def asset_choice_from_text(content: str, case_ids: list[str]) -> list[str] | None:
    """Resolve only unambiguous replies against the currently displayed asset list."""
    text = re.sub(r"[\s。！!，,]", "", content).replace("两", "二")
    if re.fullmatch(r"(?:确认|全部|都)(?:选用|复用|使用)(?:这些|以上|全部)?(?:用例|资产)?", text):
        return case_ids
    if re.fullmatch(r"(?:不复用|都不用|全部不选|不用这些)(?:继续生成)?", text):
        return []
    match = re.fullmatch(
        r"(?:只)?(?:选|选用|使用|用|复用)(?:第)?([一二三四五六七八九十]|\d+)条", text
    )
    if match:
        value = match.group(1)
        index = int(value) if value.isdigit() else "一二三四五六七八九十".index(value) + 1
        return [case_ids[index - 1]] if 0 < index <= len(case_ids) else None
    match = re.fullmatch(r"这([一二三四五六七八九十]|\d+)条直接用", text)
    if match:
        value = match.group(1)
        count = int(value) if value.isdigit() else "一二三四五六七八九十".index(value) + 1
        return case_ids if count == len(case_ids) else None
    return None


def _interpret_generation_choice(content, settings, case_ids=None, conversation_memory=None,
                                collection_catalog=None, explicit_collection_only=False):
    """Interpret strategy and selection without interpreting numeric text locally."""
    import json
    from typing import Literal

    from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
    from openai import AsyncOpenAI
    from pydantic import BaseModel, Field

    from casepilot_api.model_client import managed_model_client

    class Choice(BaseModel):
        strategy: Literal["generate", "select", "select_and_generate"] = "generate"
        target_collection_id: str | None = Field(default=None, description=(
            "明确作为本次操作目标的用例集合ID。普通业务名称、测试对象、参考来源、"
            "否定切换以及要求继续当前集合时均为null。不能仅按名称重合选集合。"
        ))
        strategy_change_requested: bool = Field(default=False, description="仅当前用户明确要求切换生成策略、搜索或选择历史用例资产时为true；编辑测试规划、保留测试点、复用登录会话均为false。")
        strategy_question: bool = False
        brief_action: Literal["none", "revise", "confirm"] = Field(
            default="none", description=(
                "当前对测试规划的动作：增删改测试点、补充需求是revise；"
                "明确接受现有规划且无任何修改要求、直接开始生成候选才是confirm；其他none。"
            )
        )
        confirms_brief: bool = False
        test_object: str = ""
        new_module: str = ""
        create_empty_module: bool = False
        rewrite_existing_assets: bool = False
        retry_requested: bool = False
        retry_kind: Literal[
            "CASE_GENERATE", "CASE_MODIFY", "CASE_DELETE", "CASE_QUERY", "CASE_REVIEW",
            "CASE_DEDUP", "COVERAGE_ANALYZE", "KNOWLEDGE_QA", "SMALL_TALK"
        ] | None = None
        selected_ids: list[str] | None = None
        ambiguous: bool = False
        requested_count: int | None = Field(default=None, ge=0)

    if settings.agent_provider == "mock":
        return Choice(strategy=generation_strategy_from_text(content),
                      strategy_question=is_strategy_question(content),
                      selected_ids=asset_choice_from_text(content, case_ids) if case_ids else None)
    set_tracing_disabled(not settings.agent_tracing_enabled)
    client = AsyncOpenAI(api_key=settings.agent_api_key,
                         base_url=settings.agent_base_url.rstrip("/"),
                         timeout=settings.agent_timeout_seconds, max_retries=1)
    agent = Agent(
        name="Generation and asset choice",
        instructions=(
            "理解当前用户的生成策略和已展示资产的选择。默认generate。"
            "仅修改测试点、替换测试点、保留原有规划不是复用历史用例资产，也不是切换生成模式。"
            "这些情况brief_action=revise、strategy_change_requested=false；复用退出前同一会话是业务动作，不是复用用例。"
            "target_collection_id仅返回用户指向的目标用例集合ID，来自collection_catalog；"
            "没有明确指向、多个集合或只是提到同名业务时返回null。"
            "explicit_collection_only为true时，必须明确将该名称当作集合，普通测试对象名称不算。"
            "参考来源集合不是要切换的目标集合；否定切换、引用示例也不是目标。"
            "例如目录有订单集合，用户说为订单业务增加用例，继续维护当前集合，"
            "target_collection_id必须是null；只有说在订单集合操作才选对应ID。"
            "confirms_brief表示明确认可当前测试说明或测试规划并要求继续生成用例。"
            "否定确认、仅询问确认方法、引用他人确认、附加修改条件都不算确认。"
            "先判断brief_action，revise和confirm互斥。增加/删除/修改测试点必须revise，"
            "即使要求原有测试点保持不变，也绝不是确认生成。"
            "例如在现有测试规划上增加一个退出登录测试点，原有两个保持不变："
            "brief_action=revise、confirms_brief=false。只有brief_action=confirm时confirms_brief才可true。"
            "test_object是用户明确指定的测试对象，结合历史理解指代，最新明确对象优先；未指定则空。"
            "new_module仅在明确要求新建模块或在指定新模块生成用例时填写名称，否则空。"
            "create_empty_module仅表示只建模块、不生成用例。"
            "rewrite_existing_assets表示明确要求依据参考资产改写已有候选，"
            "不包括重新规划、只增加测试点或生成全新用例。"
            "历史仅作理解上下文，不把过去已撤销的指令当当前授权。"
            "retry_requested仅当用户要求重试刚才失败或未完成的任务；解释重试、否定重试都不是重试。"
            "简短确认只有紧接助手明确询问是否重试才算重试。新任务或追加修改不算重试。"
            "retry_kind只填写用户指明的任务类型，未指明则null，不能从资料或旧任务猜测。"
            "Referencing historical cases to add new scenarios is select_and_generate, even without available_ids."
            "明确只搜索或选取已有用例为select；参考已有资产生成、改写或补齐为select_and_generate。"
            "解释概念、引用示例、业务本身复用会话等不授权搜索资产；strategy_question标明策略问答。"
            "理解否定、条件、纠正，最新有效要求优先。"
            "available_ids按展示顺序给出，理解中文/英文数字、序数、数量、全部、排除和不选。"
            "仅明确确认选择时返回selected_ids（允许空数组表示都不选），否则null。"
            "选择不明确或数量不符时ambiguous=true，不能猜测。requested_count只填最终选中总数，"
            "序号、业务阈值和已有数量不是总数。只返回available_ids内的ID，保持原值。"
            "Never replace the user's requested count with the number of available IDs. "
            "If the user says use these three but only two IDs exist, return requested_count=3, "
            "ambiguous=true and selected_ids=null."
        ),
        model=OpenAIChatCompletionsModel(model=settings.routing_model, openai_client=client),
        output_type=Choice,
    )
    with managed_model_client(client):
        result = Runner.run_sync(agent, json.dumps(
            {"message": content, "available_ids": case_ids or [],
             "conversation_memory": conversation_memory or [],
             "collection_catalog": collection_catalog or [],
             "explicit_collection_only": explicit_collection_only}, ensure_ascii=False),
            max_turns=1).final_output
    result.confirms_brief = result.confirms_brief and result.brief_action == "confirm"
    if (result.target_collection_id is not None
            and result.target_collection_id not in {item["id"] for item in collection_catalog or []}):
        raise ValueError("collection_reference_outside_catalog")
    if result.selected_ids is not None:
        selected = result.selected_ids
        if (len(selected) != len(set(selected)) or not set(selected) <= set(case_ids or [])
                or result.requested_count is not None and len(selected) != result.requested_count):
            result.ambiguous = True
        if result.ambiguous:
            result.selected_ids = None
    return result


def interpret_generation_choice(content, settings, case_ids=None, conversation_memory=None,
                                collection_catalog=None, explicit_collection_only=False):
    """Reuse identical interpretations only within the current HTTP request."""
    if settings.agent_provider == "mock":
        return _interpret_generation_choice(content, settings, case_ids, conversation_memory,
                                            collection_catalog, explicit_collection_only)
    cache = choice_request_cache.get()
    key = json.dumps([content, case_ids, conversation_memory, collection_catalog,
                      explicit_collection_only, settings.agent_provider, settings.routing_model],
                     ensure_ascii=False, sort_keys=True)
    if cache is not None and key in cache:
        return cache[key].model_copy(deep=True)
    result = _interpret_generation_choice(content, settings, case_ids, conversation_memory,
                                         collection_catalog, explicit_collection_only)
    if cache is not None:
        cache[key] = result.model_copy(deep=True)
    return result
