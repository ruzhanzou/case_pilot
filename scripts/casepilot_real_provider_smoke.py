"""Real-provider smoke for the structured-brief-to-library CasePilot journey."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

BASE_URL = os.getenv(
    "CASEPILOT_ACCEPTANCE_BASE_URL",
    "http://127.0.0.1:8000/api/v1",
)
TERMINAL = {"completed", "failed", "cancelled", "awaiting_input"}


def require(response: httpx.Response, status: int) -> Any:
    if response.status_code != status:
        raise AssertionError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    return response.json() if response.content else None


def wait_job(
    client: httpx.Client,
    job_id: str,
    *,
    timeout: float = 720,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = require(client.get(f"/generation-jobs/{job_id}"), 200)
        if job["status"] in TERMINAL:
            return job
        time.sleep(1)
    raise AssertionError(f"real-provider job {job_id} did not finish")


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        require(
            client.post(
                "/auth/login",
                json={
                    "email": "demo@casepilot.local",
                    "password": "CasePilot123!",
                },
            ),
            200,
        )
        me = require(client.get("/auth/me"), 200)
        space_id = me["spaces"][0]["id"]
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        collection = require(
            client.post(
                f"/spaces/{space_id}/collections",
                json={
                    "name": f"真实 Provider 冒烟 {timestamp}",
                    "description": (
                        "隔离验收：结构化说明确认后由真实 Provider 生成并写入"
                    ),
                },
            ),
            201,
        )
        collection_id = collection["id"]
        workspace = require(
            client.put(f"/collections/{collection_id}/workspace"),
            200,
        )
        workspace_id = workspace["id"]
        turn = require(
            client.post(
                f"/conversations/{workspace_id}/messages",
                json={
                    "content": (
                        "为账号密码登录生成测试用例。角色明确为已注册普通用户；"
                        "成功标准为凭有效账号密码进入工作台；覆盖正常、错误密码、"
                        "锁定、并发重复提交、弱网恢复、权限和隐私审计。"
                    ),
                    "model_id": "auto",
                    "scope": "current",
                    "target_case_ids": [],
                    "target_candidate_snapshots": [],
                    "knowledge_source_ids": [],
                    "document_ids": [],
                    "use_space_knowledge": False,
                },
            ),
            202,
        )
        brief_job = wait_job(client, turn["action"]["job_id"])
        if brief_job["status"] != "completed":
            raise AssertionError(f"real brief generation failed: {brief_job}")
        workspace = require(
            client.put(f"/collections/{collection_id}/workspace"),
            200,
        )
        brief = workspace["test_briefs"][-1]
        blockers = [
            item
            for item in brief["content"]["open_questions"]
            if item.get("blocking")
        ]
        clarified = False
        if blockers:
            content = {
                **brief["content"],
                "open_questions": [
                    item
                    for item in brief["content"]["open_questions"]
                    if not item.get("blocking")
                ],
                "assumptions": [
                    *brief["content"]["assumptions"],
                    "冒烟验收已明确角色、成功标准与测试环境，不存在阻塞项。",
                ],
            }
            brief = require(
                client.post(
                    f"/workspaces/{workspace_id}/test-briefs",
                    json={"content": content},
                ),
                201,
            )
            clarified = True
        confirmation = require(
            client.post(
                f"/workspaces/{workspace_id}/test-briefs/confirm",
                json={"version": brief["version"], "model_id": "auto"},
            ),
            202,
        )
        generation_job = wait_job(
            client,
            confirmation["action"]["job_id"],
        )
        recovered_from_invalid_response = False
        if (
            generation_job["status"] == "failed"
            and generation_job["error_code"] == "provider_response_invalid"
        ):
            require(
                client.post(
                    f"/generation-jobs/{generation_job['id']}/retry"
                ),
                202,
            )
            generation_job = wait_job(client, generation_job["id"])
            recovered_from_invalid_response = True
        if generation_job["status"] != "completed":
            raise AssertionError(f"real case generation failed: {generation_job}")
        provider_models = sorted(
            {
                str(stage["model"])
                for stage in [
                    *brief_job["stages"],
                    *generation_job["stages"],
                ]
                if stage.get("model")
                and stage["model"] != "deterministic-rules-v1"
            }
        )
        if not provider_models or any(
            "mock" in model.casefold() for model in provider_models
        ):
            raise AssertionError(
                f"real provider evidence missing: {provider_models}"
            )
        workspace = require(
            client.put(f"/collections/{collection_id}/workspace"),
            200,
        )
        candidate_count = len(workspace["candidates"])
        if candidate_count == 0:
            raise AssertionError("real provider returned no workspace candidates")
        committed = require(
            client.post(
                f"/workspaces/{workspace_id}/candidates/commit",
                json={"candidate_ids": []},
            ),
            200,
        )
        restored_workspace = require(
            client.put(f"/collections/{collection_id}/workspace"),
            200,
        )
        formal_cases = require(
            client.get(f"/collections/{collection_id}/test-cases"),
            200,
        )
        assert restored_workspace["id"] == workspace_id
        assert restored_workspace["context"]["phase"] == "maintenance"
        assert len(formal_cases) == len(committed) == candidate_count
        print(
            json.dumps(
                {
                    "status": "passed",
                    "provider_models": provider_models,
                    "brief_version": brief["version"],
                    "blocking_items_clarified": clarified,
                    "invalid_response_retry_used": (
                        recovered_from_invalid_response
                    ),
                    "candidate_count": candidate_count,
                    "committed_count": len(committed),
                    "workspace_restored": True,
                    "collection_id": collection_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
