"""Isolated live acceptance for the CasePilot conversation area.

The script uses the configured OpenAI-compatible provider for model answers and
creates uniquely named collections so it never depends on mutable demo assets.
It prints and stores a machine-readable report under ``artifacts/``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.getenv(
    "CASEPILOT_ACCEPTANCE_API_URL",
    "http://127.0.0.1:8000/api/v1",
)
EMAIL = os.getenv("CASEPILOT_ACCEPTANCE_EMAIL", "demo@casepilot.local")
PASSWORD = os.getenv("CASEPILOT_ACCEPTANCE_PASSWORD", "CasePilot123!")
MAX_FILE_BYTES = int(os.getenv("CASEPILOT_ACCEPTANCE_MAX_FILE_BYTES", "26214400"))
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "awaiting_input"}


@dataclass
class AcceptanceResult:
    case_id: str
    status: str = "passed"
    actual_reply: str = ""
    intent: str | None = None
    action: str | None = None
    operation_status: str | None = None
    conversation_id: str | None = None
    collection_id: str | None = None
    navigation: str = "stay"
    related_job_id: str | None = None
    related_change_set_id: str | None = None
    stream_events: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def require(response: httpx.Response, status: int | set[int]) -> Any:
    allowed = {status} if isinstance(status, int) else status
    if response.status_code not in allowed:
        raise AssertionError(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {response.text}"
        )
    if response.status_code == 204:
        return None
    return response.json()


@contextmanager
def login() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE_URL, timeout=45) as client:
        require(
            client.post(
                "/auth/login",
                json={"email": EMAIL, "password": PASSWORD},
            ),
            200,
        )
        yield client


def create_collection(client: httpx.Client, space_id: str, name: str) -> dict:
    return require(
        client.post(
            f"/spaces/{space_id}/collections",
            json={"name": name, "description": "对话区自动验收隔离数据"},
        ),
        201,
    )


def create_case(
    client: httpx.Client,
    collection_id: str,
    *,
    case_key: str,
    title: str,
    priority: str,
) -> dict:
    return require(
        client.post(
            f"/collections/{collection_id}/test-cases",
            json={
                "case_key": case_key,
                "title": title,
                "module": "验收模块",
                "priority": priority,
                "case_type": "功能",
                "tags": ["conversation-acceptance"],
                "preconditions": ["验收账号已登录"],
                "steps": [
                    {
                        "id": "step-1",
                        "action": "执行隔离验收步骤",
                        "expected": "系统返回隔离验收结果",
                    }
                ],
                "source": "对话区验收脚本",
            },
        ),
        201,
    )


def create_conversation(
    client: httpx.Client,
    space_id: str,
    collection_id: str | None = None,
) -> dict:
    payload: dict[str, Any] = {"space_id": space_id, "title": "新对话"}
    if collection_id:
        payload["collection_id"] = collection_id
    return require(client.post("/conversations", json=payload), 201)


def send(
    client: httpx.Client,
    conversation_id: str,
    content: str,
    *,
    targets: list[dict[str, Any]] | None = None,
) -> dict:
    return require(
        client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "content": content,
                "model_id": "auto",
                "targets": targets or [],
                "target_case_ids": [],
                "target_candidate_snapshots": [],
                "knowledge_source_ids": [],
                "document_ids": [],
                "use_space_knowledge": True,
            },
        ),
        202,
    )


def wait_job(client: httpx.Client, job_id: str, timeout: float = 360) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = require(client.get(f"/generation-jobs/{job_id}"), 200)
        if job["status"] in TERMINAL_JOB_STATUSES:
            return job
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def collect_stream_events(
    client: httpx.Client,
    job_id: str,
    timeout: float = 360,
) -> list[str]:
    events: list[str] = []
    deadline = time.monotonic() + timeout
    current = ""
    with client.stream("GET", f"/generation-jobs/{job_id}/events") as response:
        if response.status_code != 200:
            raise AssertionError(f"SSE returned {response.status_code}: {response.text}")
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                raise AssertionError(f"SSE for {job_id} exceeded {timeout}s")
            if line.startswith("event: "):
                current = line[7:]
                events.append(current)
            if current in {
                "qa.completed",
                "qa.failed",
                "generation.completed",
                "generation.failed",
                "generation.cancelled",
                "generation.awaiting_input",
                "brief.completed",
                "brief.failed",
                "rewrite.completed",
                "rewrite.failed",
            }:
                break
    return events


def finish_model_turn(
    client: httpx.Client,
    conversation_id: str,
    turn: dict,
) -> tuple[dict, list[str]]:
    job_id = turn.get("action", {}).get("job_id")
    events: list[str] = []
    if job_id:
        events = collect_stream_events(client, job_id)
        job = wait_job(client, job_id)
        assert job["status"] == "completed", job
    conversation = require(client.get(f"/conversations/{conversation_id}"), 200)
    return conversation, events


def result_from_turn(
    case_id: str,
    turn: dict,
    *,
    conversation: dict | None = None,
    events: list[str] | None = None,
    navigation: str = "stay",
    evidence: dict[str, Any] | None = None,
) -> AcceptanceResult:
    operation = (turn.get("operation_plan") or {}).get("operations", [{}])[0]
    if conversation and operation.get("id"):
        refreshed = next(
            (
                item
                for item in (conversation.get("operation_plan") or {}).get(
                    "operations", []
                )
                if item.get("id") == operation["id"]
            ),
            None,
        )
        if refreshed is not None:
            operation = refreshed
    assistant = turn.get("assistant_message") or {}
    action = operation.get("payload", {}).get("action")
    return AcceptanceResult(
        case_id=case_id,
        actual_reply=assistant.get("content", ""),
        intent=turn.get("intent"),
        action=action,
        operation_status=operation.get("status"),
        conversation_id=turn.get("conversation_id"),
        collection_id=(conversation or {}).get("collection_id"),
        navigation=navigation,
        related_job_id=operation.get("related_job_id"),
        related_change_set_id=operation.get("related_change_set_id"),
        stream_events=events or [],
        evidence=evidence or {},
    )


def run_case(
    results: list[AcceptanceResult],
    case_id: str,
    callback: Callable[[], AcceptanceResult],
) -> None:
    try:
        results.append(callback())
    except Exception as error:  # noqa: BLE001 - each case must be reported independently.
        results.append(
            AcceptanceResult(
                case_id=case_id,
                status="failed",
                evidence={"error": f"{type(error).__name__}: {error}"},
            )
        )


def main() -> None:
    started_at = datetime.now(UTC)
    token = str(time.time_ns())[-10:]
    results: list[AcceptanceResult] = []
    with login() as client:
        me = require(client.get("/auth/me"), 200)
        space_id = me["spaces"][0]["id"]
        collection_a = create_collection(
            client, space_id, f"登录回归用例-{token}"
        )
        collection_b = create_collection(
            client, space_id, f"支付回归用例-{token}"
        )
        case_a0 = create_case(
            client,
            collection_a["id"],
            case_key=f"LOGIN-{token}-P0",
            title=f"登录成功验收标记 {token}",
            priority="P0",
        )
        create_case(
            client,
            collection_a["id"],
            case_key=f"LOGIN-{token}-P1",
            title="登录失败提示",
            priority="P1",
        )
        case_b0 = create_case(
            client,
            collection_b["id"],
            case_key=f"PAY-{token}-P0",
            title="支付成功",
            priority="P0",
        )
        create_case(
            client,
            collection_b["id"],
            case_key=f"PAY-{token}-P1",
            title="支付失败回滚",
            priority="P1",
        )

        qa_conversation = create_conversation(client, space_id)

        def identity_case() -> AcceptanceResult:
            turn = send(client, qa_conversation["id"], "你是谁？你能做什么？")
            conversation, events = finish_model_turn(client, qa_conversation["id"], turn)
            reply = next(
                message["content"]
                for message in reversed(conversation["messages"])
                if message["role"] == "assistant"
            )
            turn["assistant_message"]["content"] = reply
            assert turn["intent"] == "SMALL_TALK"
            assert "CasePilot" in reply
            assert events.count("qa.delta") >= 2, events
            return result_from_turn(
                "CHAT-001", turn, conversation=conversation, events=events
            )

        run_case(results, "CHAT-001", identity_case)

        def delete_question_case() -> AcceptanceResult:
            turn = send(client, qa_conversation["id"], "如何删除测试用例？")
            conversation, events = finish_model_turn(client, qa_conversation["id"], turn)
            reply = next(
                message["content"]
                for message in reversed(conversation["messages"])
                if message["role"] == "assistant"
            )
            turn["assistant_message"]["content"] = reply
            assert turn["intent"] == "KNOWLEDGE_QA"
            assert conversation["collection_id"] is None
            assert not conversation["test_briefs"]
            return result_from_turn(
                "CHAT-003", turn, conversation=conversation, events=events
            )

        run_case(results, "CHAT-003", delete_question_case)

        def generation_gate_case() -> AcceptanceResult:
            before = require(client.get(f"/spaces/{space_id}/collections"), 200)
            turn = send(
                client,
                qa_conversation["id"],
                "为邮箱密码登录生成测试用例",
            )
            conversation = require(
                client.get(f"/conversations/{qa_conversation['id']}"), 200
            )
            after = require(client.get(f"/spaces/{space_id}/collections"), 200)
            operation = turn["operation_plan"]["operations"][0]
            assert operation["status"] == "awaiting_collection"
            assert conversation["collection_id"] is None
            assert len(after) == len(before)
            return result_from_turn(
                "INTENT-001",
                turn,
                conversation=conversation,
                evidence={"collection_count_before": len(before), "after": len(after)},
            )

        run_case(results, "INTENT-001", generation_gate_case)
        pending_generation = require(
            client.get(f"/conversations/{qa_conversation['id']}"), 200
        )["operation_plan"]["operations"][0]
        require(
            client.post(
                f"/conversation-operations/{pending_generation['id']}/cancel"
            ),
            200,
        )

        query_conversation = create_conversation(client, space_id)

        def collection_confirm_case() -> AcceptanceResult:
            turn = send(
                client,
                query_conversation["id"],
                f"查询{collection_a['name']}中的 P0 用例",
            )
            operation = turn["operation_plan"]["operations"][0]
            assert operation["status"] == "awaiting_collection"
            confirmed = require(
                client.post(
                    f"/conversation-operations/{operation['id']}/confirm-collection",
                    json={"collection_id": collection_a["id"]},
                ),
                202,
            )
            conversation = require(
                client.get(f"/conversations/{query_conversation['id']}"), 200
            )
            assert conversation["collection_id"] == collection_a["id"]
            assert case_a0["id"] in confirmed["assistant_message"]["target_case_ids"]
            return result_from_turn(
                "COLL-005",
                confirmed,
                conversation=conversation,
                navigation="workbench",
            )

        run_case(results, "COLL-005", collection_confirm_case)

        def same_collection_case() -> AcceptanceResult:
            turn = send(client, query_conversation["id"], "查询当前集合中的用例")
            conversation = require(
                client.get(f"/conversations/{query_conversation['id']}"), 200
            )
            assert turn["action"]["type"] == "case_query"
            assert conversation["collection_id"] == collection_a["id"]
            return result_from_turn("COLL-006", turn, conversation=conversation)

        run_case(results, "COLL-006", same_collection_case)

        def cross_collection_case() -> AcceptanceResult:
            turn = send(
                client,
                query_conversation["id"],
                f"查询{collection_b['name']}中的用例",
            )
            operation = turn["operation_plan"]["operations"][0]
            assert operation["status"] == "awaiting_confirmation"
            assert turn["action"]["type"] == "new_conversation_required"
            conversation = require(
                client.get(f"/conversations/{query_conversation['id']}"), 200
            )
            assert conversation["collection_id"] == collection_a["id"]
            return result_from_turn(
                "COLL-007", turn, conversation=conversation, evidence={"operation_id": operation["id"]}
            )

        run_case(results, "COLL-007", cross_collection_case)
        cross_operation = require(
            client.get(f"/conversations/{query_conversation['id']}"), 200
        )["operation_plan"]["operations"][0]

        def continue_case() -> AcceptanceResult:
            created = require(
                client.post(
                    f"/conversation-operations/{cross_operation['id']}/continue-in-new-conversation",
                    json={"collection_id": collection_b["id"]},
                ),
                201,
            )
            source = require(
                client.get(f"/conversations/{query_conversation['id']}"), 200
            )
            source_operation = source["operation_plan"]["operations"][0]
            assert created["collection_id"] == collection_b["id"]
            assert created["messages"] == []
            assert created["context"]["draft_text"]
            assert source_operation["status"] == "skipped"
            assert source_operation["result"]["continued_in_conversation_id"] == created["id"]
            return AcceptanceResult(
                case_id="COLL-008",
                operation_status="skipped",
                conversation_id=created["id"],
                collection_id=created["collection_id"],
                navigation="new_workbench",
                evidence={
                    "draft_text": created["context"]["draft_text"],
                    "message_count": len(created["messages"]),
                },
            )

        run_case(results, "COLL-008", continue_case)

        def collection_lock_case() -> AcceptanceResult:
            response = client.patch(
                f"/conversations/{query_conversation['id']}/collection",
                json={"collection_id": collection_b["id"]},
            )
            assert response.status_code == 409
            assert response.json()["detail"] == "conversation_collection_locked"
            restored = require(
                client.get(f"/conversations/{query_conversation['id']}"), 200
            )
            assert restored["collection_id"] == collection_a["id"]
            return AcceptanceResult(
                case_id="COLL-010",
                conversation_id=query_conversation["id"],
                collection_id=restored["collection_id"],
                evidence={"http_status": response.status_code, "detail": response.json()["detail"]},
            )

        run_case(results, "COLL-010", collection_lock_case)

        def target_mismatch_case() -> AcceptanceResult:
            response = client.post(
                f"/conversations/{query_conversation['id']}/messages",
                json={
                    "content": "修改选中的支付用例",
                    "model_id": "auto",
                    "targets": [
                        {
                            "kind": "case",
                            "collection_id": collection_b["id"],
                            "case_ids": [case_b0["id"]],
                        }
                    ],
                },
            )
            assert response.status_code == 422
            assert response.json()["detail"] == "target_collection_mismatch"
            return AcceptanceResult(
                case_id="COLL-012",
                conversation_id=query_conversation["id"],
                collection_id=collection_a["id"],
                evidence={"http_status": response.status_code, "detail": response.json()["detail"]},
            )

        run_case(results, "COLL-012", target_mismatch_case)

        attachment_conversation = create_conversation(client, space_id)

        def attachment_case() -> AcceptanceResult:
            # Keep the deliberately oversized multipart request on a separate
            # connection so an early 413 cannot poison the suite's keep-alive.
            with httpx.Client(
                base_url=BASE_URL,
                timeout=45,
                cookies=client.cookies,
            ) as upload_client:
                valid_txt = upload_client.post(
                    f"/conversations/{attachment_conversation['id']}/attachments",
                    files={
                        "files": ("evidence.txt", b"untrusted evidence", "text/plain")
                    },
                )
                require(valid_txt, 202)
                invalid_docx = upload_client.post(
                    f"/conversations/{attachment_conversation['id']}/attachments",
                    files={
                        "files": (
                            "evidence.docx",
                            b"PK\x03\x04not-a-real-docx",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                    },
                )
                spoofed_pdf = upload_client.post(
                    f"/conversations/{attachment_conversation['id']}/attachments",
                    files={
                        "files": ("evidence.pdf", b"not a pdf", "application/pdf")
                    },
                )
                oversized_txt = upload_client.post(
                    f"/conversations/{attachment_conversation['id']}/attachments",
                    files={
                        "files": (
                            "oversized.txt",
                            b"x" * (MAX_FILE_BYTES + 1),
                            "text/plain",
                        )
                    },
                )
            assert invalid_docx.status_code == 415
            assert spoofed_pdf.status_code == 415
            assert oversized_txt.status_code == 413
            return AcceptanceResult(
                case_id="UI-007-009",
                conversation_id=attachment_conversation["id"],
                evidence={
                    "txt": valid_txt.status_code,
                    "docx": invalid_docx.status_code,
                    "spoofed_pdf": spoofed_pdf.status_code,
                    "oversized_txt": oversized_txt.status_code,
                },
            )

        run_case(results, "UI-007-009", attachment_case)

        history_conversation = create_conversation(client, space_id, collection_a["id"])

        def history_message_search_case() -> AcceptanceResult:
            turn = send(client, history_conversation["id"], "查询当前集合中的用例")
            assert token in turn["assistant_message"]["content"]
            history = require(
                client.get(
                    "/conversations/history",
                    params={"space_id": space_id, "q": token},
                ),
                200,
            )
            assert history_conversation["id"] in {item["id"] for item in history["items"]}
            return result_from_turn(
                "UI-002",
                turn,
                conversation=require(
                    client.get(f"/conversations/{history_conversation['id']}"), 200
                ),
                evidence={"history_match_count": len(history["items"])},
            )

        run_case(results, "UI-002", history_message_search_case)

        def collection_delete_retains_conversation_case() -> AcceptanceResult:
            require(client.delete(f"/collections/{collection_a['id']}"), 204)
            restored = require(
                client.get(f"/conversations/{history_conversation['id']}"), 200
            )
            history = require(
                client.get("/conversations/history", params={"space_id": space_id}), 200
            )
            assert restored["collection_id"] is None
            assert history_conversation["id"] in {item["id"] for item in history["items"]}
            return AcceptanceResult(
                case_id="DATA-COLLECTION-DELETE",
                conversation_id=history_conversation["id"],
                collection_id=None,
                evidence={"retained_in_history": True},
            )

        run_case(results, "DATA-COLLECTION-DELETE", collection_delete_retains_conversation_case)

    finished_at = datetime.now(UTC)
    payload = {
        "suite": "CasePilot conversation acceptance v1",
        "provider": "configured-openai-compatible",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": "passed" if all(item.status == "passed" for item in results) else "failed",
        "summary": {
            "total": len(results),
            "passed": sum(item.status == "passed" for item in results),
            "failed": sum(item.status == "failed" for item in results),
        },
        "results": [asdict(item) for item in results],
    }
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    report_path = artifact_dir / f"conversation-acceptance-{started_at:%Y%m%d-%H%M%S}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**payload, "report_path": str(report_path)}, ensure_ascii=False, indent=2))
    if payload["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
