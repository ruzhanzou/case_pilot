"""Run the full TestWeb/TestTool contract and emit a request-by-request report."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: (
            "Bearer ***"
            if key.lower() == "authorization"
            else "***"
            if key.lower() == "x-lease-token"
            else value
        )
        for key, value in headers.items()
    }


def redact_body(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***"
            if key.lower() in {"password", "lease_token"}
            else redact_body(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_body(item) for item in value]
    return value


class Recorder:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.records: list[dict[str, Any]] = []

    def request(
        self,
        name: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        started = time.monotonic()
        response = self.client.request(
            method,
            path,
            headers=headers,
            json=json_body,
            params=params,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            response_body: Any = response.json()
        except json.JSONDecodeError:
            response_body = response.text
        self.records.append(
            {
                "name": name,
                "timestamp": datetime.now(UTC).isoformat(),
                "duration_ms": duration_ms,
                "request": {
                    "method": method,
                    "path": str(response.request.url),
                    "headers": redact_headers(headers or {}),
                    "body": redact_body(json_body),
                },
                "response": {
                    "status": response.status_code,
                    "headers": {
                        "content-type": response.headers.get("content-type", "")
                    },
                    "body": redact_body(response_body),
                },
            }
        )
        if response.status_code not in expected:
            raise RuntimeError(
                f"{name} failed: HTTP {response.status_code}: {response_body}"
            )
        return response_body


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)


def write_report(
    path: Path,
    *,
    mode: str,
    started_at: datetime,
    records: list[dict[str, Any]],
    callbacks: list[dict[str, Any]],
    result: dict[str, Any],
) -> None:
    lines = [
        "# Case Service 接口逐请求测试报告",
        "",
        f"- 执行时间：{started_at.isoformat()}",
        f"- 生成模式：{mode}",
        f"- 结果：{result['status']}",
        f"- Case Project：{result.get('case_project_id', '-')}",
        f"- Generation：{result.get('case_generation_id', '-')}",
        f"- Task：{result.get('test_task_id', '-')}",
        f"- 客户端请求数：{len(records)}",
        f"- 异步回调数：{len(callbacks)}",
        "",
        "## 客户端请求与返回",
        "",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"### {index}. {record['name']}",
                "",
                f"耗时：{record['duration_ms']} ms",
                "",
                "请求：",
                "",
                "```json",
                render_json(record["request"]),
                "```",
                "",
                "返回：",
                "",
                "```json",
                render_json(record["response"]),
                "```",
                "",
            ]
        )
    lines.extend(["## 异步状态回调", ""])
    for index, callback in enumerate(callbacks, 1):
        lines.extend(
            [
                f"### Callback {index}: {callback['path']}",
                "",
                "```json",
                render_json(callback),
                "```",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--service-token", default="case-service-local")
    parser.add_argument("--tool-token", default="test-tool-local")
    parser.add_argument("--mode", choices=("mock", "real"), required=True)
    parser.add_argument("--model-id", default="auto")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--callback-log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started_at = datetime.now(UTC)
    service_headers = {"Authorization": f"Bearer {args.service_token}"}
    tool_headers = {
        "Authorization": f"Bearer {args.tool_token}",
        "X-TestTool-User-ID": "executor@casepilot.local",
    }
    result: dict[str, Any] = {"status": "FAILED"}
    with httpx.Client(base_url=args.api_url, timeout=30) as client:
        recorder = Recorder(client)
        target_number = int(time.time() * 1000) % 2_000_000_000
        target = {
            "target_type": "fr_test",
            "target_id": target_number,
            "target_key": f"FR-REVIEW-{target_number}",
            "title": "设备所有者说话人分离与弱网恢复",
            "linked_fr_ids": [],
            "linked_qpm_ids": [],
        }
        created = recorder.request(
            "创建空用例集合",
            "POST",
            "/case-projects",
            headers=service_headers,
            json_body={
                "source_system": "test_web",
                "test_target": target,
                "test_context": {
                    "description": "验证设备所有者检测、弱网恢复与长时间稳定性",
                    "platform": "Android",
                    "build_version": "review-real-1",
                },
            },
            expected=(201,),
        )
        project_id = created["case_project_id"]
        generated = recorder.request(
            "启动异步用例生成",
            "POST",
            f"/case-projects/{project_id}/case-generation-jobs",
            headers=service_headers,
            json_body={
                "test_target": target,
                "test_context": {"network_profiles": ["offline", "high_jitter"]},
                "model_id": args.model_id,
            },
            expected=(202,),
        )
        generation_id = generated["case_generation_id"]
        deadline = time.monotonic() + args.timeout
        poll_number = 0
        summary: dict[str, Any] = {}
        while time.monotonic() < deadline:
            poll_number += 1
            summary = recorder.request(
                f"轮询生成状态 #{poll_number}",
                "GET",
                f"/case-projects/{project_id}/case-summary",
                headers=service_headers,
            )
            if summary["generation_status"] in {"approved", "failed", "cancelled"}:
                break
            time.sleep(2)
        if summary.get("generation_status") != "approved":
            raise RuntimeError(f"generation not approved: {summary}")
        recorder.request(
            "POST 方式读取完整用例快照",
            "POST",
            f"/case-projects/{project_id}/case-summary",
            headers=service_headers,
        )
        task_request_id = str(uuid4())
        task = recorder.request(
            "创建待确认执行任务",
            "POST",
            f"/case-projects/{project_id}/tasks",
            headers=service_headers,
            json_body={
                "test_target": target,
                "test_context": {"build_version": "review-real-1"},
                "task_context": {
                    "tester": "executor@casepilot.local",
                    "execution_notes": "执行 L2 累计范围并同步结果",
                    "execution_level": "L2",
                },
                "task_request_id": task_request_id,
                "case_generation_id": generation_id,
            },
            expected=(202,),
        )
        recorder.request(
            "登录 CasePilot 确认人",
            "POST",
            "/api/v1/auth/login",
            json_body={
                "email": "demo@casepilot.local",
                "password": "CasePilot123!",
            },
        )
        confirmed = recorder.request(
            "确认 Playlist 并冻结 ExecutionRun",
            "POST",
            f"/api/v1/integration-task-requests/{task_request_id}/confirm",
            json_body={"execution_level": "L2"},
        )
        task_id = task["test_task_id"]
        first_case_id = next(iter(confirmed["cases"]))
        recorder.request(
            "按当前用户、target_type 与 case_id 查询任务",
            "GET",
            "/api/test-tool/v1/tasks",
            headers=tool_headers,
            params={"target_type": "fr_test", "case_id": first_case_id},
        )
        claimed = recorder.request(
            "TestTool 领取指定任务",
            "POST",
            f"/api/test-tool/v1/tasks/{task_id}/claim",
            headers=tool_headers,
            json_body={"worker_id": "review-worker", "lease_seconds": 300},
        )
        lease_token = claimed["lease_token"]
        recorder.request(
            "TestTool 续租",
            "POST",
            f"/api/test-tool/v1/tasks/{task_id}/heartbeat",
            headers={**tool_headers, "X-Lease-Token": lease_token},
            json_body={"worker_id": "review-worker", "lease_seconds": 300},
        )
        updated_at = datetime.now(UTC) + timedelta(seconds=2)
        case_updates = {
            case_id: {
                "status": "passed",
                "updated_at": updated_at.isoformat(),
                "actual_result": "真实生成用例的 Mock 执行通过",
                "completed_step_ids": [],
                "logs": [{"level": "info", "message": "review execution passed"}],
                "artifacts": [],
            }
            for case_id in confirmed["cases"]
        }
        update_id = str(uuid4())
        update_body = {
            "update_id": update_id,
            "lease_token": lease_token,
            "status": "completed",
            "updated_at": updated_at.isoformat(),
            "cases_complete": True,
            "cases": case_updates,
            "logs": [{"level": "info", "message": "task completed"}],
            "artifacts": [],
        }
        recorder.request(
            "上报完整任务与用例状态",
            "PATCH",
            f"/api/test-tool/v1/tasks/{task_id}",
            headers=tool_headers,
            json_body=update_body,
        )
        recorder.request(
            "幂等重放相同 update_id",
            "PATCH",
            f"/api/test-tool/v1/tasks/{task_id}",
            headers=tool_headers,
            json_body=update_body,
        )
        recorder.request(
            "查询单个任务用例",
            "GET",
            f"/api/test-tool/v1/tasks/{task_id}/cases/{first_case_id}",
            headers=tool_headers,
        )
        time.sleep(3)
        callbacks = []
        if args.callback_log.exists():
            callbacks = [
                json.loads(line)
                for line in args.callback_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        result = {
            "status": "PASSED",
            "case_project_id": project_id,
            "case_generation_id": generation_id,
            "test_task_id": task_id,
        }
        write_report(
            args.report,
            mode=args.mode,
            started_at=started_at,
            records=recorder.records,
            callbacks=callbacks,
            result=result,
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
