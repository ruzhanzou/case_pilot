"""Live model/API/worker journeys. Isolated synthetic data, retained evidence, no mock replies."""

import argparse
import asyncio
import json
import time
import traceback
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

from casepilot_agent import tasks
from casepilot_api import conversations, generation
from casepilot_api.database import get_session_factory
from casepilot_api.main import app
from casepilot_api.models import Account, Space
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete


class Journey:
    def __init__(self, client, record, model):
        self.client, self.record, self.model = client, record, model

    async def req(self, method, path, body=None):
        r = await self.client.request(method, "/api/v1" + path, json=body)
        assert not r.is_error, f"{method} {path}: {r.status_code} {r.text[:1000]}"
        return r.json()

    async def state(self):
        return await self.req("GET", f"/conversations/{self.cid}")

    async def say(self, text, expected, **extra):
        turn = await self.req(
            "POST",
            f"/conversations/{self.cid}/messages",
            {"content": text, "model_id": self.model, **extra},
        )
        print(f"{self.model}: {text[:35]} -> {turn['intent']}", flush=True)
        self.record["turns"].append(
            {"text": text, "expected": expected, "response": turn}
        )
        assert turn["intent"] == expected, f"intent {turn['intent']} != {expected}"
        assert turn["user_message"]["status"] != "awaiting_intent", (
            "unexpected intent clarification"
        )
        return turn

    async def run(self, turn, worker):
        jid = turn["action"].get("job_id")
        assert jid, f"no job: {turn['action']}"
        for attempt in range(2):
            try:
                result = await asyncio.to_thread(worker.run, jid)
            except Exception as error:
                result = {"error": str(error), "error_type": type(error).__name__}
            job = await self.req("GET", f"/generation-jobs/{jid}")
            self.record.setdefault("jobs", []).append(job)
            if job["status"] == "completed" and "error" not in result:
                return result
            if attempt == 0 and job["status"] == "failed":
                # Exercise the public retry API once, retaining the first failure
                # as evidence. Quantity/scope assertions are never retried.
                before = (await self.state())["candidates"]
                self.record.setdefault("explicit_job_retries", []).append(
                    {
                        "job_id": jid,
                        "first_failure": result,
                        "failed_job": job,
                    }
                )
                await self.req("POST", f"/generation-jobs/{jid}/retry")
                assert (await self.state())["candidates"] == before, (
                    "retry altered saved candidates"
                )
                continue
            raise AssertionError(
                f"job {jid} did not complete after bounded retry: {result}"
            )
        raise AssertionError("retry exhausted")

    async def generate(self, expected, selected_count=None, case_count=None):
        state = await self.state()
        brief = state["test_briefs"][-1]
        points = brief["content"]["planning"]["test_points"]
        assert len(points) == expected, f"expected {expected} points, got {len(points)}"
        selected_points = (
            points[:selected_count] if selected_count is not None else points
        )
        expected_candidates = len(selected_points) if case_count is None else case_count
        turn = (
            await self.say("就按当前测试点开始生成用例吧。", "CASE_GENERATE")
            if getattr(self, "natural_brief_confirmation", False) and selected_count is None
            else await self.req(
                "POST",
                f"/workspaces/{self.cid}/test-briefs/confirm",
                {
                    "version": brief["version"],
                    "model_id": self.model,
                    "selected_test_point_ids": [p["id"] for p in selected_points],
                },
            )
        )
        await self.run(turn, tasks.generate_test_cases)
        state = await self.state()
        assert state["test_briefs"][-1]["content"]["planning"]["test_points"] == points, "generation changed confirmed points"
        candidates = state["candidates"]
        assert len(candidates) == expected_candidates, (
            f"expected {expected_candidates} candidates, got {len(candidates)}"
        )
        for c in candidates:
            s = c["snapshot"]
            assert s["steps"] and all(x["action"] and x["expected"] for x in s["steps"])
            assert s["test_point_ids"], "missing traceability"
        assert {p["id"] for p in selected_points} == {
            p for c in candidates for p in c["snapshot"]["test_point_ids"]
        }
        self.record["generated"] = deepcopy(candidates)
        return candidates

    async def rewrite(self, text):
        turn = await self.say(text, "CASE_MODIFY")
        if not turn["action"].get("job_id"):
            oid = turn["operation_plan"]["current_operation_id"]
            turn = await self.req(
                "POST",
                f"/conversation-operations/{oid}/resume",
                {"confirm_modification": True},
            )
        result = await self.run(turn, tasks.rewrite_test_cases_batch)
        change = await self.req("GET", f"/case-change-sets/{result['change_set_id']}")
        self.record.setdefault("changes", []).append(change)
        assert change["status"] == "ready", change["status"]
        assert all(i["quality"]["passed"] for i in change["items"]), (
            "rewrite quality failed"
        )
        return change


