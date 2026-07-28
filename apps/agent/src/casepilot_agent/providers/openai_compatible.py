import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from casepilot_agent.contracts import (
    GenerationRequest,
    GenerationResult,
    RewriteCandidate,
    RewriteRequest,
)

ResultT = TypeVar("ResultT", bound=BaseModel)


class ProviderResponseError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        if not api_key:
            raise ValueError("agent_api_key_required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "openai_compatible"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        prompt = (
            "你是测试设计 Agent。根据输入生成严格 JSON，字段必须符合给定 schema。"
            "要求建立需求、功能点、测试点、用例的引用链，不虚构未提供的确定性规则。\n"
            f"schema={json.dumps(GenerationResult.model_json_schema(), ensure_ascii=False)}\n"
            f"需求={request.prompt}\nMarkdown={request.markdown_content}"
        )
        return self._request(prompt, GenerationResult)

    def rewrite(self, request: RewriteRequest) -> RewriteCandidate:
        prompt = (
            "你是测试用例改写 Agent。只按指令修改必要字段，返回完整候选、字段 diff、"
            "修改理由和质量报告，不能声称已覆盖原版本。\n"
            f"schema={json.dumps(RewriteCandidate.model_json_schema(), ensure_ascii=False)}\n"
            f"原用例={request.test_case.model_dump_json()}\n指令={request.instruction}"
        )
        return self._request(prompt, RewriteCandidate)

    def _request(self, prompt: str, result_type: type[ResultT]) -> ResultT:
        validation_feedback = ""
        for attempt in range(2):
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": prompt + validation_feedback}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            try:
                content = payload["choices"][0]["message"]["content"]
                return result_type.model_validate_json(content)
            except (KeyError, IndexError, TypeError, ValidationError, ValueError) as error:
                if attempt == 1:
                    raise ProviderResponseError(
                        "invalid_structured_model_response"
                    ) from error
                validation_feedback = (
                    "\n上一次输出未通过结构校验。请修复并只返回 JSON。"
                    f"错误类型：{error.__class__.__name__}"
                )
        raise ProviderResponseError("model_response_unavailable")
