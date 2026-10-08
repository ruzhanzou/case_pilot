"""Resolve explicit user references against the current collection, never other spaces."""

import re


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
            r"|测试|的|中|里|内|下|P[0-2]|\d+\s*条|\s", "", match[1], flags=re.I
        )
        if qualifier:
            return True
    return bool(
        re.search(
            r"(?:涉及|关于|有关|相关|包含|含有|满足|符合|不含|不包括|排除|除了|除外)"
            r"[^，,。；;\n]*?(?:用例|场景)"
            r"|(?:标题|名称|步骤|预期|前置条件)(?:中|里)?(?:包含|含有|含|为|是)[^，,。；;\n]*?用例"
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
    guards = re.findall(
        r"(?:不要|无需|禁止|勿|不)(?:修改|改写|调整|删除|影响)[^，,。；;\n]*",
        instruction,
    )
    guards += re.findall(
        r"(?:其他|其余)(?:\s*\d+\s*个)?模块(?:的用例)?(?:不要动|不动|不变|保持不变|不得改动|不要改动)",
        instruction,
    )
    guards += re.findall(r"(?:保留|保持)[^，,。；;\n]*", instruction)
    positive = instruction
    for guard in guards:
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
        return {"ids": [], "modules": [], "error": "请在工作区选择排除后的具体范围，避免误操作。"}
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
    requested_keys = re.findall(
        r"(?<![a-z0-9_-])(?:CP|CASE|TC|MAP\d*)-[A-Za-z0-9-]+(?![a-z0-9_-])", instruction, re.I
    )
    known_keys = {str(case.get("case_key", "")).casefold() for case in cases}
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
                r"^(?:(?:请|仅|只|先|再|全部|所有|对|把|将|给|和|与|及|的)|"
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


def filter_priority(instruction: str, cases: list[dict]) -> list[dict]:
    text = re.sub(
        r"(?:改为|改成|设为|设置为|调整为|优先级为|\bto)\s*P[0-3]", "", instruction, flags=re.I
    )
    priorities = set(re.findall(r"(?<![A-Z0-9])P[0-3](?![A-Z0-9])", text.upper()))
    return [case for case in cases if not priorities or case.get("priority") in priorities]


def requested_new_module(instruction: str) -> str:
    """Extract the explicit module name in an additive request, preserving its path."""
    match = re.search(
        r"(?:新增|增加|添加|创建)(?:一个|个)?\s*(?:名为|名称为)?\s*(?:[「“\"]([^」”\"]+)[」”\"]\s*(?:的)?(?:空)?模块"
        r"|([^，,。；;\n「」“”\"]+?)模块)"
        r"|\b(?:add|create)\s+(?:a\s+)?(?:new\s+)?module\s+[\"']?([\w /-]+)",
        instruction, re.I,
    )
    return (next((value for value in match.groups() if value), "").strip() if match else "")[:160]