async def scenario(kind, model, output, natural_confirmation=False):
    record = {"kind": kind, "model": model, "passed": False, "turns": []}
    started = time.monotonic()
    account = None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        j = Journey(client, record, model)
        j.natural_brief_confirmation = kind == "natural_generate"
        try:
            account = await j.req(
                "POST",
                "/auth/register",
                {
                    "email": f"deep-{uuid4().hex}@casepilot.test",
                    "password": "SyntheticAcceptance123!",
                    "display_name": "Deep dialogue acceptance",
                },
            )
            space = account["spaces"][0]["id"]
            collection = await j.req(
                "POST", f"/spaces/{space}/collections", {"name": "账号系统验收"}
            )
            conv = await j.req(
                "POST",
                "/conversations",
                {
                    "space_id": space,
                    **(
                        {}
                        if kind in {"select", "select_and_generate"}
                        else {"collection_id": collection["id"]}
                    ),
                },
            )
            j.cid = conv["id"]
            if kind == "qa":
                await qa_journey(j, collection)
            elif kind in {"range_expression", "correction_expression", "ambiguous_expression", "ellipsis_expression"}:
                await expression_journey(j, collection, kind)
            elif kind == "ordinal":
                await ordinal_journey(j, collection)
            elif kind == "scope":
                await scope_journey(j, collection)
            elif kind in {"select", "select_and_generate"}:
                source = await j.req(
                    "POST", f"/spaces/{space}/collections", {"name": "账号系统来源"}
                )
                old = await j.req(
                    "POST",
                    f"/collections/{source['id']}/test-cases",
                    {
                        "title": "账号系统正确密码登录",
                        "module": "账号系统",
                        "priority": "P1",
                        "preconditions": ["账号系统存在有效账号，当前未登录"],
                        "steps": [
                            {
                                "action": "在账号系统提交正确账号密码",
                                "expected": "进入首页并建立登录会话",
                            }
                        ],
                    },
                )
                extra = None
                if kind == "select":
                    extra = await j.req(
                        "POST",
                        f"/collections/{source['id']}/test-cases",
                        {
                            "title": "账号系统错误密码登录",
                            "module": "账号系统",
                            "priority": "P1",
                            "preconditions": ["账号系统存在有效账号，当前未登录"],
                            "steps": [
                                {
                                    "action": "在账号系统提交正确账号和错误密码",
                                    "expected": "登录失败且不建立会话",
                                }
                            ],
                        },
                    )
                prompt = (
                    "测试对象是账号系统。选用已有的登录用例组成新集合，先展示资产让我选择，不生成新用例。"
                    if kind == "select"
                    else "测试对象是账号系统。选用已有用例并补充生成，规划两个测试点：正确密码登录成功、错误密码登录失败；总共两条用例。"
                )
                turn = await j.say(
                    prompt,
                    "CASE_GENERATE",
                    generation_strategy=kind,
                    source_collection_ids=[source["id"]],
                )
                if not turn["action"].get("job_id"):
                    oid = turn["operation_plan"]["current_operation_id"]
                    turn = await j.req(
                        "POST",
                        f"/conversation-operations/{oid}/confirm-collection",
                        {"create_collection_name": "账号系统输出"},
                    )
                await j.run(turn, tasks.draft_test_brief)
                state = await j.state()
                brief = state["test_briefs"][-1]
                selection = brief["content"]["asset_selection"]
                assert selection["status"] == "awaiting_confirmation"
                assert {s["case_id"] for s in selection["sources"]} == {
                    old["id"],
                    *([extra["id"]] if extra else []),
                }
                record["selected_from"] = deepcopy(selection["sources"])
                turn = (
                    await j.say("就用正确密码登录那条，其他不要。确认选这条。", "CASE_GENERATE")
                    if natural_confirmation else await j.req(
                        "POST",
                        f"/workspaces/{j.cid}/generation-assets/confirm",
                        {"version": brief["version"], "case_ids": [old["id"]]},
                    )
                )
                if kind == "select":
                    assert turn["action"]["type"] == "assets_selected"
                    state = await j.state()
                    actual = await j.req(
                        "GET", f"/collections/{state['collection_id']}/test-cases"
                    )
                    assert [c["id"] for c in actual] == [old["id"]]
                    assert not state["candidates"]
                    untouched = await j.req("GET", f"/test-cases/{extra['id']}")
                    assert (
                        untouched["current_revision_id"] == extra["current_revision_id"]
                    )
                else:
                    await j.run(turn, tasks.draft_test_brief)
                    await j.generate(2)
                unchanged = await j.req("GET", f"/test-cases/{old['id']}")
                assert (
                    unchanged["steps"] == old["steps"]
                    and unchanged["current_revision_id"] == old["current_revision_id"]
                )
            else:
                count = 2 if kind in {"expression_generate", "append", "colloquial_planning", "colloquial", "dialogue", "planning", "retry", "subset", "quantities", "candidate", "allocation_retry", "allocation_clarification", "subset_quantities"} else 1
                prompt = (
                    "为账号系统规划两个测试点并生成两条用例：正确密码登录成功、错误密码登录失败；仅覆盖这两种场景。"
                    if count == 2
                    else "为账号系统规划一个测试点并生成一条用例：有效账号使用正确密码登录成功，进入首页并建立会话。仅这一个场景。"
                )
                if kind in {"quantities", "allocation_retry", "subset_quantities", "expression_generate"}:
                    prompt = "为账号系统规划两个测试点：正确密码登录成功、错误密码登录失败。基于这两个测试点总共生成四条用例，每个测试点分别覆盖普通账号、管理员账号，两种账号均适用相同登录规则。测试点严格两个，用例严格四条。"
                if kind == "expression_generate":
                    prompt = "给账号系统做登录用例。密码对了能进去、密码错了进不去，就这俩测试点，别拆更多。每个点普通账号和管理员账号各来一条，两种账号用同一套登录规则。不是每点四条，是加起来四条。"
                if kind == "allocation_clarification":
                    prompt = "为账号系统规划两个测试点：正确密码登录成功、错误密码登录失败。后续严格生成四条用例，每个点需要覆盖两种账号类型；具体账号类型尚未确定，稍后补充。请不要自行假设账号类型。"
                if kind == "quantities_fewer":
                    count = 4
                    prompt = "为账号系统严格规划四个测试点：正确密码登录进入首页、成功登录建立会话、错误密码登录被拒绝、失败登录不建立会话。严格生成两条用例：一条正确密码成功登录同时验证首页和会话，另一条错误密码失败登录同时验证拒绝和未建立会话；四个点均须覆盖。"
                turn = await j.say(
                    prompt, "CASE_GENERATE", generation_strategy="generate"
                )
                await j.run(turn, tasks.draft_test_brief)
                if kind in {"dialogue", "planning", "colloquial_planning"}:
                    first = (await j.state())["test_briefs"][-1]["content"]["planning"][
                        "test_points"
                    ]
                    turn = await j.say(
                        "在现有测试规划上增加一个测试点：用户登录后点击退出，返回登录页，会话失效。原有两个测试点保持不变。",
                        "CASE_GENERATE",
                    )
                    await j.run(turn, tasks.draft_test_brief)
                    points = (await j.state())["test_briefs"][-1]["content"][
                        "planning"
                    ]["test_points"]
                    assert len(points) == 3, f"addition count {len(points)}"
                    assert all(p in points for p in first), "existing planning changed"
                    added = next(
                        p for p in points if p["id"] not in {x["id"] for x in first}
                    )
                    if kind in {"planning", "colloquial_planning"}:
                        turn = await j.say(
                            ("刚加的退出那个点改一下：退出后再用原来的会话访问受保护页面，应返回登录页且会话失效。别加点，原来两个不动。"
                             if kind == "colloquial_planning" else
                             f"仅修改测试规划中的测试点 {added['id']}：改为用户退出登录后，"
                             "用退出前的同一会话访问受保护页面，返回登录页且会话失效。"
                             "仅替换这一个测试点，不新增测试点，其他两个测试点保持不变。"),
                            "CASE_GENERATE",
                        )
                        await j.run(turn, tasks.draft_test_brief)
                        points = (await j.state())["test_briefs"][-1]["content"][
                            "planning"
                        ]["test_points"]
                        assert len(points) == 3 and all(p in points for p in first), (
                            "point edit drift"
                        )
                        added = next(
                            p for p in points if p["id"] not in {x["id"] for x in first}
                        )
                        record["edited_point"] = added
                    turn = await j.say(
                        ("算了，退出的那个点先不要了，就留最开始的两个。"
                         if kind == "colloquial_planning" else
                         f"从测试规划中删除测试点 {added['id']}（退出登录），其他两个测试点保持不变。"),
                        "CASE_GENERATE",
                    )
                    await j.run(turn, tasks.draft_test_brief)
                    points = (await j.state())["test_briefs"][-1]["content"][
                        "planning"
                    ]["test_points"]
                    assert points == first, "planning deletion changed unrelated points"
                candidates = (
                    await allocated_clarification(j)
                    if kind == "allocation_clarification"
                    else await allocated_retry(j)
                    if kind == "allocation_retry"
                    else await partial_retry(j)
                    if kind == "retry"
                    else await j.generate(
                        count, selected_count=1 if kind in {"subset", "subset_quantities"} else None,
                        case_count=4 if kind in {"quantities", "expression_generate"} else 2 if kind in {"quantities_fewer", "subset_quantities"} else None
                    )
                )
                if kind == "append":
                    original_cases = await j.req("POST", f"/workspaces/{j.cid}/candidates/commit",
                        {"candidate_ids": [c["id"] for c in candidates]})
                    assert len(original_cases) == 2
                    turn = await j.say(
                        "原来的两条留着，再补两条退出登录用例，集合一共四条就够。新增两个测试点："
                        "退出后回到登录页；退出后原会话访问受保护页面被拒绝。每个新点一条用例，别重做登录的两条。",
                        "CASE_GENERATE")
                    await j.run(turn, tasks.draft_test_brief)
                    added = await j.generate(2, case_count=2)
                    assert not {c["id"] for c in candidates} & {c["id"] for c in added}
                    for old in original_cases:
                        assert await j.req("GET", f"/test-cases/{old['id']}") == old
                    await j.req("POST", f"/workspaces/{j.cid}/candidates/commit",
                        {"candidate_ids": [c["id"] for c in added]})
                    final_cases = await j.req("GET", f"/collections/{collection['id']}/test-cases")
                    assert len(final_cases) == 4, "append confused final total with new output count"
                    record["final_collection"] = final_cases
                if kind == "colloquial":
                    await colloquial_journey(j, candidates)
                if kind in {"dialogue", "candidate"}:
                    base = {c["ref"]: deepcopy(c["snapshot"]) for c in candidates}
                    chosen, other = candidates
                    ref = chosen["ref"]
                    priority = "P2" if base[ref]["priority"] != "P2" else "P0"
                    change1 = await j.rewrite(
                        f"仅将候选用例 {ref} 的优先级改为{priority}，其他字段保持不变。"
                    )
                    assert len(change1["items"]) == 1
                    s1 = change1["items"][0]["proposed_snapshot"]
                    assert s1 == {**base[ref], "priority": priority}, (
                        "priority-only edit changed other fields"
                    )
                    change2 = await j.rewrite(
                        f"继续修改候选用例 {ref}，仅将标题改为“账号系统登录验收修订版”，保留上一轮{priority}和所有其他字段。"
                    )
                    assert len(change2["items"]) == 1
                    s2 = change2["items"][0]["proposed_snapshot"]
                    assert s2 == {**s1, "title": "账号系统登录验收修订版"}, (
                        "second turn lost previous edit"
                    )
                    await j.req("POST", f"/case-change-sets/{change2['id']}/apply", {})
                    state = await j.state()
                    now = {c["ref"]: c["snapshot"] for c in state["candidates"]}
                    assert now[ref] == s2 and now[other["ref"]] == base[other["ref"]]
                    before_chat = deepcopy(state["candidates"])
                    turn = await j.say(
                        "先不要修改或生成任何用例。解释一下等价类划分是什么。",
                        "KNOWLEDGE_QA",
                    )
                    assert turn["action"].get("job_id"), "QA failed to start answer job"
                    await j.run(turn, tasks.answer_knowledge_question)
                    assert (await j.state())["candidates"] == before_chat, (
                        "QA mutated candidates"
                    )
                    formal = await j.req(
                        "POST",
                        f"/workspaces/{j.cid}/candidates/commit",
                        {"candidate_ids": [c["id"] for c in candidates]},
                    )
                    record["committed"] = formal
                    assert len(formal) == 2
                    assert any(
                        c["title"] == s2["title"]
                        and c["priority"] == priority
                        and [
                            {"action": x["action"], "expected": x["expected"]}
                            for x in c["steps"]
                        ]
                        == s2["steps"]
                        for c in formal
                    )
                    turn = await j.say("查询当前集合全部用例", "CASE_QUERY")
                    assert turn["action"]["count"] == 2
                    record["committed"] = formal
            record["final_state"] = await j.state()
            record["passed"] = True
        except Exception as exc:
            record.update(
                error_type=type(exc).__name__,
                error=str(exc)[:3000],
                traceback=traceback.format_exc(),
            )
            if hasattr(j, "cid"):
                record["final_state"] = await j.state()
        finally:
            if account:
                with get_session_factory()() as db:
                    from sqlalchemy import select
                    from casepilot_api.models import GenerationJob, GenerationJobStage
                    jobs = select(GenerationJob.id).where(GenerationJob.account_id == UUID(account["id"]))
                    stages = db.scalars(select(GenerationJobStage).where(
                        GenerationJobStage.generation_job_id.in_(jobs),
                        GenerationJobStage.stage.in_(["output_quantity.interpreted", "test_case.allocated", "test_case.allocation_reviewed"])
                    ).order_by(GenerationJobStage.created_at)).all()
                    record["allocation_diagnostics"] = [{"stage": st.stage, "status": st.status,
                        "attempt": st.attempt, "input": st.input_payload, "output": st.output_payload} for st in stages]
                    db.execute(
                        delete(Space).where(
                            Space.id == UUID(account["spaces"][0]["id"])
                        )
                    )
                    db.execute(delete(Account).where(Account.id == UUID(account["id"])))
                    db.commit()
                record["cleaned_up"] = True
    record["seconds"] = round(time.monotonic() - started, 2)
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{kind}-{model}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                k: record[k]
                for k in ["kind", "model", "passed", "seconds", "error"]
                if k in record
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return record


