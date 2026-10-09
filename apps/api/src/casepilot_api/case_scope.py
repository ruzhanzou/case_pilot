"""Resolve explicit user references against the current collection, never other spaces."""

import re


PREVIOUS_QUERY_REFERENCE = re.compile(
    r"(?:刚才|上次|上述|前面)(?:查询|查找|查)(?:到|出)?的"
    r"(?:\s*(?:[0-9]+|[一二两三四五六七八九十]+)\s*条)?(?:测试)?用例"
)
FIELD_CONTENT_PATTERN = (
    r'(?P<field>标题|名称|描述|标签|前置条件|步骤|预期结果|预期)(?:中|里|内)?'
    r'(?P<operator>不包含|不含|包含|含有|含)\s*'
    r'(?P<value>「[^」]+」|“[^”]+”|"[^"]+"|[^，,。；;\n「」“”"]+?(?=的?(?:正式|候选|测试)?用例))'
)


def scope_reference_text(instruction: str) -> str:
    """New field values are data, even when they name an existing case/module."""
    text = re.sub(
        r'(?:标题|名称|描述|所属模块|模块|用例类型|类型|前置条件|步骤|预期结果|校验点)\s*'
        r'(?:统一|全部)?\s*(?:改为|改成|修改为|调整为|设置为|设为|替换为|更新为|补充为)'
        r'\s*(?:「[^」]*」|“[^”]*”|"[^"]*")',
        "", instruction,
    )
    # Field search values are predicates, not implicit case/module references.
    return re.sub(FIELD_CONTENT_PATTERN, "", text)


def unsupported_mutation_condition(instruction: str) -> bool:
    """Recognize content predicates that the deterministic resolver cannot honor.

    Quoted assignments describe the new content, not selection predicates.
    A confirmed UI selection may bypass this check in the action handler.
    """
    text = re.sub(
        r'(?:标题|名称|所属模块|模块|用例类型|类型|预期结果|校验点)\s*'
        r'(?:统一|全部)?\s*(?:改为|改成|修改为|调整为|设置为|设为|替换为|更新为|补充为|为|是|[:：])'
        r'\s*[「“"].*?[」”"]',
        "", instruction,
    )
    # A known module is not sufficient if an additional unsupported predicate
    # follows it. Keep only the subset grammar we actually resolve locally.
    module_text = re.sub(r'模块\s*[「“"][^」”"]+[」”"]', "模块", text)
    for match in re.finditer(r"模块(?:中|里|内|下)?([^，,。；;\n]*?)用例", module_text):
        qualifier = re.sub(
            r"全部|所有|当前|这些|剩余|未采纳(?:建议)?|未审阅|待审阅建议|未纳入|候选"
            r"|测试|的|中|里|内|下|优先级(?:为|是)?\s*P[0-3]|P[0-3]|\d+\s*条|\s",
            "", match[1], flags=re.I,
        )
        if qualifier:
            return True
    return bool(
        re.search(
            r"(?:涉及|关于|有关|相关|包含|含有|满足|符合|不含|不包括|排除|除了|除外)"
            r"[^，,。；;\n]*?(?:用例|场景)"
            r"|(?:标题|名称|步骤|预期|前置条件|标签|用例类型)(?:中|里)?(?:包含|含有|含|为|是)[^，,。；;\n]*?用例"
            r"|(?:失败|成功|异常|正常|超时)(?:场景)?的(?:测试)?用例"
            r"|\b(?:cases?|tests?)\s+(?:that|which|where|containing|involving|tagged|with|matching)\b"
            r"|\b(?:except|excluding)\b",
            text,
            re.I,
        )
    )


def module_parts(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"\s*(?:/|>|::|／)\s*", value) if part.strip())


def module_contains(parent: str, child: str) -> bool:
    prefix, path = module_parts(parent), module_parts(child)
    return path[: len(prefix)] == prefix if prefix else not path


