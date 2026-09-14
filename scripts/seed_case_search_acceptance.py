"""Seed isolated browser-acceptance data for case asset fuzzy search."""

from __future__ import annotations

import json
import os
import time

import httpx

BASE_URL = os.getenv("CASEPILOT_API_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("CASE_SERVICE_API_TOKEN", "case-service-local")
PASSWORD = "CasePilot123!"


def require(response: httpx.Response) -> dict:
    response.raise_for_status()
    return response.json()


def create_case(
    client: httpx.Client,
    collection_id: str,
    *,
    case_key: str,
    title: str,
    module: str,
    tags: list[str],
) -> dict:
    return require(
        client.post(
            f"{BASE_URL}/api/v1/collections/{collection_id}/test-cases",
            json={
                "case_key": case_key,
                "title": title,
                "module": module,
                "priority": "P1",
                "case_type": "功能",
                "tags": tags,
                "preconditions": ["验收环境可用"],
                "steps": [
                    {
                        "id": "step-1",
                        "action": f"执行 {title}",
                        "expected": "结果符合验收预期",
                    }
                ],
                "source": "搜索功能 E2E 验收数据",
            },
        )
    )


def main() -> None:
    suffix = str(int(time.time()))
    owner_email = f"search-owner-{suffix}@casepilot.local"
    creator_email = f"search-zhangsan-{suffix}@casepilot.local"

    owner = httpx.Client()
    creator = httpx.Client()
    owner_account = require(
        owner.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={
                "email": owner_email,
                "display_name": "李四·搜索验收",
                "password": PASSWORD,
            },
        )
    )
    require(
        creator.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={
                "email": creator_email,
                "display_name": "张三·搜索验收",
                "password": PASSWORD,
            },
        )
    )
    space_id = owner_account["spaces"][0]["id"]
    require(
        owner.post(
            f"{BASE_URL}/api/v1/spaces/{space_id}/members",
            json={"email": creator_email},
        )
    )

    service_headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    fr_target_id = int(suffix)
    project = require(
        httpx.post(
            f"{BASE_URL}/case-projects",
            headers=service_headers,
            json={
                "source_system": "testtool-e2e",
                "space_id": space_id,
                "test_target": {
                    "target_type": "fr_test",
                    "target_id": fr_target_id,
                    "target_key": f"FR-SEARCH-{suffix[-6:]}",
                    "title": "统一登录搜索验收",
                    "linked_fr_ids": [fr_target_id, f"FR-LINK-{suffix[-4:]}"],
                    "linked_qpm_ids": [f"QPM-LINK-{suffix[-4:]}"],
                },
                "test_context": {"purpose": "case-search-e2e"},
            },
        )
    )
    navigation = require(
        owner.get(
            f"{BASE_URL}/api/v1/case-projects/{project['case_project_id']}"
        )
    )
    collection_id = navigation["collection_id"]

    owner_case = create_case(
        owner,
        collection_id,
        case_key=f"SEARCH-{suffix[-6:]}-001",
        title="统一登录主链路",
        module="认证中心",
        tags=["smoke", "核心链路"],
    )
    creator_case = create_case(
        creator,
        collection_id,
        case_key=f"SEARCH-{suffix[-6:]}-002",
        title="统一登录异常恢复",
        module="认证中心",
        tags=["regression", "异常恢复"],
    )

    print(
        json.dumps(
            {
                "owner_email": owner_email,
                "creator_email": creator_email,
                "password": PASSWORD,
                "space_id": space_id,
                "case_project_id": project["case_project_id"],
                "collection_id": collection_id,
                "target": navigation["test_target"],
                "case_ids": [owner_case["id"], creator_case["id"]],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