async def allocated_clarification(j):
    brief = (await j.state())["test_briefs"][-1]
    points = brief["content"]["planning"]["test_points"]
    assert len(points) == 2
    turn = await j.req("POST", f"/workspaces/{j.cid}/test-briefs/confirm", {
        "version": brief["version"], "model_id": j.model,
        "selected_test_point_ids": [p["id"] for p in points]})
    jid = turn["action"]["job_id"]
    await asyncio.to_thread(tasks.generate_test_cases.run, jid)
    job = await j.req("GET", f"/generation-jobs/{jid}")
    j.record["clarification_job"] = job
    assert job["status"] == "awaiting_input", job["status"]
    assert not (await j.state())["candidates"]
    assert any(q["id"] == "case_allocation_conditions" for q in job["questions"])
    await j.req("POST", f"/generation-jobs/{jid}/answers", {
        "answers": [{"question_id": "case_allocation_conditions",
                     "answer": "两种账号类型是普通账号、管理员账号，均遵循相同登录规则。"}]})
    await j.run(turn, tasks.generate_test_cases)
    state = await j.state()
    candidates = state["candidates"]
    assert len(candidates) == 4
    assert state["test_briefs"][-1]["content"]["planning"]["test_points"] == points
    assert {p["id"] for p in points} == {p for c in candidates for p in c["snapshot"]["test_point_ids"]}
    j.record["generated"] = deepcopy(candidates)
    return candidates


