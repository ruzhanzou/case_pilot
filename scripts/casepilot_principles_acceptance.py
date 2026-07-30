"""Live deterministic acceptance smoke for the CasePilot product principles."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from typing import Any

import httpx

BASE_URL = os.getenv(
    "CASEPILOT_ACCEPTANCE_API_URL",
    "http://127.0.0.1:8000/api/v1",
)
PASSWORD = "CasePilot123!"
TERMINAL = {"completed", "failed", "cancelled", "awaiting_input"}


def require(response: httpx.Response, status: int | set[int]) -> Any:
    allowed = {status} if isinstance(status, int) else status
    if response.status_code not in allowed:
        raise AssertionError(
            f"{response.request.method} {response.request.url} "
            f"returned {response.status_code}: {response.text}"
        )
    if response.status_code == 204:
        return None
    return response.json()


def login(email: str) -> httpx.Client:
    client = httpx.Client(base_url=BASE_URL, timeout=30)
    require(
        client.post(
            "/auth/login",
            json={"email": email, "password": PASSWORD},
        ),
        200,
    )
    return client


def wait_job(client: httpx.Client, job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = require(client.get(f"/generation-jobs/{job_id}"), 200)
        if job["status"] in TERMINAL:
            return job
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not become terminal")


def workspace(client: httpx.Client, collection_id: str) -> dict:
    return require(client.put(f"/collections/{collection_id}/workspace"), 200)


def send(
    client: httpx.Client,
    workspace_id: str,
    content: str,
    *,
    target_case_ids: list[str] | None = None,
    scope: str = "current",
) -> dict:
    return require(
        client.post(
            f"/conversations/{workspace_id}/messages",
            json={
                "content": content,
                "model_id": "auto",
                "scope": scope,
                "target_case_ids": target_case_ids or [],
                "target_candidate_snapshots": [],
                "knowledge_source_ids": [],
                "document_ids": [],
                "use_space_knowledge": True,
            },
        ),
        202,
    )


def wait_turn(client: httpx.Client, collection_id: str, turn: dict) -> dict:
    job_id = turn["action"].get("job_id")
    if job_id:
        job = wait_job(client, job_id)
        if job["status"] == "failed":
            raise AssertionError(f"job failed: {job}")
    return workspace(client, collection_id)


def case_payload(index: int, run_token: str) -> dict:
    return {
        "case_key": f"E2E-{run_token}-{index:03}",
        "title": f"多人执行验收用例 {index}",
        "module": "多人执行",
        "priority": "P1",
        "case_type": "功能",
        "tags": ["E2E", "多人执行"],
        "preconditions": ["验收环境可用"],
        "steps": [
            {
                "id": f"step-{index}",
                "action": f"执行第 {index} 条验收操作",
                "expected": "系统返回预期结果",
            }
        ],
        "source": "隔离验收数据",
    }


def main() -> None:
    results: dict[str, str] = {}
    run_token = str(time.time_ns())[-12:]
    owner = login("demo@casepilot.local")
    executor = login("executor@casepilot.local")
    me = require(owner.get("/auth/me"), 200)
    space_id = me["spaces"][0]["id"]
    acceptance_collection = require(
        owner.post(
            f"/spaces/{space_id}/collections",
            json={
                "name": f"原则隔离验收 {time.time_ns()}",
                "description": "自动化原则验收专用集合",
            },
        ),
        201,
    )
    collection_id = acceptance_collection["id"]

    members = require(owner.get(f"/spaces/{space_id}/members"), 200)
    assert {item["email"] for item in members} >= {
        "demo@casepilot.local",
        "executor@casepilot.local",
    }
    owner_id = next(
        item["account_id"]
        for item in members
        if item["email"] == "demo@casepilot.local"
    )
    executor_id = next(
        item["account_id"]
        for item in members
        if item["email"] == "executor@casepilot.local"
    )
    results["MEM-01"] = "passed"

    first_workspace = workspace(owner, collection_id)
    second_workspace = workspace(owner, collection_id)
    shared_workspace = workspace(executor, collection_id)
    assert first_workspace["id"] == second_workspace["id"]
    assert first_workspace["id"] == shared_workspace["id"]
    workspace_id = first_workspace["id"]
    results["WS-01"] = "passed"

    greeting = send(owner, workspace_id, "你好")
    assert greeting["intent"] == "SMALL_TALK"
    assert greeting["action"]["retrieval_performed"] is False
    assert greeting["assistant_message"]["related_job_id"] is None
    identity = send(owner, workspace_id, "你是谁")
    assert "CasePilot" in identity["assistant_message"]["content"]
    results["AG-04"] = "passed"
    results["AG-05"] = "passed"

    brief_turn = send(
        owner,
        workspace_id,
        "为账号密码登录生成测试用例，覆盖正常、权限、异常、边界与并发。",
    )
    assert brief_turn["action"]["type"] == "test_brief"
    state = wait_turn(owner, collection_id, brief_turn)
    assert len(state["test_briefs"]) == 1
    assert state["candidates"] == []
    assert require(owner.get(f"/collections/{collection_id}/test-cases"), 200) == []
    assert state["context"]["phase"] == "brief_review"
    results["BR-01"] = "passed"
    results["WS-02"] = "passed"

    revision_turn = send(
        owner,
        workspace_id,
        "修改测试说明：增加弱网恢复、重复提交和隐私审计范围。",
    )
    state = wait_turn(owner, collection_id, revision_turn)
    assert [item["version"] for item in state["test_briefs"]] == [1, 2]
    assert state["test_briefs"][0]["status"] == "superseded"
    assert state["test_briefs"][1]["status"] == "draft"
    old_confirm = owner.post(
        f"/workspaces/{workspace_id}/test-briefs/confirm",
        json={"version": 1, "model_id": "auto"},
    )
    require(old_confirm, 409)
    results["BR-02"] = "passed"

    blocking_turn = send(
        owner,
        workspace_id,
        "修改测试说明：待澄清 阻塞问题，先确认目标角色。",
    )
    state = wait_turn(owner, collection_id, blocking_turn)
    blocking_brief = state["test_briefs"][-1]
    assert any(
        item.get("blocking")
        for item in blocking_brief["content"]["open_questions"]
    )
    blocked_confirm = owner.post(
        f"/workspaces/{workspace_id}/test-briefs/confirm",
        json={"version": blocking_brief["version"], "model_id": "auto"},
    )
    require(blocked_confirm, 409)
    resolved_turn = send(
        owner,
        workspace_id,
        "修改测试说明：目标角色为已注册用户，成功标准为进入工作台，并覆盖取消竞争。",
    )
    state = wait_turn(owner, collection_id, resolved_turn)
    confirmed_version = state["test_briefs"][-1]["version"]
    assert not any(
        item.get("blocking")
        for item in state["test_briefs"][-1]["content"]["open_questions"]
    )
    results["BR-03"] = "passed"

    cancel_turn = require(
        owner.post(
            f"/workspaces/{workspace_id}/test-briefs/confirm",
            json={"version": confirmed_version, "model_id": "auto"},
        ),
        202,
    )
    cancel_job_id = cancel_turn["action"]["job_id"]
    cancelled = require(
        owner.post(f"/generation-jobs/{cancel_job_id}/cancel"),
        200,
    )
    assert cancelled["status"] == "cancelled"
    state = workspace(owner, collection_id)
    assert state["candidates"] == []
    assert state["test_briefs"][-1]["status"] == "confirmed"
    results["BR-04"] = "passed"

    generation_turn = require(
        owner.post(
            f"/workspaces/{workspace_id}/test-briefs/confirm",
            json={"version": confirmed_version, "model_id": "auto"},
        ),
        202,
    )
    generation_job = wait_job(owner, generation_turn["action"]["job_id"])
    assert generation_job["status"] == "completed"
    state = workspace(owner, collection_id)
    assert state["context"]["phase"] == "candidate_review"
    assert len(state["candidates"]) >= 2
    first_candidate = state["candidates"][0]
    edited_snapshot = {
        **first_candidate["snapshot"],
        "title": f"{first_candidate['snapshot']['title']}（已审阅）",
    }
    require(
        owner.patch(
            f"/workspace-candidates/{first_candidate['id']}",
            json={"snapshot": edited_snapshot},
        ),
        200,
    )
    excluded_candidate = state["candidates"][-1]
    require(
        owner.patch(
            f"/workspace-candidates/{excluded_candidate['id']}",
            json={"included": False},
        ),
        200,
    )
    committed = require(
        owner.post(
            f"/workspaces/{workspace_id}/candidates/commit",
            json={"candidate_ids": []},
        ),
        200,
    )
    assert len(committed) == len(state["candidates"]) - 1
    assert any(item["title"].endswith("（已审阅）") for item in committed)
    assert workspace(owner, collection_id)["context"]["phase"] == "maintenance"
    results["AG-01"] = "passed"

    current_case = committed[0]
    current_modify = send(
        owner,
        workspace_id,
        "修改当前用例：补充边界校验点。",
        target_case_ids=[current_case["id"]],
    )
    current_set = require(
        owner.get(
            f"/case-change-sets/{current_modify['action']['change_set_id']}"
        ),
        {200, 404},
    ) if not current_modify["action"].get("job_id") else None
    if current_modify["action"].get("job_id"):
        wait_job(owner, current_modify["action"]["job_id"])
        current_set = require(
            owner.get(
                f"/case-change-sets/{current_modify['action']['change_set_id']}"
            ),
            200,
        )
    assert current_set and current_set["status"] == "ready"
    first_diff = current_set["items"][0]["field_diff"][0]["field"]
    applied = require(
        owner.post(
            f"/case-change-sets/{current_set['id']}/apply",
            json={
                "accepted_fields": {
                    current_set["items"][0]["ref"]: [first_diff],
                }
            },
        ),
        200,
    )
    assert applied["test_cases"][0]["revision_number"] == 2

    same_module = [
        item["id"]
        for item in committed
        if item["module"] == committed[0]["module"]
    ]
    module_modify = send(
        owner,
        workspace_id,
        "修改当前模块：补充重复操作的幂等检查。",
        target_case_ids=same_module,
        scope="module",
    )
    wait_job(owner, module_modify["action"]["job_id"])
    module_set = require(
        owner.get(
            f"/case-change-sets/{module_modify['action']['change_set_id']}"
        ),
        200,
    )
    assert len(module_set["items"]) == len(same_module)
    results["AG-02"] = "passed"

    qa_turn = send(
        owner,
        workspace_id,
        "为什么当前用例是这个优先级？",
        target_case_ids=[current_case["id"]],
    )
    assert qa_turn["intent"] == "KNOWLEDGE_QA"
    qa_job = wait_job(owner, qa_turn["action"]["job_id"])
    assert any(stage["stage"] == "context.prepared" for stage in qa_job["stages"])
    qa_state = workspace(owner, collection_id)
    qa_message = next(
        message
        for message in reversed(qa_state["messages"])
        if message["related_job_id"] == qa_turn["action"]["job_id"]
    )
    assert qa_message["citations"]

    delete_turn = send(
        owner,
        workspace_id,
        "删除当前用例",
        target_case_ids=[committed[-1]["id"]],
    )
    delete_set_id = delete_turn["action"]["change_set_id"]
    before_delete = len(
        require(owner.get(f"/collections/{collection_id}/test-cases"), 200)
    )
    require(owner.post(f"/case-change-sets/{delete_set_id}/reject"), 200)
    assert len(
        require(owner.get(f"/collections/{collection_id}/test-cases"), 200)
    ) == before_delete
    delete_turn = send(
        owner,
        workspace_id,
        "删除当前用例",
        target_case_ids=[committed[-1]["id"]],
    )
    delete_set_id = delete_turn["action"]["change_set_id"]
    require(
        owner.post(
            f"/case-change-sets/{delete_set_id}/apply",
            json={
                "accepted_fields": {
                    committed[-1]["id"]: ["delete"],
                }
            },
        ),
        200,
    )
    assert len(
        require(owner.get(f"/collections/{collection_id}/test-cases"), 200)
    ) == before_delete - 1
    results["AG-03"] = "passed"

    execution_collection = require(
        owner.post(
            f"/spaces/{space_id}/collections",
            json={
                "name": f"隔离多人执行验收集 {run_token}",
                "description": "仅用于 E2E 验收",
            },
        ),
        201,
    )
    execution_collection_id = execution_collection["id"]
    for index in range(1, 6):
        require(
            owner.post(
                f"/collections/{execution_collection_id}/test-cases",
                json=case_payload(index, run_token),
            ),
            201,
        )
    run = require(
        owner.post(
            f"/collections/{execution_collection_id}/execution-runs",
            json={
                "description": "5 条用例、2 名执行人平均分配",
                "assignee_ids": [owner_id, executor_id],
            },
        ),
        200,
    )
    counts = Counter(item["assignee_id"] for item in run["records"])
    assert sorted(counts.values()) == [2, 3]
    results["EX-01"] = "passed"

    executor_record = next(
        item for item in run["records"] if item["assignee_id"] == executor_id
    )
    forbidden = owner.patch(
        f"/execution-records/{executor_record['id']}",
        json={
            "status": "passed",
            "completed_step_ids": [
                executor_record["test_case"]["steps"][0]["id"]
            ],
            "actual_result": "不应保存",
            "defect_ref": "",
            "base_updated_at": executor_record["updated_at"],
        },
    )
    require(forbidden, 403)
    executor_run = require(executor.get(f"/execution-runs/{run['id']}"), 200)
    executor_record = next(
        item
        for item in executor_run["records"]
        if item["id"] == executor_record["id"]
    )
    updated = require(
        executor.patch(
            f"/execution-records/{executor_record['id']}",
            json={
                "status": "passed",
                "completed_step_ids": [
                    executor_record["test_case"]["steps"][0]["id"]
                ],
                "actual_result": "执行通过",
                "defect_ref": "",
                "base_updated_at": executor_record["updated_at"],
            },
        ),
        200,
    )
    owner_run = require(owner.get(f"/execution-runs/{run['id']}"), 200)
    synchronized = next(
        item for item in owner_run["records"] if item["id"] == updated["id"]
    )
    assert synchronized["status"] == "passed"
    results["EX-02"] = "passed"

    reassigned = require(
        owner.patch(
            f"/execution-records/{updated['id']}/assignee",
            json={"assignee_id": owner_id},
        ),
        200,
    )
    assert reassigned["assignee_id"] == owner_id
    assert reassigned["status"] == "passed"
    assert reassigned["actual_result"] == "执行通过"
    results["EX-03"] = "passed"

    stale = reassigned["updated_at"]
    first_update = require(
        owner.patch(
            f"/execution-records/{reassigned['id']}",
            json={
                "status": "blocked",
                "completed_step_ids": reassigned["completed_step_ids"],
                "actual_result": "等待依赖",
                "defect_ref": "",
                "base_updated_at": stale,
            },
        ),
        200,
    )
    conflict = owner.patch(
        f"/execution-records/{reassigned['id']}",
        json={
            "status": "failed",
            "completed_step_ids": first_update["completed_step_ids"],
            "actual_result": "并发旧写入",
            "defect_ref": "",
            "base_updated_at": stale,
        },
    )
    require(conflict, 409)
    closed = require(
        owner.patch(
            f"/execution-runs/{run['id']}",
            json={"status": "completed", "allow_incomplete": True},
        ),
        200,
    )
    assert closed["status"] == "completed"
    read_only = owner.patch(
        f"/execution-records/{reassigned['id']}",
        json={
            "status": "passed",
            "completed_step_ids": reassigned["completed_step_ids"],
            "actual_result": "任务已结束",
            "defect_ref": "",
            "base_updated_at": first_update["updated_at"],
        },
    )
    require(read_only, 409)
    results["EX-04"] = "passed"

    empty_collection = require(
        owner.post(
            f"/spaces/{space_id}/collections",
            json={
                "name": f"空执行集合 {run_token}",
                "description": "验证空集合门禁",
            },
        ),
        201,
    )
    empty_run = owner.post(
        f"/collections/{empty_collection['id']}/execution-runs",
        json={
            "description": "不应创建",
            "assignee_ids": [owner_id],
        },
    )
    require(empty_run, 409)
    results["EX-EMPTY"] = "passed"

    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    owner.close()
    executor.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ACCEPTANCE FAILED: {error}", file=sys.stderr)
        raise