def common_module_path(modules: list[str]) -> str:
    paths = [module_parts(value) for value in modules if value]
    if not paths:
        return ""
    common = list(paths[0])
    for path in paths[1:]:
        matched = 0
        while matched < min(len(common), len(path)) and common[matched] == path[matched]:
            matched += 1
        common = common[:matched]
    return "/".join(common)


def resolve_scope(instruction: str, cases: list[dict]) -> dict | None:
    """Negative guard clauses must never become additional mutation targets."""
    instruction = scope_reference_text(instruction)
    guards = re.findall(
        r"(?:不要|无需|禁止|勿|不)(?:修改|改写|调整|删除|影响)[^，,。；;\n]*",
        instruction,
    )
    guards += re.findall(
        r"(?:其他|其余)(?:\s*\d+\s*个)?模块(?:的用例)?(?:不要动|不动|不变|保持不变|不得改动|不要改动)",
        instruction,
    )
    guards += re.findall(r"(?:保留|保持)[^，,。；;\n]*", instruction)
    guards += re.findall(
        r"(?:其他|其余)[^，,。；;\n]*?(?:不变|不动|不要动)", instruction,
    )
    guards += re.findall(
        r"[^，,。；;\n]*?模块(?:的用例)?(?:保持不变|不变|不动|不要动|不得改动|不要改动)",
        instruction,
    )
    positive = instruction
    for guard in sorted(guards, key=len, reverse=True):
        positive = positive.replace(guard, "")
    scope = _resolve_scope(positive, cases)
    if not guards:
        return scope
    # If an explicit positive scope overlaps a protected case/module, ask for
    # clarification instead of silently including the protected assets.
    protected = set()
    guard_text = " ".join(guards).casefold()
    for case in cases:
        aliases = [str(case.get("case_key", "")), str(case.get("title", "")),
                   *module_parts(str(case.get("module", "")))]
        if any(alias and alias.casefold() in guard_text for alias in aliases):
            protected.add(str(case["id"]))
    if scope is None or protected.intersection(scope.get("ids", [])):
        return {"ids": [], "modules": [], "error": "请明确需要修改的范围，避免影响要求保留的用例。"}
    return scope