async def allocated_retry(j):
    from casepilot_agent import compact_generation
    from casepilot_agent.compact_generation import StageContractError
    state = await j.state()
    brief = state["test_briefs"][-1]
    points = brief["content"]["planning"]["test_points"]
    assert len(points) == 2
    turn = await j.req("POST", f"/workspaces/{j.cid}/test-briefs/confirm", {
        "version": brief["version"], "model_id": j.model,
        "selected_test_point_ids": [p["id"] for p in points]})
    jid = turn["action"]["job_id"]
    factory = tasks.create_provider
    old_size, old_concurrency = compact_generation.BATCH_SIZE, compact_generation.BATCH_CONCURRENCY
    calls, failures, allocation_calls = [], [], []
    injecting = True
    class FaultProvider:
        def __init__(self, inner): self.inner = inner
        def __getattr__(self, name): return getattr(self.inner, name)
        def complete(self, **kwargs):
            if kwargs["stage"] == "test_case.allocated":
                allocation_calls.append(kwargs["payload"])
            if kwargs["stage"] == "test_case.generated":
                slots = kwargs["payload"]["batch_slots"]
                calls.extend(slots)
                if injecting and 4 in slots:
                    failures.append(4)
                    raise StageContractError("acceptance_allocated_slot_failure")
            return self.inner.complete(**kwargs)
    compact_generation.BATCH_SIZE = compact_generation.BATCH_CONCURRENCY = 1
    try:
        tasks.create_provider = lambda *a: FaultProvider(factory(*a))
        try:
            await asyncio.to_thread(tasks.generate_test_cases.run, jid)
        except Exception as error:
            j.record["injected_failure"] = {"type": type(error).__name__, "error":str(error)}
        failed = await j.req("GET", f"/generation-jobs/{jid}")
        j.record["failed_allocation_job"] = failed
        assert failed["status"] == "failed"
        assert len(failures) == 3
        assert not (await j.state())["candidates"], "partial allocated set became adoptable"
        j.record["failed_allocation_job"] = failed
        first_calls = list(calls)
        first_allocation_count = len(allocation_calls)
        injecting = False
        await j.req("POST", f"/generation-jobs/{jid}/retry")
        duplicate = await j.client.post(f"/api/v1/generation-jobs/{jid}/retry")
        assert duplicate.status_code == 409
        await j.run(turn, tasks.generate_test_cases)
        assert set(calls[len(first_calls):]) == {4}, "retry regenerated successful slots"
        assert len(allocation_calls) == first_allocation_count, "retry reallocated scenarios"
    finally:
        tasks.create_provider = factory
        compact_generation.BATCH_SIZE, compact_generation.BATCH_CONCURRENCY = old_size, old_concurrency
    job = await j.req("GET", f"/generation-jobs/{jid}")
    stages = job.get("stages", [])
    # Inspect persisted stage records: successful calls remain single checkpoints.
    j.record["allocation_retry"] = {"failed_slots": failures, "first_execution_slots": first_calls,
                                    "retry_slots": calls[len(first_calls):],
                                    "final_stage_records": stages}
    state = await j.state()
    cases = state["candidates"]
    assert len(cases) == 4 and len({c["ref"] for c in cases}) == 4
    assert state["test_briefs"][-1]["content"]["planning"]["test_points"] == points
    assert {p["id"] for p in points} == {p for c in cases for p in c["snapshot"]["test_point_ids"]}
    j.record["generated"] = deepcopy(cases)
    return cases


