"""Current-segment output choices and bounded, content-free reference diagnostics."""

import json
from copy import deepcopy

from agents.agent_output import AgentOutputSchema
from agents.exceptions import ModelBehaviorError

OUTCOMES = {
    "answer_none": ("answer", "none"),
    "clarify_none": ("clarify", "none"),
    "answer_read": ("answer", "read"),
    "clarify_read": ("clarify", "read"),
    "action_read": ("action", "read"),
    "action_prepare": ("action", "prepare"),
    "answer_prepare": ("answer", "prepare"),
    "clarify_prepare": ("clarify", "prepare"),
}


def pending_review_receipt(receipt):
    result = receipt.get("result", {})
    return (
        receipt.get("effect") == "prepare" and bool(receipt.get("fulfilled_actions"))
        and result.get("status") == "awaiting_input"
        and result.get("requires_human_review") is True and result.get("applied") is False
        and isinstance(result.get("proposal"), dict)
        and result["proposal"].get("status") == "pending"
    )


class CurrentReceiptSchema(AgentOutputSchema):
    """Refresh choices at each SDK request; runtime still validates every reference.

    Parsing deliberately retains the ordinary typed parser so an uncooperative
    provider reaches the existing bounded correction and fail-closed guard.
    No reference is inferred, replaced, or granted authority by this schema.
    """

    def __init__(self, output_type, receipts):
        super().__init__(output_type)
        self.receipts = receipts

    def json_schema(self):
        schema = deepcopy(super().json_schema())
        effects = {r["effect"] for r in self.receipts.values()} & {"read", "prepare"}
        choices = ["answer_none", "clarify_none"]
        if "read" in effects:
            choices += ["answer_read", "clarify_read", "action_read"]
        if "prepare" in effects:
            choices.append("action_prepare")
        if any(pending_review_receipt(r) for r in self.receipts.values()):
            choices += ["answer_prepare", "clarify_prepare"]
        del schema["properties"]["kind"], schema["properties"]["effect"]
        schema["properties"]["outcome"] = {
            "type": "string", "enum": choices,
            "description": (
                "Choose one complete reporting mode, not independent kind/effect fields. "
                "action_prepare reports actual preparation, including queued computation; "
                "it NEVER means applied or business completed. Informational prepare modes "
                "require a cited real pending human-review proposal, not a queued job."
            ),
        }
        schema["required"] = [k for k in schema["required"] if k not in {"kind", "effect"}]
        schema["required"].append("outcome")
        field = schema["properties"]["receipt_ids"]
        if self.receipts:
            field["items"]["enum"] = list(self.receipts)
        else:
            field["maxItems"] = 0
        field["description"] = (
            "Only successful receipts from THIS execution segment. Historical "
            "messages/proposals/operations are not receipt choices. Use [] when "
            "no tool effect is claimed. Preparation never authorizes application."
        )
        return schema

    def validate_json(self, json_str):
        # Decode an explicit model choice; never infer or repair a receipt/effect.
        # Legacy typed adapters still reach the unchanged runtime guards.
        try:
            value = json.loads(json_str)
        except (ValueError, TypeError):
            return super().validate_json(json_str)
        if isinstance(value, dict) and "outcome" in value:
            choice = value.pop("outcome")
            if (not isinstance(choice, str) or choice not in OUTCOMES
                    or "kind" in value or "effect" in value):
                raise ModelBehaviorError("agent_final_outcome_invalid")
            value["kind"], value["effect"] = OUTCOMES[choice]
            json_str = json.dumps(value, ensure_ascii=False)
        return super().validate_json(json_str)


def receipt_diagnostic(receipts, references, *, kind=None, effect=None):
    """Never retain arbitrary model strings, hashes of them, or prior-run IDs."""
    slots = {ref: index for index, ref in enumerate(receipts, 1)}
    return {
        **({"kind": kind} if kind in {"answer", "clarify", "action"} else {}),
        **({"effect": effect} if effect in {"none", "read", "prepare"} else {}),
        "available": [
            {"slot": slots[ref], "effect": receipt["effect"]}
            for ref, receipt in receipts.items()
        ],
        "submitted": [
            {"relation": "current", "slot": slots[ref]} if ref in slots
            else {"relation": "not_current"}
            for ref in references
        ],
    }


def safe_receipt_diagnostic(value):
    """Allowlist applied at event storage and QA extraction, including nested fields."""
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key, allowed in (("kind", ("answer", "clarify", "action")),
                         ("effect", ("none", "read", "prepare"))):
        if value.get(key) in allowed:
            clean[key] = value[key]
    for key in ("available", "submitted"):
        rows = value.get(key)
        if not isinstance(rows, list) or len(rows) > 64:
            continue
        accepted = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            slot = row.get("slot")
            valid_slot = type(slot) is int and 1 <= slot <= 64
            if key == "available" and valid_slot and row.get("effect") in (
                "read", "plan", "prepare",
            ):
                accepted.append({"slot": slot, "effect": row["effect"]})
            elif key == "submitted":
                if row.get("relation") == "current" and valid_slot:
                    accepted.append({"relation": "current", "slot": slot})
                elif row.get("relation") == "not_current":
                    accepted.append({"relation": "not_current"})
        clean[key] = accepted
    return clean