def _resolve_scope(instruction: str, cases: list[dict]) -> dict | None:
    """None means implicit selection; an explicit empty/error scope must not fall back."""
    text = re.sub(r"\s*(?:/|>|::|／)\s*", "/", instruction).casefold()
    if re.search(r"排除|除外|除了|\b(?:except|excluding)\b", text):
        error = {"ids": [], "modules": [], "error": "请在工作区选择排除后的具体范围，避免误操作。"}
        positive = text
        excluded = set()
        known = {str(case.get("case_key", "")).casefold(): str(case["id"]) for case in cases}
        for match in re.finditer(
            r"(?:但)?(?:排除|除了|\bexcept\b|\bexcluding\b)([^，,。；;\n]+)", text,
        ):
            clause = match[1]
            keys = re.findall(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+", clause)
            residue = clause
            for key in keys:
                if key not in known:
                    return {**error, "error": "未找到要排除的用例编号，请检查编号或当前集合。"}
                residue = residue.replace(key, "")
                excluded.add(known[key])
            residue = re.sub(r"用例|候选|编号|除外|[\s、「」“”\"']", "", residue)
            if not keys or residue:
                return error
            # A comma-separated continuation must not become a positive target.
            if re.match(r"[，,]\s*(?:用例\s*)?[a-z][a-z0-9]*(?:-[a-z0-9]+)+", text[match.end():]):
                return error
            positive = positive.replace(match.group(), "")
        if not excluded or re.search(r"排除|除外|除了|\b(?:except|excluding)\b", positive):
            return error
        scope = _resolve_scope(positive, cases)
        if scope is None or scope.get("error"):
            return scope or error
        return {**scope, "ids": [ref for ref in scope["ids"] if ref not in excluded],
                "exclusion_scope_text": positive}
    keys = [
        case
        for case in cases
        if any(
            value
            and re.search(
                (r"(?:用例|候选|编号|\bid|#)[\s:：#「“\"]*" if value.isdigit() else r"(?<![a-z0-9_-])")
                + re.escape(value.casefold()) + r"(?![a-z0-9_-])", text
            )
            for value in [str(case.get("case_key", ""))]
        )
    ]
    known_keys = {str(case.get("case_key", "")).casefold() for case in cases}
    prefixes = {key.split("-", 1)[0] for key in known_keys if "-" in key}
    prefix_pattern = "|".join([r"CP", r"CASE", r"TC", r"MAP\d*", *map(re.escape, sorted(prefixes))])
    requested_keys = re.findall(
        rf"(?<![a-z0-9_-])(?:{prefix_pattern})-[A-Za-z0-9-]+(?![a-z0-9_-])", instruction, re.I
    )
    # Custom/imported identifiers are valid references too, including mixed
    # prefix lists. Never silently keep only the identifiers that happen to exist.
    for reference in re.finditer(
        r"(?:用例|候选|编号)\s*[「“\"]?([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+"
        r"(?:[」”\"]?\s*(?:和|与|及|、|，|,)\s*(?:用例|候选|编号)?\s*[「“\"]?"
        r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)*)", instruction,
    ):
        requested_keys.extend(re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+", reference[1]))
    if any(key.casefold() not in known_keys for key in requested_keys):
        return {"ids": [], "modules": [], "error": "未找到指定编号的用例，请检查编号或当前集合。"}
    if keys:
        return {"ids": [str(case["id"]) for case in keys], "modules": []}
    titles = [case for case in cases if len(str(case.get("title", ""))) >= 4
              and str(case["title"]).casefold() in text]
    if titles:
        return {"ids": [str(case["id"]) for case in titles], "modules": []}
    paths = {str(case.get("module", "")) for case in cases if case.get("module")}
    aliases: dict[str, set[str]] = {}
    for path in paths:
        parts = module_parts(path)
        for index, part in enumerate(parts):
            prefix = "/".join(parts[: index + 1])
            aliases.setdefault(part, set()).add(prefix)
            aliases.setdefault(prefix, set()).add(prefix)
            numbered = re.fullmatch(r"\d+[-_．.、\s]+(.+)", part)
            if numbered:
                aliases.setdefault(numbered.group(1), set()).add(prefix)
    matched = [
        alias
        for alias in aliases
        if re.search(
            (r"(?<![a-z0-9])" if alias[0].isascii() and alias[0].isalnum() else "")
            + re.escape(alias.casefold())
            + (r"(?![a-z0-9])" if alias[-1].isascii() and alias[-1].isalnum() else ""),
            text,
        )
    ]
    # Prefer a full path over its component aliases.
    matched = [
        alias
        for alias in matched
        if not any(alias != other and alias in other for other in matched)
    ]
    explicit_modules = re.findall(
        r'模块[「“"]([^」”"]+)[」”"]|[「“"]([^」”"]+)[」”"]\s*模块'
        r'|([^\s，,、；;。「」“”"]+?)模块(?![「“"])', instruction
    )
    for after, before, label in explicit_modules:
        name = after or before or label
        if name.endswith(("当前", "整个", "本", "某个", "所属")):
            continue
        if not (after or before):
            name = re.sub(
                r"^(?:(?:或者|或是|以及|并且|或|请|仅|只|先|再|全部|所有|对|把|将|给|和|与|及|的)|"
                r"(?:修改|改写|重写|调整|删除|查询|查看|检查|评审|分析|生成|编写|补充)|"
                r"(?:review|modify|rewrite|delete|query|check))+", "", name, flags=re.I,
            )
        normalized_name = "/".join(module_parts(name)).casefold()
        if normalized_name not in {alias.casefold() for alias in aliases}:
            return {
                "ids": [],
                "modules": [],
                "error": "未找到指定模块，请提供完整模块路径或在工作区选择目标。",
            }
    if matched:
        if any(len(aliases[alias]) > 1 for alias in matched):
            return {"ids": [], "modules": [], "error": "模块名称有歧义，请提供完整模块路径。"}
        modules = sorted({next(iter(aliases[alias])) for alias in matched})
        return {
            "ids": [
                str(case["id"])
                for case in cases
                if any(module_contains(module, str(case.get("module", ""))) for module in modules)
            ],
            "modules": modules,
        }
    if re.search(
        r"(?:模块[「“\"].+?[」”\"]|[\w\u4e00-\u9fff]+模块|\bmodule\s+\S+)", instruction, re.I
    ) and not re.search(
        r"当前模块|本模块|整个模块|selected module|current module", instruction, re.I
    ):
        return {
            "ids": [],
            "modules": [],
            "error": "未找到指定模块，请提供完整模块路径或在工作区选择目标。",
        }
    if re.search(r"全部|所有|整个集合|当前集合|\ball\b|\bcollection\b", instruction, re.I):
        return {"ids": [str(case["id"]) for case in cases], "modules": []}
    return None


def filter_priority(instruction: str, cases: list[dict], *, mutation: bool = False) -> list[dict]:
    text = re.sub(
        r"(?:改为|改成|设为|设置为|调整为|\bto)\s*P[0-3]", "", instruction, flags=re.I
    )
    if mutation:
        text = re.sub(
            r'(?:标题|名称|描述|标签|步骤|预期(?:结果)?|前置条件|所属模块|模块)\s*'
            r'(?:统一|全部)?\s*(?:改为|改成|修改为|调整为|设置为|设为|替换为|更新为|补充为|为|是)\s*'
            r'(?:「[^」]*」|“[^”]*”|"[^"]*")', "", text,
        )
        text = re.sub(r"优先级为\s*P[0-3](?!\s*的?(?:测试)?用例)", "", text, flags=re.I)
    negative_pattern = r"优先级(?:不是|不为|不等于)\s*(P[0-3])"
    excluded = {value.upper() for value in re.findall(negative_pattern, text, re.I)}
    text = re.sub(negative_pattern, "", text, flags=re.I)
    priorities = set(re.findall(r"(?<![A-Z0-9])P[0-3](?![A-Z0-9])", text.upper()))
    return [case for case in cases if (not priorities or case.get("priority") in priorities)
            and case.get("priority") not in excluded]


def requested_new_module(instruction: str) -> str:
    """Extract the explicit module name in an additive request, preserving its path."""
    match = re.search(
        r"(?:新增|增加|添加|创建)(?:一个|个)?\s*(?:名为|名称为)?\s*(?:[「“\"]([^」”\"]+)[」”\"]\s*(?:的)?(?:空)?模块"
        r"|([^，,。；;\n「」“”\"]+?)模块)"
        r"|\b(?:add|create)\s+(?:a\s+)?(?:new\s+)?module\s+[\"']?([\w /-]+)",
        instruction, re.I,
    )
    return (next((value for value in match.groups() if value), "").strip() if match else "")[:160]


def has_content_condition(instruction: str) -> bool:
    """Content predicates require evidence matching, not module-only selection."""
    negative_pattern = r"优先级(?:不是|不为|不等于)\s*P[0-3]"
    negatives = re.findall(negative_pattern, instruction, re.I)
    if negatives:
        remaining = re.sub(negative_pattern, "", instruction, flags=re.I)
        if len(negatives) != 1 or re.search(r"P[0-3]", remaining, re.I):
            return True
        instruction = remaining
    return unsupported_mutation_condition(instruction) or bool(re.search(
        r"包含|含有|不含|涉及|关于|有关|相关|标签|前置条件|预期结果|步骤|或者|或是|或|并且|"
        r"优先级不是|优先级不为|除了|排除|除外|"
        r"\b(?:containing|with|without|tagged|matching|where|except|excluding|or|and)\b",
        instruction, re.I,
    ))


def resolve_literal_content(instruction: str, cases: list[dict]) -> tuple[list[dict], str] | None:
    """Resolve one explicit field substring; leave semantic/compound predicates to the selector."""
    matches = list(re.finditer(FIELD_CONTENT_PATTERN, instruction))
    if len(matches) != 1:
        return None
    match = matches[0]
    value = match['value'].strip(' 「」“”"').casefold()
    remaining = instruction[:match.start()] + instruction[match.end():]
    if (not value or re.search(r'或者|或|以及|并且|\b(?:and|or)\b', value, re.I)
            or has_content_condition(remaining)):
        return None
    # Only shortcut a simple query with a known scope. Unknown qualifiers and
    # additional predicates must not silently become a broader substring query.
    prefix = instruction[:match.start()]
    aliases = {str(case.get('case_key', '')) for case in cases}
    for case in cases:
        aliases.update(module_parts(str(case.get('module', ''))))
        aliases.add(str(case.get('module', '')))
    for alias in sorted(filter(None, aliases), key=len, reverse=True):
        prefix = re.sub(re.escape(alias), '', prefix, flags=re.I)
    prefix = re.sub(r'优先级(?:为|是)?\s*P[0-3]|P[0-3]', '', prefix, flags=re.I)
    prefix = re.sub(
        r'查询|查看|列出|搜索|筛选|请|仅|只|当前|整个|本|集合|模块|正式|候选|测试|用例'
        r'|选中|所选|这些|全部|所有|中|里|内|下|的|[\s/「」“”"]', '', prefix,
    )
    suffix = re.sub(
        r'只查询不修改|只查询|不修改|只列出来|正式|候选|测试|用例|的|[\s，,。；;]',
        '', instruction[match.end():],
    )
    if prefix or suffix:
        return None
    field = {'名称': 'title', '标题': 'title', '描述': 'description', '标签': 'tags',
             '前置条件': 'preconditions'}.get(match['field'])
    negative = match['operator'].startswith('不')
    selected = []
    for case in cases:
        if field:
            raw = case.get(field, '')
            values = raw if isinstance(raw, list) else [raw]
        else:
            fields = ('expected',) if match['field'].startswith('预期') else ('action', 'expected')
            values = [step.get(key, '') for step in case.get('steps', []) for key in fields]
        contains = any(value in str(item).casefold() for item in values)
        if contains != negative:
            selected.append(case)
    return selected, remaining


def resolve_module_priority_union(instruction: str, cases: list[dict]) -> list[dict] | None:
    """Evaluate complete module/priority OR clauses; never drop other predicates."""
    text = re.sub(r"^\s*(?:请)?(?:查询|查看|列出|搜索|筛选)\s*", "", instruction)
    text = re.sub(r"[，,]\s*只查询不修改[。.!！]?\s*$", "", text).strip(" 。.!！")
    clauses = re.split(r"\s*[，,]?\s*(?:或者|或是|或|\bor\b)\s*", text, flags=re.I)
    if not 2 <= len(clauses) <= 8:
        return None
    selected = set()
    for clause in clauses:
        match = re.fullmatch(
            r"(.+?)模块(?:中|里|内|下)?(?:的)?\s*(?:优先级(?:为|是)?\s*)?"
            r"(P[0-3])(?:的)?(?:测试)?用例", clause, re.I,
        )
        if not match:
            return None
        scope = resolve_scope(f'查询模块「{match[1]}」的用例', cases)
        if not scope or scope.get("error"):
            return None
        selected.update(str(case["id"]) for case in cases
                        if str(case["id"]) in scope["ids"]
                        and case.get("priority") == match[2].upper())
    return [case for case in cases if str(case["id"]) in selected]
