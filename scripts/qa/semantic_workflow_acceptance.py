"""Real model + API + worker acceptance in a temporary synthetic account.

Run with local DATABASE_URL and REDIS_URL. Only the created account is mutated
and it is removed on exit; model credentials are never included in the report.
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

from casepilot_agent import tasks
from casepilot_api import conversations
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Space
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete


async def main(
    output_path="artifacts/semantic-acceptance/workflows.json", intents=None
):
    assert (
        conversations.settings.agent_provider != "mock"
        and tasks.settings.provider != "mock"
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    # Run each queued job ourselves against the current checkout, never an older
    # background worker. All actual model calls and persistence remain enabled.
    original_enqueue = conversations.enqueue_task
    conversations.enqueue_task = lambda *args, **kwargs: None
    account = None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def request(method, path, body=None):
            response = await client.request(method, "/api/v1" + path, json=body)
            if response.is_error:
                raise RuntimeError(
                    f"HTTP {response.status_code}: {response.text[:800]}"
                )
            return response.json()

        try:
            account = await request(
                "POST",
                "/auth/register",
                {
                    "email": f"semantic-acceptance-{uuid4().hex}@casepilot.test",
                    "password": "SyntheticAcceptance123!",
                    "display_name": "Semantic acceptance",
                },
            )
            space = account["spaces"][0]["id"]
            scenarios = [
                ("SMALL_TALK", "你好"),
                ("KNOWLEDGE_QA", "请解释测试中的等价类划分"),
                ("CASE_QUERY", "查询当前集合全部用例"),
                ("CASE_REVIEW", "review全部当前集合用例，指出质量问题"),
                ("CASE_DEDUP", "找出当前集合重复的用例"),
                ("COVERAGE_ANALYZE", "分析当前集合登录用例的测试覆盖缺口"),
                ("CASE_MODIFY", "仅将用例 {case_key} 的优先级改为P0，其他字段保持不变"),
                ("CASE_DELETE", "删除用例 {case_key}"),
                (
                    "CASE_GENERATE",
                    "为登录系统规划两个测试点并生成两条用例：有效密码登录成功，错误密码登录失败；仅覆盖这两种场景",
                ),
            ]
            for intent, template in scenarios:
                if intents and intent not in intents:
                    continue
                record = {"intent": intent, "passed": False}
                try:
                    collection = await request(
                        "POST",
                        f"/spaces/{space}/collections",
                        {"name": f"验收-{intent}"},
                    )
                    cases = []
                    if intent != "CASE_GENERATE":
                        for index in range(2):
                            cases.append(
                                await request(
                                    "POST",
                                    f"/collections/{collection['id']}/test-cases",
                                    {
                                        "title": f"有效密码登录{index + 1}",
                                        "module": "登录",
                                        "priority": "P1",
                                        "preconditions": ["存在有效账号，用户未登录"],
                                        "steps": [
                                            {
                                                "action": "提交有效账号和正确密码",
                                                "expected": "登录成功并建立会话",
                                            }
                                        ],
                                    },
                                )
                            )
                    conversation = await request(
                        "POST",
                        "/conversations",
                        {"space_id": space, "collection_id": collection["id"]},
                    )
                    cid = conversation["id"]
                    prompt = template.format(
                        case_key=cases[0]["case_key"] if cases else ""
                    )
                    record.update(prompt=prompt, conversation_id=cid)
                    turn = await request(
                        "POST", f"/conversations/{cid}/messages", {"content": prompt}
                    )
                    record["actual_intent"] = turn["intent"]
                    assert turn["intent"] == intent, turn["intent"]
                    if turn["user_message"]["status"] == "awaiting_intent":
                        turn = await request(
                            "POST",
                            f"/conversation-messages/{turn['user_message']['id']}/confirm-intent",
                            {"intent": intent},
                        )
                    if intent == "CASE_MODIFY":
                        oid = turn["operation_plan"]["operations"][0]["id"]
                        turn = await request(
                            "POST",
                            f"/conversation-operations/{oid}/resume",
                            {"confirm_modification": True},
                        )
                    action = turn["action"]
                    record["action"] = action["type"]
                    if "job_id" in action:
                        worker = (
                            tasks.draft_test_brief
                            if intent == "CASE_GENERATE"
                            else tasks.rewrite_test_cases_batch
                            if intent == "CASE_MODIFY"
                            else tasks.answer_knowledge_question
                        )
                        result = await asyncio.to_thread(worker.run, action["job_id"])
                        assert "error" not in result, result
                        job = await request(
                            "GET", f"/generation-jobs/{action['job_id']}"
                        )
                        assert job["status"] == "completed", job.get("error_code")
                        record["job_status"] = job["status"]
                    if intent == "CASE_QUERY":
                        assert action["count"] == 2, action
                    elif intent == "CASE_DELETE":
                        proposal = await request(
                            "GET", f"/case-change-sets/{action['change_set_id']}"
                        )
                        assert len(proposal["items"]) == 1
                        assert proposal["items"][0]["ref"] == cases[0]["id"]
                        await request(
                            "POST", f"/case-change-sets/{proposal['id']}/apply", {}
                        )
                    elif intent == "CASE_MODIFY":
                        proposal = await request(
                            "GET", f"/case-change-sets/{result['change_set_id']}"
                        )
                        assert len(proposal["items"]) == 1
                        assert (
                            proposal["items"][0]["proposed_snapshot"]["priority"]
                            == "P0"
                        )
                        assert all(
                            field["field"] == "priority"
                            for field in proposal["items"][0]["field_diff"]
                        )
                        await request(
                            "POST", f"/case-change-sets/{proposal['id']}/apply", {}
                        )
                    elif intent == "CASE_GENERATE":
                        state = await request("GET", f"/conversations/{cid}")
                        brief = state["test_briefs"][-1]
                        points = brief["content"]["planning"]["test_points"]
                        assert len(points) == 2, len(points)
                        turn = await request(
                            "POST",
                            f"/workspaces/{cid}/test-briefs/confirm",
                            {
                                "version": brief["version"],
                                "model_id": "auto",
                                "selected_test_point_ids": [
                                    point["id"] for point in points
                                ],
                            },
                        )
                        result = await asyncio.to_thread(
                            tasks.generate_test_cases.run, turn["action"]["job_id"]
                        )
                        assert "error" not in result, result
                        state = await request("GET", f"/conversations/{cid}")
                        assert len(state["candidates"]) == 2, len(state["candidates"])
                        record["generated_count"] = 2
                    record["passed"] = True
                except Exception as error:
                    record.update(
                        error_type=type(error).__name__, error=str(error)[:800]
                    )
                records.append(record)
                output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
                print(json.dumps(record, ensure_ascii=False), flush=True)
        finally:
            conversations.enqueue_task = original_enqueue
            if account:
                with get_session_factory()() as db:
                    db.execute(
                        delete(Space).where(
                            Space.id == UUID(account["spaces"][0]["id"])
                        )
                    )
                    db.execute(delete(Account).where(Account.id == UUID(account["id"])))
                    db.commit()
    return int(not all(record["passed"] for record in records))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="artifacts/semantic-acceptance/workflows.json"
    )
    parser.add_argument("--intents", nargs="+")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.output, args.intents)))
