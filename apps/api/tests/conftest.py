"""Offline execution fixtures; scripts/qa/semantic_* exercise actual model behavior."""

import re
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def offline_provider_default(monkeypatch):
    # Developer credentials must never turn execution-contract tests into live
    # integration requests. Semantic-path tests explicitly select their provider.
    from casepilot_api.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_provider", "mock")
    from casepilot_agent.config import get_settings as get_agent_settings

    monkeypatch.setattr(get_agent_settings(), "provider", "mock")


@pytest.fixture(autouse=True)
def offline_generation_interpretation(monkeypatch):
    # Routing/scope tests already inject their respective model responses. The
    # newly separate generation interpreter must not make network calls in them.
    # Semantic accuracy is covered by the live acceptance corpus, not this stub.
    from casepilot_api import conversations
    from casepilot_api.generation_strategy import interpret_generation_choice

    def interpret(
        content,
        settings,
        case_ids=None,
        conversation_memory=None,
        collection_catalog=None,
        explicit_collection_only=False,
        current_collection_id=None,
    ):
        choice = interpret_generation_choice(
            content, SimpleNamespace(agent_provider="mock"), case_ids
        )
        collections = [
            item["id"]
            for item in collection_catalog or []
            if item["name"].casefold() in content.casefold()
            and (
                not explicit_collection_only
                or conversations._explicit_collection_mention(content, item["name"])
            )
        ]
        choice.target_collection_id = collections[0] if len(collections) == 1 else None
        choice.confirms_brief = conversations._looks_like_brief_confirmation(content)
        texts = [
            m.get("content", "") for m in (conversation_memory or []) if m.get("role") == "user"
        ]
        texts.append(content)
        choice.test_object = next(
            (
                value
                for text in reversed(texts)
                if (value := conversations._extract_explicit_test_object(text))
            ),
            "",
        )
        choice.new_module = conversations.requested_new_module(content) or ""
        choice.create_empty_module = bool(
            re.search(
                r"空模块|(?:只|仅)(?:需|要)?(?:创建|新增|增加|添加).{0,20}模块|不生成.{0,8}用例",
                content,
            )
        )
        rewrite = re.sub(
            r"(?:不要|无需|禁止|勿|不(?:得)?)(?:修改|改写|重写)[^，,。；;\n]*", "", content
        )
        choice.rewrite_existing_assets = bool(
            re.search(r"改写|修改|重写", rewrite)
        ) and not re.search(r"测试点|重新规划", content)
        choice.retry_requested = conversations._is_generation_retry(content)
        choice.retry_kind = next(
            (
                intent
                for label, intent in {
                    "生成": "CASE_GENERATE",
                    "修改": "CASE_MODIFY",
                    "删除": "CASE_DELETE",
                    "查询": "CASE_QUERY",
                    "评审": "CASE_REVIEW",
                }.items()
                if label in content
            ),
            None,
        )
        memory = conversation_memory or []
        if (
            not choice.retry_requested
            and content.strip().strip("。！! ").casefold()
            in {"确认", "是", "是的", "好的", "好", "确认重试", "yes", "ok", "confirm"}
            and len(memory) == 2
            and memory[0].get("role") == "user"
            and memory[1].get("role") == "assistant"
        ):
            choice.retry_requested = bool(
                conversations._is_generation_retry(memory[0]["content"])
                and re.search(
                    r"(?:是否|要不要|确认|要).*重试|retry.*\?", memory[1]["content"], re.I
                )
            )
        return choice

    monkeypatch.setattr(conversations, "interpret_generation_choice", interpret)


@pytest.fixture(autouse=True)
def offline_rewrite_interpretation(monkeypatch):
    # Exercise stored drafts and confirmation transitions without a live network.
    # Tests of the interpreter itself import rewrite_dialogue directly.
    from casepilot_api import conversations
    from casepilot_api.rewrite_dialogue import interpret_rewrite_reply

    def interpret(content, state, **kwargs):
        return interpret_rewrite_reply(content, state, **{**kwargs, "provider": "mock"})

    monkeypatch.setattr(conversations, "interpret_rewrite_reply", interpret)
