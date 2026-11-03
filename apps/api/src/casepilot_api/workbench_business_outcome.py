"""Server evidence, separate from the completion of a conversational answer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BusinessOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    activity: Literal[
        "not_executed", "context_observed", "read_completed", "workspace_updated",
        "planned", "preparation_verified",
    ]
    plan_coverage: Literal["not_planned", "pending_steps", "steps_verified"] = "not_planned"
    run_id: str
    receipt_ids: list[str]
    # This contract records tool effects, never a model's claim of formal application.
    authority: Literal["server_tool_records"] = "server_tool_records"


def business_outcome(run_id, tool_results, completion=None):
    """Only call with this segment's successful, server-created tool records."""
    records = [item for item in tool_results if item.get("receipt")]
    activity = "not_executed"
    if any(item["receipt"]["effect"] == "prepare" for item in records):
        activity = "preparation_verified"
    elif any(item["tool"] in {"select_assets", "select_collection", "update_selection"}
             for item in records):
        activity = "workspace_updated"
    elif any(item["receipt"]["effect"] == "read" and item["tool"] not in {
        "get_workspace_context", "read_attachment_evidence", "load_workbench_skill",
    } for item in records):
        activity = "read_completed"
    elif any(item["receipt"]["effect"] == "plan" for item in records):
        activity = "planned"
    elif records:
        activity = "context_observed"
    completion = completion or {}
    plan_coverage = "not_planned"
    if completion.get("goal_plan_valid") is True:
        plan_coverage = ("steps_verified" if completion.get("completion_code") == "goal_satisfied"
                         else "pending_steps")
    return BusinessOutcome(activity=activity, plan_coverage=plan_coverage, run_id=str(run_id),
                           receipt_ids=[item["receipt"]["id"] for item in records])


def unexecuted_answer_notice(result, outcome):
    """Do not classify prose or force writes; label an exhausted execution check."""
    if (result.status == "completed" and outcome.activity == "read_completed"
            and outcome.plan_coverage == "not_planned"):
        return "读取记录：已核验本次读取；未执行其他操作，也未据此认定其他目标已完成。\n\n"
    if (result.status == "completed"
            and outcome.activity in {"not_executed", "context_observed", "planned"}
            and any(event.get("error_code") == "agent_execution_unverified"
                    or event.get("type") == "tool_rejected"
                    for event in result.events)):
        return "执行记录：本轮未启动任务或生成差异。以下仅为对话答复，不是执行成功凭据。\n\n"
    return ""


def present_final(result, outcome):
    """Preserve informational prose; execution authority lives in a separate section."""
    return result.final.model_dump(mode="json") if result.final is not None else None


def answer_sections(run_id, tool_results, status, *, receipt_namespace=None):
    """Server-only projection. Model prose/claimed receipts cannot create actions.

    Read results remain available with their exact successful current-segment receipt.
    No preparation receipt establishes formal application or the whole goal's completion.
    """
    namespace = receipt_namespace or str(run_id)
    actions = []
    reads = []
    for item in tool_results:
        receipt = item.get("receipt")
        if not receipt or not receipt["id"].startswith(namespace + ":"):
            continue
        data = item["result"]
        effect = receipt["effect"]
        state = "read_completed" if effect == "read" else "plan_recorded"
        if effect == "prepare":
            state = ("workspace_updated" if item["tool"] in {
                "select_assets", "select_collection", "update_selection",
            } else "cancelled" if data.get("status") == "cancelled" else
                     "failed" if data.get("status") == "failed" else
                     "queued" if data.get("status") in {"queued", "running"} else
                     "awaiting_review" if data.get("requires_human_review") is True else
                     "preparation_recorded")
        actions.append({"receipt_id": receipt["id"], "tool": receipt["tool"],
                        "effect": effect, "state": state})
        if effect == "read" and item["tool"] in {
            "query_assets", "query_candidates", "query_uploaded_cases", "query_collections",
        }:
            # This already-authorized, bounded result is business data, not a claim.
            key = "collections" if item["tool"] == "query_collections" else "cases"
            rows = data.get(key)
            if isinstance(rows, list):
                reads.append({"receipt_id": receipt["id"], "kind": key, "rows": rows,
                              "truncated": data.get("truncated") is True,
                              "has_more": data.get("has_more") is True})
    return {"version": 1, "authority": "server_tool_records", "run_id": str(run_id),
            "receipt_namespace": namespace,
            "information_authority": "unverified_dialogue", "actions": actions,
            "read_results": reads}