async def partial_retry(j):
    """Inject one exhausted slot failure; all returned case content is generated by real models."""
    from casepilot_agent import compact_generation
    from casepilot_agent.compact_generation import StageContractError
    from casepilot_api.models import GenerationJob

    brief = (await j.state())["test_briefs"][-1]
    points = brief["content"]["planning"]["test_points"]
    assert len(points) == 2
    missing = points[1]["id"]
    turn = await j.req(
        "POST",
        f"/workspaces/{j.cid}/test-briefs/confirm",
        {
            "version": brief["version"],
            "model_id": j.model,
            "selected_test_point_ids": [p["id"] for p in points],
        },
    )
    original_factory = tasks.create_provider
    batch_size, concurrency = (
        compact_generation.BATCH_SIZE,
        compact_generation.BATCH_CONCURRENCY,
    )
    failures = []

    class FaultProvider:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, key):
            return getattr(self.inner, key)

        def complete(self, **kwargs):
            if kwargs["stage"] == "test_case.generated" and any(
                p["point"]["id"] == missing for p in kwargs["payload"].get("points", [])
            ):
                failures.append(missing)
                raise StageContractError("acceptance_injected_slot_failure")
            return self.inner.complete(**kwargs)

    try:
        compact_generation.BATCH_SIZE = compact_generation.BATCH_CONCURRENCY = 1
        tasks.create_provider = lambda *a: FaultProvider(original_factory(*a))
        await j.run(turn, tasks.generate_test_cases)
    finally:
        tasks.create_provider = original_factory
        compact_generation.BATCH_SIZE, compact_generation.BATCH_CONCURRENCY = (
            batch_size,
            concurrency,
        )
    state = await j.state()
    kept = deepcopy(state["candidates"])
    assert len(kept) == 1 and missing not in kept[0]["snapshot"]["test_point_ids"], (
        "partial result wrong"
    )
    j.record["fault_injection"] = {
        "point_id": missing,
        "attempts": len(failures),
        "retained": kept,
    }
    retry = await j.say(
        "重试未完成的生成，只补齐失败的测试点，已经成功的用例保持不变。",
        "CASE_GENERATE",
    )
    with get_session_factory()() as db:
        job = db.get(GenerationJob, UUID(retry["action"]["job_id"]))
        assert [
            p["id"] for p in job.input_payload["confirmed_plan"]["test_points"]
        ] == [missing]
        j.record["retry_point_ids"] = [
            p["id"] for p in job.input_payload["confirmed_plan"]["test_points"]
        ]
    duplicate = await j.client.post(
        "/api/v1/conversations/" + j.cid + "/messages", json={"content": "重试"}
    )
    assert duplicate.status_code == 409, "duplicate retry was not blocked"
    await j.run(retry, tasks.generate_test_cases)
    final = (await j.state())["candidates"]
    assert (
        len(final) == 2
        and next(c for c in final if c["id"] == kept[0]["id"]) == kept[0]
    )
    assert {p["id"] for p in points} == {
        pid for c in final for pid in c["snapshot"]["test_point_ids"]
    }
    j.record["generated"] = final
    return final


