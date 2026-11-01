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
