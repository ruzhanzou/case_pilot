"""Asset search requires an explicit user request, including natural language."""

import re

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
        clause = re.sub(r"(?:不|不要|无需)(?:重新)?(?:生成|改写|修改)(?:新的|新用例)?", "", clause)
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
    action = r"(?:找|搜|查找|检索|参考|参照|借鉴|复用|选用|挑选|选择|只选|沿用)"
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