async def scope_journey(j, collection):
    """Real query references, cumulative modifications, QA interruption, and formal persistence."""
    cases = []
    for title, module in [
        ("正确密码登录", "登录"),
        ("错误密码登录", "登录"),
        ("订单提交", "订单"),
    ]:
        cases.append(
            await j.req(
                "POST",
                f"/collections/{collection['id']}/test-cases",
                {
                    "title": title,
                    "module": module,
                    "priority": "P1",
                    "preconditions": ["验收环境已准备"],
                    "steps": [
                        {"action": f"执行{title}", "expected": f"{title}结果可核对"}
                    ],
                },
            )
        )
    query = await j.say("查询当前集合登录模块的全部用例，不包括订单模块", "CASE_QUERY")
    assert query["action"]["count"] == 2
    mismatch = await j.say(
        "仅将刚才查到的这三条用例优先级改为P2，其他字段不变。", "CASE_MODIFY"
    )
    assert not mismatch["action"].get("job_id"), "count mismatch dispatched a mutation"
    assert not mismatch['assistant_message']['metadata'].get('modification_confirmation'), (
        'count mismatch silently offered a smaller mutation scope'
    )
    for case in cases:
        unchanged = await j.req("GET", f"/test-cases/{case['id']}")
        assert unchanged == case, "count mismatch changed an asset"
    first = await j.rewrite(
        "纠正刚才数量，是查到的这两条登录用例。仅将这两条用例优先级改为P2，其他字段保持不变。"
    )
    items = {i["ref"]: i for i in first["items"]}
    assert set(items) == {c["id"] for c in cases[:2]}, (
        "query reference selected wrong cases"
    )
    for item in items.values():
        assert item["proposed_snapshot"]["priority"] == "P2"
        assert {d["field"] for d in item["field_diff"]} == {"priority"}
    second = await j.rewrite(
        f"继续修改用例 {cases[0]['case_key']}，仅将标题改为“登录验收指定用例”，保留上一轮优先级和其他内容。"
    )
    latest = {i["ref"]: i for i in second["items"]}
    assert set(latest) == set(items), "pending sibling removed"
    assert latest[cases[0]["id"]]["proposed_snapshot"] == {
        **items[cases[0]["id"]]["proposed_snapshot"],
        "title": "登录验收指定用例",
    }
    assert (
        latest[cases[1]["id"]]["proposed_snapshot"]
        == items[cases[1]["id"]]["proposed_snapshot"]
    )
    qa = await j.say("先不修改用例。解释一下等价类划分，并举一个例子。", "KNOWLEDGE_QA")
    assert qa["action"].get("job_id"), "QA failed to start answer job"
    await j.run(qa, tasks.answer_knowledge_question)
    after_qa = await j.req("GET", f"/case-change-sets/{second['id']}")
    assert after_qa["items"] == second["items"], "QA altered pending proposal"
    await j.req("POST", f"/case-change-sets/{second['id']}/apply", {})
    actual = [await j.req("GET", f"/test-cases/{c['id']}") for c in cases]
    for index, case in enumerate(actual):
        assert case["steps"] == cases[index]["steps"]
        assert case["preconditions"] == cases[index]["preconditions"]
        assert case["module"] == cases[index]["module"]
        assert case["title"] == (
            "登录验收指定用例" if index == 0 else cases[index]["title"]
        )
        assert case["priority"] == ("P2" if index < 2 else "P1")
    assert actual[2]["current_revision_id"] == cases[2]["current_revision_id"], (
        "unselected case rewritten"
    )
    j.record["formal_before"] = cases
    j.record["formal_after"] = actual


