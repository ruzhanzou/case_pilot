"""Built-in, versioned workflow guidance; loading never executes a business action."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

SkillId = Literal["inspect_reuse", "plan_test_points", "generate_cases", "rewrite_cases"]


class SkillSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: SkillId
    version: str = Field(pattern=r"^[a-f0-9]{64}$")


class SkillContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    skill_id: SkillId
    purpose: str
    tools: tuple[str, ...]
    input_fields: tuple[str, ...]
    output_states: tuple[str, ...]
    human_boundary: str


CONTRACTS = (
    SkillContract(
        skill_id="inspect_reuse", purpose="Inspect existing cases and reuse only requested assets",
        tools=("get_workspace_context", "query_assets", "query_candidates",
               "query_uploaded_cases", "preview_uploaded_cases", "select_assets", "prepare_reuse"),
        input_fields=("current_goal", "authorized_scope", "observed_refs_and_versions"),
        output_states=("observed_cases", "pending_reuse_review"),
        human_boundary="Reuse/adoption and new destinations require exact human confirmation",
    ),
    SkillContract(
        skill_id="plan_test_points",
        purpose="Prepare test points for the requested uncovered goals",
        tools=("get_workspace_context", "read_attachment_evidence", "prepare_generation"),
        input_fields=("current_goal", "reference_binding", "coverage_evidence"),
        output_states=("queued", "running", "brief_awaiting_review"),
        human_boundary="Exact brief version confirmation; planning never approves generation",
    ),
    SkillContract(
        skill_id="generate_cases",
        purpose="Generate requested candidates using the brief review gate",
        tools=("get_workspace_context", "read_attachment_evidence", "prepare_generation",
               "prepare_reuse"),
        input_fields=("current_goal", "reference_binding", "requested_count", "brief_version"),
        output_states=("brief_awaiting_review", "queued", "candidate_review"),
        human_boundary="Human confirms brief; separate explicit adoption writes formal assets",
    ),
    SkillContract(
        skill_id="rewrite_cases", purpose="Revise exact selected cases and present a scoped diff",
        tools=("get_workspace_context", "read_attachment_evidence", "query_assets",
               "query_uploaded_cases", "preview_uploaded_cases", "select_assets",
               "prepare_rewrite"),
        input_fields=("current_goal", "full_selected_cases", "selection_version",
                      "reference_binding", "pending_operation_if_replaced"),
        output_states=("queued", "running", "diff_awaiting_review"),
        human_boundary="Only exact human-approved fields apply; old versions cannot be rebased",
    ),
)


def manifest(skill_id):
    contract = next((c for c in CONTRACTS if c.skill_id == skill_id), None)
    if contract is None:
        return None
    # No caller-controlled path; only server-built-in identifiers above reach this read.
    instructions = (Path(__file__).parent / f"{contract.skill_id}.md").read_text()
    data = contract.model_dump(mode="json")
    version = hashlib.sha256(json.dumps(
        {**data, "instructions": instructions}, sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    return {**data, "version": version, "instructions": instructions,
            "authority": "guidance_only", "applied": False}


def catalog():
    return [{k: v for k, v in manifest(c.skill_id).items() if k != "instructions"}
            for c in CONTRACTS]


def load(selection):
    entry = manifest(selection.skill_id)
    if entry is None or entry["version"] != selection.version:
        return {"error_code": "skill_version_changed"}
    return entry


def assert_bindings(bindings):
    if bindings is None:
        return
    if not isinstance(bindings, dict) or len(bindings) > len(CONTRACTS):
        raise HTTPException(409, "skill_version_changed")
    for skill_id, version in bindings.items():
        entry = manifest(skill_id)
        if entry is None or entry["version"] != version:
            raise HTTPException(409, "skill_version_changed")
