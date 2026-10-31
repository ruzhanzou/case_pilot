"""Current-segment output choices and bounded, content-free reference diagnostics."""

from copy import deepcopy

from agents.agent_output import AgentOutputSchema


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
        schema["properties"]["effect"]["enum"] = ["none", *sorted(effects)]
        if not effects:
            schema["properties"]["kind"]["enum"] = ["answer", "clarify"]
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