async def qa_journey(j, collection):
    original = await j.req(
        "POST",
        f"/collections/{collection['id']}/test-cases",
        {
            "title": "问答期间应保持不变的登录用例",
            "module": "登录",
            "priority": "P1",
            "steps": [{"action": "输入正确密码", "expected": "登录成功"}],
        },
    )
    for text in [
        "解释一下等价类划分，用登录密码长度为8到20个字符举例。只回答，不生成或修改用例。",
        "沿用刚才的长度规则，边界值应该选哪些？只解释，不保存到用例。",
        "把上一条回答简要翻译成英文，不改动任何用例。",
    ]:
        turn = await j.say(text, "KNOWLEDGE_QA")
        await j.run(turn, tasks.answer_knowledge_question)
        state = await j.state()
        assert not state["test_briefs"] and not state["candidates"]
        assert all(o["intent"] == "KNOWLEDGE_QA" for o in state["operation_history"])
        actual = await j.req("GET", f"/test-cases/{original['id']}")
        assert actual == original, "QA changed formal case"
    j.record["qa_answers"] = [
        m["content"] for m in (await j.state())["messages"] if m["role"] == "assistant"
    ]


async def expression_journey(j, collection, kind):
    cases = []
    for title in ["正确密码登录", "错误密码登录", "退出登录"]:
        cases.append(await j.req("POST", f"/collections/{collection['id']}/test-cases", {
            "title": title, "module": "登录", "priority": "P1",
            "preconditions": ["账号已存在"],
            "steps": [{"action": f"执行{title}", "expected": "结果符合登录规则"}],
        }))
    baseline = {c["id"]: deepcopy(c) for c in cases}
    query = await j.say("列出这个集合里所有用例。", "CASE_QUERY")
    ordered = query["assistant_message"]["target_case_ids"]
    assert len(ordered) == 3
    j.record["visible_order"] = ordered
    if kind == "range_expression":
        first = await j.rewrite("头一条别动，剩下那两条的优先级都调成P2，其他字段照旧。")
        expected_ids = set(ordered[1:])
        assert {i["ref"] for i in first["items"]} == expected_ids, "exclusion/colloquial ordinal scope wrong"
        change = await j.rewrite("刚才说错了，不是P2，是P0。就那两条，别扩大范围。")
    elif kind == "correction_expression":
        first = await j.rewrite("错误密码登录那条，优先级先调成P0，别改步骤。")
        expected_ids = {cases[1]["id"]}
        assert {i["ref"] for i in first["items"]} == expected_ids
        change = await j.rewrite("不对，我要的是P2，不是P0；标题和步骤都照旧。")
    else:
        vague = await j.say("登录那条，优先级调成P0。", "CASE_MODIFY")
        assert not vague["action"].get("job_id"), "ambiguous singular target dispatched rewrite"
        assert not vague["assistant_message"]["metadata"].get("modification_confirmation"), "ambiguous target offered guessed preview"
        for cid, old in baseline.items():
            assert await j.req("GET", f"/test-cases/{cid}") == old
        change = await j.rewrite(
            "密码错了进不去的那个。" if kind == "ellipsis_expression"
            else "我指的是错误密码登录失败的那条，优先级P0，别的不用改。")
        expected_ids = {cases[1]["id"]}
    assert {i["ref"] for i in change["items"]} == expected_ids, "correction lost target scope"
    priority = "P2" if kind == "correction_expression" else "P0"
    for item in change["items"]:
        assert item["proposed_snapshot"]["priority"] == priority
        assert {d["field"] for d in item["field_diff"]} == {"priority"}, "correction changed unrelated field"
    await j.req("POST", f"/case-change-sets/{change['id']}/apply", {})
    for cid, old in baseline.items():
        actual = await j.req("GET", f"/test-cases/{cid}")
        if cid not in expected_ids:
            assert actual == old, "unselected formal case changed"
        else:
            assert actual["priority"] == priority
            for field in ["title", "module", "preconditions", "steps"]:
                assert actual[field] == old[field], f"unrequested field {field} changed"
    j.record["expected_target_ids"] = sorted(expected_ids)


async def ordinal_journey(j, collection):
    cases = []
    for title in ["正确密码登录", "错误密码登录", "退出登录"]:
        cases.append(await j.req("POST", f"/collections/{collection['id']}/test-cases", {
            "title": title, "module": "登录", "priority": "P1",
            "preconditions": ["账号已存在"],
            "steps": [{"action": f"执行{title}", "expected": "结果符合登录规则"}],
        }))
    baseline = {c["id"]: c for c in cases}
    query = await j.say("把这个集合的用例列一下。", "CASE_QUERY")
    ordered = query["assistant_message"]["target_case_ids"]
    assert len(ordered) == 3
    j.record["visible_order"] = ordered
    change = await j.rewrite("刚列出来的第二条，优先级改成P0，其余都别动。")
    assert len(change["items"]) == 1
    item = change["items"][0]
    assert item["ref"] == ordered[1], "ordinal did not match displayed query order"
    assert {d["field"] for d in item["field_diff"]} == {"priority"}
    assert item["proposed_snapshot"]["priority"] == "P0"
    await j.req("POST", f"/case-change-sets/{change['id']}/apply", {})
    for cid, old in baseline.items():
        current = await j.req("GET", f"/test-cases/{cid}")
        if cid != ordered[1]:
            assert current == old, "ordinal edit changed unrelated case"
        else:
            assert current["priority"] == "P0"
            for field in ["title", "module", "preconditions", "steps"]:
                assert current[field] == old[field]


async def colloquial_journey(j, candidates):
    """Check referential language against exact snapshots, without explicit IDs."""
    baseline = {c["ref"]: deepcopy(c["snapshot"]) for c in candidates}
    # Ground the first reference in a unique user-visible title; subsequent turns
    # intentionally omit identifiers and depend on dialogue memory.
    chosen, other = candidates
    title = chosen["snapshot"]["title"]
    priority = "P2" if chosen["snapshot"]["priority"] != "P2" else "P0"
    first = await j.rewrite(f"把‘{title}’那条的优先级调成{priority}，别的都别动。")
    assert len(first["items"]) == 1, "title reference selected wrong number"
    expected = {**baseline[chosen["ref"]], "priority": priority}
    assert first["items"][0]["proposed_snapshot"] == expected, "title reference selected or changed wrong case"
    second = await j.rewrite("刚才那条，标题改成‘登录检查’，其他保持刚才的结果。")
    assert len(second["items"]) == 1, "anaphora selected wrong number"
    expected = {**expected, "title": "登录检查"}
    assert second["items"][0]["proposed_snapshot"] == expected, "anaphora lost previous edit or selected wrong case"
    await j.req("POST", f"/case-change-sets/{second['id']}/apply", {})
    now = {c["ref"]: c["snapshot"] for c in (await j.state())["candidates"]}
    assert now == {**baseline, chosen["ref"]: expected}, "apply changed unrelated candidate"
    before = deepcopy((await j.state())["candidates"])
    qa = await j.say("先别改。如果把它改成P0，会有什么影响？只解释一下。", "KNOWLEDGE_QA")
    await j.run(qa, tasks.answer_knowledge_question)
    assert (await j.state())["candidates"] == before, "hypothetical discussion mutated candidates"
    other_priority = "P2" if baseline[other["ref"]]["priority"] != "P2" else "P0"
    third = await j.rewrite(f"换另一条，标题叫‘{other['snapshot']['title']}’的那条，只把优先级改成{other_priority}，刚才那条别动。")
    assert len(third["items"]) == 1
    assert third["items"][0]["proposed_snapshot"] == {**baseline[other["ref"]], "priority": other_priority}, "corrected target retained stale scope"
    await j.req("POST", f"/case-change-sets/{third['id']}/apply", {})
    final = {c["ref"]: c["snapshot"] for c in (await j.state())["candidates"]}
    assert final == {chosen["ref"]: expected, other["ref"]: {**baseline[other["ref"]], "priority": other_priority}}


async def main(args):
    assert (
        conversations.settings.agent_provider != "mock"
        and tasks.settings.provider != "mock"
    )
    original = conversations.enqueue_task
    original_generation_enqueue = generation.enqueue_task
    conversations.enqueue_task = lambda *a, **kw: None
    generation.enqueue_task = lambda *a, **kw: None
    try:
        models = args.models or conversations.settings.available_agent_models
        specs = (
            [("model", m) for m in models]
            if args.kind == "models"
            else [(args.kind, m) for m in models]
        )
        semaphore = asyncio.Semaphore(args.concurrency)

        async def bounded(kind, model):
            async with semaphore:
                return await scenario(kind, model, Path(args.output), args.natural_confirmation)

        records = await asyncio.gather(*(bounded(k, m) for k, m in specs))
        return int(not all(r["passed"] for r in records))
    finally:
        conversations.enqueue_task = original
        generation.enqueue_task = original_generation_enqueue


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--kind",
        choices=[
            "models",
            "natural_generate",
            "dialogue",
            "candidate",
            "colloquial",
            "append",
            "planning",
            "colloquial_planning",
            "retry",
            "scope",
            "ordinal",
            "range_expression",
            "correction_expression",
            "ambiguous_expression",
            "ellipsis_expression",
            "subset",
            "subset_quantities",
            "quantities",
            "expression_generate",
            "quantities_fewer",
            "allocation_retry",
            "allocation_clarification",
            "qa",
            "select",
            "select_and_generate",
        ],
        default="models",
    )
    p.add_argument("--models", nargs="+")
    p.add_argument("--natural-confirmation", action="store_true")
    p.add_argument("--concurrency", type=int, choices=range(1, 4), default=1)
    p.add_argument("--output", default="artifacts/deep-dialogue-acceptance")
    raise SystemExit(asyncio.run(main(p.parse_args())))
